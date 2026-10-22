"""Mankene oturtma (fit_garment): beden dışına itme, katman sırası, derin/uzak parçalar."""
from __future__ import annotations

import pathlib
import sys

import numpy as np
import trimesh

_SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from clothsim_worker.fit_garment import body_samples, fit_glb, fit_vertices  # noqa: E402

BODY_R = 0.30


def _body():
    s = trimesh.creation.icosphere(subdivisions=4, radius=BODY_R)
    return body_samples(s.vertices, s.faces, n=60_000)


def _radii(v):
    return np.linalg.norm(v, axis=1)


def test_poking_fabric_is_pushed_outside_body():
    bp, bn = _body()
    g = trimesh.creation.icosphere(subdivisions=3, radius=0.29)  # beden içinde (1 cm taşma)
    new, rep = fit_vertices(g.vertices, g.faces, bp, bn, margin=0.01)
    assert rep["inside_before"] > 0 and rep["inside_after"] == 0
    assert _radii(new).min() > BODY_R  # hepsi beden dışında


def test_far_fabric_untouched():
    bp, bn = _body()
    g = trimesh.creation.icosphere(subdivisions=2, radius=0.60)  # bedenden uzak
    new, rep = fit_vertices(g.vertices, g.faces, bp, bn, margin=0.01)
    assert np.allclose(new, g.vertices) and rep["moved"] == 0


def test_double_shell_order_preserved():
    bp, bn = _body()
    outer = trimesh.creation.icosphere(subdivisions=3, radius=0.295)
    inner = trimesh.creation.icosphere(subdivisions=3, radius=0.285)
    v = np.concatenate([outer.vertices, inner.vertices])
    f = np.concatenate([outer.faces, inner.faces + len(outer.vertices)])
    new, _ = fit_vertices(v, f, bp, bn, margin=0.01)
    ro, ri = _radii(new[: len(outer.vertices)]), _radii(new[len(outer.vertices):])
    # Aynı yönlerdeki köşeler (icosphere'ler aynı topoloji): dış kabuk iç kabuğun dışında kalır.
    assert (ro >= ri - 1e-6).all()


def test_deep_interior_parts_left_alone():
    bp, bn = _body()
    core = trimesh.creation.icosphere(subdivisions=2, radius=0.15)  # bedenin 15 cm içinde
    new, rep = fit_vertices(core.vertices, core.faces, bp, bn, margin=0.01, deep=0.04)
    assert np.allclose(new, core.vertices)


def test_fit_glb_applies_mannequin_transform_and_keeps_uv(tmp_path):
    # Manken: birim küre (yerel), Designer transform'u ile 0.30 yarıçapa ölçeklenip ötelenir.
    man = trimesh.creation.icosphere(subdivisions=4, radius=1.0)
    man.export(tmp_path / "man.glb")
    g = trimesh.creation.icosphere(subdivisions=3, radius=0.29)
    g.apply_translation([0, 0.5, 0])
    uv = np.random.default_rng(0).random((len(g.vertices), 2))
    g.visual = trimesh.visual.TextureVisuals(uv=uv)
    trimesh.Scene(g).export(tmp_path / "g.glb")
    rep = fit_glb(str(tmp_path / "g.glb"), str(tmp_path / "man.glb"),
                  {"position": [0, 0.5, 0], "rotation": [0, 0, 0], "scale": BODY_R},
                  str(tmp_path / "out.glb"), margin=0.01)
    out = trimesh.load(tmp_path / "out.glb").to_geometry()
    assert np.linalg.norm(out.vertices - [0, 0.5, 0], axis=1).min() > BODY_R
    assert out.visual.uv is not None and len(out.visual.uv) == len(out.vertices)
    assert list(rep["geometries"].values())[0]["inside_after"] == 0


def test_align_sleeves_moves_sleeve_onto_arm_but_not_torso():
    from clothsim_worker.fit_garment import align_sleeves
    rng = np.random.default_rng(1)
    ys = rng.uniform(-0.5, 0.0, 3000)
    th = rng.uniform(0, 2 * np.pi, 3000)
    # Gövde paneli: x ∈ [-0.15, 0.15] düz levha; kolluklar: yanlarda r=0.06 silindir,
    # merkez (±0.25, z=+0.05). Kollar: r=0.03 silindir, merkez (±0.25, z=0).
    torso = np.column_stack([rng.uniform(-0.15, 0.15, 3000), ys, np.zeros(3000)])
    sleeves, arms = [], []
    for s in (1, -1):
        sleeves.append(np.column_stack([s * 0.25 + 0.06 * np.cos(th), ys, 0.05 + 0.06 * np.sin(th)]))
        arms.append(np.column_stack([s * 0.25 + 0.03 * np.cos(th), ys, 0.03 * np.sin(th)]))
    gv = np.concatenate([torso, *sleeves])
    new, rep = align_sleeves(gv, np.concatenate(arms), max_shift=0.10)
    assert np.allclose(new[:3000], torso)  # gövde paneli yerinde
    lower = (ys < -0.2)  # omuz rampasının altı
    sl = new[3000:6000][lower]
    assert abs(sl[:, 2].mean()) < 0.01  # kolluk kolun üzerine (z≈0) kaydı
    assert rep["side+1"]["slices"] > 5
