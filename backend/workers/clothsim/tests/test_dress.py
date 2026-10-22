"""Mankene giydir (dress.py): kol pozu araması, otomatik hiza, kolsuz/alt giyim.

Sentetik kıyafetler (tüp gövde + tüp kolluklar) gerçek T-poz manken (female-a) ile
denenir: kol yönü kolluğun yönünü izlemeli, kolsuzda doğal duruş, alt giyimde bel hizası."""
from __future__ import annotations

import math
import pathlib
import sys

import numpy as np
import pytest
import trimesh

_SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from clothsim_worker import dress as D  # noqa: E402

MQ = pathlib.Path(__file__).resolve().parents[4] / "data/templates/mannequins/female-a.glb"
pytestmark = pytest.mark.skipif(not MQ.exists(), reason="manken GLB yok")


def _body():
    b = trimesh.load(MQ, force="mesh", process=False)
    v, f = np.asarray(b.vertices, float), np.asarray(b.faces)
    return v, f, D.body_landmarks(v, f)


def _tube(p0, p1, r, sections=24, rings=12):
    """p0→p1 ekseninde açık uçlu silindir yüzeyi."""
    p0, p1 = np.asarray(p0, float), np.asarray(p1, float)
    a = p1 - p0
    a /= np.linalg.norm(a)
    t = np.cross(a, [0, 0, 1.0] if abs(a[2]) < 0.9 else [1.0, 0, 0])
    t /= np.linalg.norm(t)
    b = np.cross(a, t)
    V, F = [], []
    for i in range(rings + 1):
        c = p0 + (p1 - p0) * i / rings
        for j in range(sections):
            ang = 2 * math.pi * j / sections
            V.append(c + r * (math.cos(ang) * t + math.sin(ang) * b))
    for i in range(rings):
        for j in range(sections):
            a0, a1 = i * sections + j, i * sections + (j + 1) % sections
            b0, b1 = a0 + sections, a1 + sections
            F += [[a0, b0, a1], [a1, b0, b1]]
    return np.array(V), np.array(F)


def _garment(lm, s, pos, sleeve_deg: float | None):
    """Bedeni saran gövde tüpü + (verilirse) omuzdan sleeve_deg açıyla kolluk tüpleri."""
    H = lm["H"] * s
    lv = lm["levels"]
    top = lv["armpit"] * s + pos[1] + 0.06 * H
    bot = lv["hip"] * s + pos[1] - 0.05 * H
    parts = [_tube([0, bot, pos[2]], [0, top, pos[2]], (lm["chest_half"] * s) * 1.6)]
    if sleeve_deg is not None:
        o = math.radians(sleeve_deg)
        for side in (1, -1):
            piv = np.array([side * lm["shoulder_x"] * 0.8, lm["arm_cy"], lm["arm_cz"]]) * s + pos
            d = np.array([side * math.sin(o), -math.cos(o), 0.0])
            parts.append(_tube(piv + 0.06 * H * d, piv + 0.30 * H * d, 0.035 * H))
    V, F, off = [], [], 0
    for v, f in parts:
        V.append(v)
        F.append(f + off)
        off += len(v)
    return np.concatenate(V), np.concatenate(F)


@pytest.mark.parametrize("deg", [15, 45, 90])
def test_arm_follows_sleeve_direction(deg):
    v, f, lm = _body()
    s, pos = 2.0, np.array([0.0, -0.45, 0.0])
    gv, gf = _garment(lm, s, pos, deg)
    occ = D.garment_occupancy(gv, gf, 0.008 * float(np.ptp(gv[:, 1])))
    dirs, rep = D.search_arm_dirs(occ, lm, s, pos)
    got = rep["1"]["deg_from_vertical"]
    assert abs(got - deg) <= 12, rep


def test_sleeveless_falls_back_to_natural_pose():
    v, f, lm = _body()
    s, pos = 2.0, np.array([0.0, -0.45, 0.0])
    gv, gf = _garment(lm, s, pos, None)
    occ = D.garment_occupancy(gv, gf, 0.008 * float(np.ptp(gv[:, 1])))
    dirs, _ = D.search_arm_dirs(occ, lm, s, pos)
    assert np.allclose(dirs[1], D.default_arm_dir(1))


def test_pose_arms_moves_only_arms():
    v, f, lm = _body()
    posed = D.pose_arms(v, lm, {1: D.default_arm_dir(1), -1: D.default_arm_dir(-1)})
    arm = D.arm_vertices(v, lm)
    head = v[:, 1] > lm["levels"]["neck"] + 0.03 * lm["H"]
    assert np.allclose(posed[head], v[head])                     # baş yerinde
    hand = np.argmax(np.abs(v[:, 0]) * arm)
    assert posed[hand, 1] < v[hand, 1] - 0.2 * lm["H"]           # el aşağı indi


def test_bottom_auto_transform_puts_waist_at_top():
    v, f, lm = _body()
    gv, gf = _tube([0, -0.5, 0], [0, 0.5, 0], 0.30)
    prof = D.garment_profile(gv, gf)
    tr = D.auto_transform(prof, lm, "skirt")
    waist_y = lm["levels"]["waist"] * tr["scale"] + tr["position"][1]
    assert abs(waist_y - 0.5) < 0.05 and tr["anchor"] == "waist"


def test_unsupported_type_rejected(tmp_path):
    with pytest.raises(ValueError):
        D.dress_glb(str(tmp_path / "x.glb"), str(MQ), "boots", str(tmp_path / "o.glb"), str(tmp_path / "m.glb"))


@pytest.mark.parametrize("ratio,gt,ok", [(0.45, "tshirt", True), (0.71, "shirt", True),
                                         (0.92, "tshirt", False), (0.60, "pants", True),
                                         (1.05, "skirt", False)])
def test_garment_span_guard(ratio, gt, ok):
    # Tam insan figürü (oran ~1.0) kıyafet diye oturtulmasın; gerçek kıyafetler geçsin.
    if ok:
        D.check_garment_span(ratio, 1.0, gt)
    else:
        with pytest.raises(ValueError, match="kıyafete benzemiyor"):
            D.check_garment_span(ratio, 1.0, gt)
