"""
Garment-to-SMPL skinning weight transfer and Linear Blend Skinning (LBS) deformation.

Pipeline:
  1. transfer_skin_weights(garment_v, body_v, body_weights, k=4)
     → inverse-distance-weighted nearest-neighbour transfer
  2. apply_lbs(garment_v_rest, garment_weights, bone_transforms)
     → per-frame deformed garment vertices [nframes, garment_V, 3]
"""
from __future__ import annotations

import numpy as np
from scipy.spatial import cKDTree


def transfer_skin_weights(
    garment_v: np.ndarray,
    body_v: np.ndarray,
    body_weights: np.ndarray,
    k: int = 4,
) -> np.ndarray:
    """Transfer skinning weights from body vertices to garment vertices.

    Uses inverse-distance-weighted interpolation over the k nearest body
    neighbours for each garment vertex.

    Args:
        garment_v:    (G, 3) garment vertex positions in rest pose.
        body_v:       (B, 3) SMPL body vertex positions in rest pose.
        body_weights: (B, J) per-vertex skinning weights for J joints.
                      Rows must already be normalised (sum to 1).
        k:            Number of nearest body vertices to use.

    Returns:
        (G, J) skinning weights for the garment, rows normalised to 1.
    """
    garment_v = np.asarray(garment_v, dtype=np.float64)
    body_v = np.asarray(body_v, dtype=np.float64)
    body_weights = np.asarray(body_weights, dtype=np.float64)

    tree = cKDTree(body_v)
    d, idx = tree.query(garment_v, k=k)  # (G, k) or (G,) when k=1

    # Ensure 2-D arrays even when k=1
    if k == 1:
        d = d[:, np.newaxis]
        idx = idx[:, np.newaxis]

    # Inverse-distance interpolation: avoid division by zero at exact hits
    inv = 1.0 / (d + 1e-6)              # (G, k)
    inv /= inv.sum(axis=1, keepdims=True)  # normalise to 1 across k neighbours

    # Weighted sum over k neighbours: (G, k) × (G, k, J) → (G, J)
    w = np.einsum("nk,nkj->nj", inv, body_weights[idx])

    # Re-normalise rows (should already sum to 1, but guards floating-point drift)
    row_sums = w.sum(axis=1, keepdims=True)
    return w / row_sums


def apply_lbs(
    garment_v_rest: np.ndarray,
    garment_weights: np.ndarray,
    bone_transforms: np.ndarray,
) -> np.ndarray:
    """Deform garment vertices with Linear Blend Skinning.

    Args:
        garment_v_rest:  (G, 3) rest-pose garment vertices.
        garment_weights: (G, J) skinning weights (rows sum to 1).
        bone_transforms: (nframes, J, 4, 4) per-frame per-joint 4×4 transforms.

    Returns:
        (nframes, G, 3) deformed garment vertex positions.
    """
    G = garment_v_rest.shape[0]
    nframes, J = bone_transforms.shape[:2]

    # Homogeneous rest vertices: (G, 4)
    ones = np.ones((G, 1), dtype=np.float64)
    v_h = np.concatenate([garment_v_rest, ones], axis=1)  # (G, 4)

    # Weighted transform per vertex: (nframes, G, 4, 4)
    # garment_weights: (G, J) → broadcast with bone_transforms (nframes, J, 4, 4)
    # w_T[f, g, :, :] = sum_j w[g,j] * T[f,j,:,:]
    w = garment_weights.astype(np.float64)  # (G, J)
    T = bone_transforms.astype(np.float64)  # (nframes, J, 4, 4)

    # einsum: "gj, fjkl -> fgkl"
    blended = np.einsum("gj,fjkl->fgkl", w, T)  # (nframes, G, 4, 4)

    # Apply to homogeneous vertices: (nframes, G, 4, 4) @ (G, 4) → (nframes, G, 4)
    # Use broadcasting: blended @ v_h[..., None]  then squeeze
    v_deformed = (blended @ v_h[np.newaxis, :, :, np.newaxis])[..., 0]  # (nframes, G, 4)

    return v_deformed[..., :3]  # drop homogeneous component
