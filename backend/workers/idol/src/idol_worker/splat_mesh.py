"""3D Gaussian splat → vertex-coloured triangle mesh (no CUDA, no normal estimation).

Idol's Gaussians are small and dense on the object's surface, so their centres sample the
surface well. Steps:
  1. keep Gaussians that are visible (opacity ≥ min_opacity),
  2. mark the voxels they fall in on a res³ grid, close 1-voxel gaps,
  3. thicken by one voxel (no leaks, thin fabric survives smoothing), then fill cavities that
     are fully enclosed (solid objects become solid; a garment whose inside is connected to the
     outside through its neck/sleeve openings stays open),
  4. drop floating fragments (<1 % of the largest piece), smooth, marching cubes at 0.5,
  5. colour each vertex from its nearest Gaussians (opacity-weighted).
Input coordinates are Idol's z-up object frame inside [-0.5, 0.5]³.
"""
from __future__ import annotations

import numpy as np

SH_C0 = 0.28209479177387814


def gaussian_colors(features_dc: np.ndarray) -> np.ndarray:
    """Degree-0 SH coefficients [N, 3] → linear RGB in [0, 1]."""
    return np.clip(0.5 + SH_C0 * features_dc, 0.0, 1.0)


def splat_to_mesh(xyz: np.ndarray, rgb: np.ndarray, opacity: np.ndarray, *, resolution: int = 256,
                  min_opacity: float = 0.1, closing: int = 1, smooth_sigma: float = 0.8,
                  min_component: float = 0.01,
                  k_colors: int = 4):
    """Return (vertices [V,3] float32, faces [F,3] int64, colors [V,3] uint8) in the input frame."""
    from scipy import ndimage
    from scipy.spatial import cKDTree
    from skimage.measure import marching_cubes

    opacity = opacity.reshape(-1)
    keep = opacity >= min_opacity
    if keep.sum() < 100:
        raise ValueError("splat has too few visible Gaussians to build a mesh")
    pts, cols, ops = xyz[keep], rgb[keep], opacity[keep]

    lo = pts.min(0)
    hi = pts.max(0)
    pad = 3  # voxels of empty border so marching cubes closes the surface
    size = float((hi - lo).max())
    voxel = size / (resolution - 2 * pad)
    origin = lo - pad * voxel
    idx = np.floor((pts - origin) / voxel).astype(np.int64)
    dims = np.ceil((hi - origin) / voxel).astype(np.int64) + pad + 1
    idx = np.clip(idx, 0, dims - 1)

    occ = np.zeros(dims, dtype=bool)
    occ[idx[:, 0], idx[:, 1], idx[:, 2]] = True
    if closing > 0:
        occ = ndimage.binary_closing(occ, iterations=closing, border_value=0)
    # A 1-voxel sheet leaks (diagonal steps let the outside reach the inside, so cavities are not
    # filled) and falls below 0.5 once smoothed (an open garment's fabric would vanish): thicken it
    # by one voxel on each side first (solid objects grow by ~1 voxel, i.e. <0.5 %).
    occ = ndimage.binary_dilation(occ, iterations=1)
    occ = ndimage.binary_fill_holes(occ)
    # drop floaters: connected pieces smaller than min_component of the largest one
    labels, n = ndimage.label(occ)
    if n > 1:
        sizes = np.bincount(labels.ravel())
        sizes[0] = 0
        occ = sizes[labels] >= max(1, int(min_component * sizes.max()))
    field = ndimage.gaussian_filter(occ.astype(np.float32), sigma=smooth_sigma) if smooth_sigma > 0 \
        else occ.astype(np.float32)

    verts, faces, _normals, _vals = marching_cubes(field, level=0.5)
    verts = verts * voxel + origin
    verts, faces = _drop_small_pieces(verts, faces, min_component)
    faces = faces[:, ::-1]  # skimage winds inward for "inside = higher value" → outward normals

    tree = cKDTree(pts)
    k = min(k_colors, len(pts))
    dist, nn = tree.query(verts, k=k)
    if k == 1:
        dist, nn = dist[:, None], nn[:, None]
    w = ops[nn] / np.maximum(dist, 1e-6)
    color = (cols[nn] * w[..., None]).sum(1) / w.sum(1, keepdims=True)
    return verts.astype(np.float32), faces.astype(np.int64), (np.clip(color, 0, 1) * 255).astype(np.uint8)


def _drop_small_pieces(verts: np.ndarray, faces: np.ndarray, min_component: float):
    """Marching cubes leaves sub-voxel slivers where voxels touch only diagonally; keep the
    surface pieces with at least min_component of the largest piece's faces."""
    import trimesh

    labels = trimesh.graph.connected_component_labels(trimesh.graph.face_adjacency(faces),
                                                      node_count=len(faces))
    sizes = np.bincount(labels)
    keep_faces = faces[sizes[labels] >= max(1, int(min_component * sizes.max()))]
    used = np.unique(keep_faces)
    remap = np.full(len(verts), -1, dtype=np.int64)
    remap[used] = np.arange(len(used))
    return verts[used], remap[keep_faces]


def front_to_viewer(xyz: np.ndarray, camera: dict | None) -> np.ndarray:
    """Idol z-up object frame → glTF y-up frame with the input photo's view facing +Z.

    The predicted camera yaw (atan2(dx, dy) of the camera direction) is turned to the viewer's
    default front; pitch is ignored (the object keeps standing upright)."""
    yaw = float(camera.get("yaw", 0.0)) if camera else 0.0
    # camera direction in the xy plane sits at angle (pi/2 - yaw); rotate it to -pi/2 (→ +Z after
    # the axis swap below)
    theta = -np.pi / 2 - (np.pi / 2 - yaw)
    c, s = np.cos(theta), np.sin(theta)
    x = c * xyz[:, 0] - s * xyz[:, 1]
    y = s * xyz[:, 0] + c * xyz[:, 1]
    z = xyz[:, 2]
    # z-up → y-up: (x, y, z) → (x, z, -y)
    return np.stack([x, z, -y], axis=1)
