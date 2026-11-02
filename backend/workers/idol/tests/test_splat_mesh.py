"""splat_mesh: Gaussian merkezlerinden mesh (sentetik splat'larla, GPU/model gerekmez).

Çalıştırmak için skimage/scipy gerekir (Idol venv'inde var; çekirdek venv'de yoksa atlanır)."""
from __future__ import annotations

import pathlib
import sys

import numpy as np
import pytest

pytest.importorskip("skimage")
pytest.importorskip("scipy")
trimesh = pytest.importorskip("trimesh")

_SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from idol_worker.splat_mesh import front_to_viewer, gaussian_colors, splat_to_mesh  # noqa: E402


def _sphere(n=60000, r=0.3, seed=0):
    rng = np.random.default_rng(seed)
    v = rng.normal(size=(n, 3))
    return v / np.linalg.norm(v, axis=1, keepdims=True) * r


def test_sphere_is_closed_and_outward():
    xyz = _sphere()
    rgb = np.where(xyz[:, :1] > 0, [[1.0, 0.0, 0.0]], [[0.0, 0.0, 1.0]])
    verts, faces, colors = splat_to_mesh(xyz, rgb, np.ones(len(xyz)), resolution=96)
    m = trimesh.Trimesh(verts, faces, process=True)
    assert m.is_watertight
    assert m.volume > 0  # normaller dışa bakıyor
    assert abs(np.linalg.norm(m.vertices, axis=1).mean() - 0.3) < 0.02
    # renk taşındı: +x yarısı kırmızı, -x yarısı mavi
    right = verts[:, 0] > 0.1
    left = verts[:, 0] < -0.1
    assert colors[right, 0].mean() > 200 and colors[right, 2].mean() < 50
    assert colors[left, 2].mean() > 200 and colors[left, 0].mean() < 50


def test_open_tube_is_not_filled():
    """Ucu açık tüp (kollu kıyafetin gövdesi gibi): içi doldurulmamalı, ortası boş kalmalı."""
    rng = np.random.default_rng(1)
    t = rng.uniform(0, 2 * np.pi, 80000)
    z = rng.uniform(-0.4, 0.4, 80000)
    xyz = np.stack([0.25 * np.cos(t), 0.25 * np.sin(t), z], 1)
    verts, faces, _ = splat_to_mesh(xyz, np.full((len(xyz), 3), 0.5), np.ones(len(xyz)), resolution=96)
    radial = np.linalg.norm(verts[:, :2], axis=1)
    assert radial.min() > 0.2  # eksende yüzey yok → tüp açık
    assert verts[:, 2].min() < -0.38 and verts[:, 2].max() > 0.38


def test_low_opacity_gaussians_are_ignored():
    xyz = np.concatenate([_sphere(), np.full((5000, 3), 0.45)])  # köşede görünmez bulut
    op = np.concatenate([np.ones(60000), np.full(5000, 0.01)])
    verts, _, _ = splat_to_mesh(xyz, np.full((len(xyz), 3), 0.5), op, resolution=96)
    assert verts.max() < 0.35


def test_too_few_visible_gaussians_raises():
    with pytest.raises(ValueError):
        splat_to_mesh(np.zeros((50, 3)), np.zeros((50, 3)), np.ones(50))


def test_front_to_viewer_turns_camera_side_to_plus_z_and_z_up_to_y_up():
    # kamera +x tarafında (yaw = atan2(dx, dy) = pi/2): +x'teki nokta görüntüleyicide +Z'ye gelmeli
    p = front_to_viewer(np.array([[0.3, 0.0, 0.0], [0.0, 0.0, 0.4]]), {"yaw": np.pi / 2})
    assert np.allclose(p[0], [0, 0, 0.3], atol=1e-6)
    assert np.allclose(p[1], [0, 0.4, 0], atol=1e-6)  # z-up → y-up
    # yaw=0: kamera +y tarafında
    p = front_to_viewer(np.array([[0.0, 0.3, 0.0]]), {"yaw": 0.0})
    assert np.allclose(p[0], [0, 0, 0.3], atol=1e-6)


def test_gaussian_colors_range():
    c = gaussian_colors(np.array([[0.0, 10.0, -10.0]]))
    assert np.allclose(c, [[0.5, 1.0, 0.0]])


def test_floaters_are_dropped():
    xyz = np.concatenate([_sphere(), np.random.default_rng(2).normal(0.42, 0.003, size=(200, 3))])
    verts, faces, _ = splat_to_mesh(xyz, np.full((len(xyz), 3), 0.5), np.ones(len(xyz)), resolution=96)
    m = trimesh.Trimesh(verts, faces)
    assert m.body_count == 1 and verts.max() < 0.35
