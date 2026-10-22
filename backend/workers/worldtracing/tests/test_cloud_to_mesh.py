"""TDD test: synthetic sphere point cloud → GLB via Poisson surface reconstruction."""
import numpy as np
from worldtracing_worker.cloud_to_mesh import points_to_glb
from pathlib import Path


def test_points_to_glb_creates_valid_mesh(tmp_path):
    # Sample N points from a unit sphere surface
    rng = np.random.default_rng(0)
    v = rng.normal(size=(2000, 3))
    v /= np.linalg.norm(v, axis=1, keepdims=True)
    out = tmp_path / "s.glb"
    p = points_to_glb(v, out)
    assert p.exists() and p.stat().st_size > 0, "GLB file not created or empty"
    import trimesh
    loaded = trimesh.load(str(p))
    # trimesh.load() may return a Scene for GLB; extract the first mesh if needed.
    if isinstance(loaded, trimesh.Scene):
        meshes = [g for g in loaded.geometry.values() if isinstance(g, trimesh.Trimesh)]
        assert meshes, "Scene contains no Trimesh geometry"
        m = meshes[0]
    else:
        m = loaded
    assert len(m.vertices) > 100, f"Too few vertices: {len(m.vertices)}"
    assert len(m.faces) > 100, f"Too few faces: {len(m.faces)}"
