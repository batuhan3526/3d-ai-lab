"""Poisson surface reconstruction: point cloud → GLB (textureless fast path).

No model weights needed; uses only open3d + trimesh.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np


def points_to_glb(points: np.ndarray, out_path: Path, depth: int = 8) -> Path:
    """Nokta bulutundan Poisson yüzey rekonstrüksiyonu → GLB (dokusuz).

    Args:
        points: ``(N, 3)`` float array of 3-D point positions.
        out_path: destination ``.glb`` (parent dirs are created if needed).
        depth: Poisson octree depth (6-10). Higher = finer detail but slower.

    Returns:
        The resolved ``out_path`` after the file has been written.
    """
    import open3d as o3d  # world-tracing venv: pip install open3d

    pcd = o3d.geometry.PointCloud()
    pcd.points = o3d.utility.Vector3dVector(np.asarray(points, dtype=np.float64))
    pcd.estimate_normals()
    pcd.orient_normals_consistent_tangent_plane(30)

    mesh, _ = o3d.geometry.TriangleMesh.create_from_point_cloud_poisson(pcd, depth=depth)
    mesh.compute_vertex_normals()

    import trimesh

    tm = trimesh.Trimesh(
        vertices=np.asarray(mesh.vertices),
        faces=np.asarray(mesh.triangles),
    )
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tm.export(str(out_path))
    return out_path
