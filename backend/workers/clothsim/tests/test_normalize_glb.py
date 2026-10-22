"""sew3d çıktısı kanonik görüntüleme çerçevesine ([-0.5, 0.5], merkez orijin) normalize
edilmeli — Tasarımcı mesh'i olduğu gibi gösterir; metre ölçekli manken uzayındaki
kıyafet (y≈1.2 m) kameranın dışında kalıyordu (2026-10-17 canlı E2E)."""
from __future__ import annotations

import pathlib
import sys

import numpy as np
import trimesh

_SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from clothsim_worker.worker import _normalize_glb  # noqa: E402


def _metric_glb(path: pathlib.Path) -> None:
    box = trimesh.creation.box(extents=(0.58, 0.46, 0.30))
    box.apply_translation((0.0, 1.18, 0.0))
    box.visual = trimesh.visual.TextureVisuals(
        material=trimesh.visual.material.PBRMaterial(name="kumas", baseColorFactor=[200, 30, 30, 255],
                                                     roughnessFactor=0.8))
    # Blender gibi nesne adlı kök düğüm (trimesh "world" adını taban çerçeve sayar).
    trimesh.Scene(box, base_frame="kiyafet").export(path)


def test_normalize_glb_unit_frame(tmp_path):
    src = tmp_path / "mesh.glb"
    _metric_glb(src)
    info = _normalize_glb(src)
    lo, hi = trimesh.load(src).bounds
    assert np.allclose((lo + hi) / 2, 0.0, atol=1e-5)
    assert abs((hi - lo).max() - 1.0) < 1e-5
    # Dönüşüm geri alınabilir şekilde raporlanır: metre = norm / scale + center
    assert abs(info["scale"] - 1 / 0.58) < 1e-4
    assert np.allclose(info["center_m"], [0.0, 1.18, 0.0], atol=1e-5)


def test_normalize_glb_keeps_material(tmp_path):
    src = tmp_path / "mesh.glb"
    _metric_glb(src)
    _normalize_glb(src)
    geom = list(trimesh.load(src).geometry.values())[0]
    assert geom.visual.material.name == "kumas"
    assert abs(float(geom.visual.material.roughnessFactor) - 0.8) < 1e-6
