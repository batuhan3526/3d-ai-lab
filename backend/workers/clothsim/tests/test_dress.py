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


# --- kayıt (register_body) + şekil denetimleri ------------------------------------
def _torso_garment(v, f, lm, s, pos, ease=1.06, depth=1.0):
    """Mankenin kendi gövde yüzeyinden kıyafet: kollar/eller hariç kalça→omuz, yatayda `ease`
    şişirilmiş, derinlik `depth` ile basık (üretim motorlarının tipik hatası), sonra
    bilinen ölçek/konumla kıyafet çerçevesine taşınmış."""
    H = lm["H"]
    keep = ~D.arm_vertices(v, lm) & (v[:, 1] > lm["levels"]["hip"] - 0.06 * H) \
        & (v[:, 1] < lm["shoulder_y"] + 0.01 * H) & (np.abs(v[:, 0]) < 1.3 * lm["shoulder_x"])
    ff = f[keep[f].all(axis=1)]
    used = np.unique(ff)
    remap = -np.ones(len(v), int)
    remap[used] = np.arange(len(used))
    g = v[used].copy()
    cz = lm["chest_z"]
    g[:, 0] *= ease
    g[:, 2] = cz + (g[:, 2] - cz) * ease * depth
    return g * s + pos, remap[ff]


def _register(gv, gf, lm, v, f, gt="shirt"):
    prof = D.garment_profile(gv, None)
    occ = D.garment_occupancy(gv, gf, 0.008 * prof["H"])
    return D.register_body(occ, prof, lm, D.body_rings(v, f, lm, gt), gt)


@pytest.mark.parametrize("depth", [1.0, 0.7])
def test_register_recovers_scale_and_position(depth):
    v, f, lm = _body()
    s_true, pos = 3.0, np.array([0.0, -0.4, 0.15])   # motor çıktıları x=0 ortalı
    gv, gf = _torso_garment(v, f, lm, s_true, pos, depth=depth)
    tr, rep = _register(gv, gf, lm, v, f)
    s = tr["scale"]
    H = lm["H"] * s_true
    assert abs(s / s_true - 1) < 0.10, rep
    # bel, kıyafetin belinde; gövde ön-arka ortada (basık derinlikte de öne kaçmaz)
    waist = lambda sc, p: lm["levels"]["waist"] * sc + p[1]  # noqa: E731
    assert abs(waist(s, tr["position"]) - waist(s_true, pos)) < 0.04 * H, rep
    cz = lambda sc, p: lm["chest_z"] * sc + p[2]  # noqa: E731
    assert abs(cz(s, tr["position"]) - cz(s_true, pos)) < 0.03 * H, rep


def test_facing_fix_turns_sideways_garment():
    v = np.random.default_rng(0).normal(size=(500, 3)) * [0.2, 1.0, 0.6]
    R = D.facing_fix(v)
    assert np.allclose(np.ptp(v @ R.T, axis=0), np.ptp(v, axis=0)[[2, 1, 0]])
    assert np.allclose(D.facing_fix(v * [3, 1, 1]), np.eye(3))


def test_shape_guard_rejects_flat_and_legged():
    v, f, lm = _body()
    with pytest.raises(ValueError, match="yatık"):
        D.check_garment_shape(v[:, [0, 2, 1]], "shirt")       # yatırılmış
    with pytest.raises(ValueError, match="bacak"):
        D.check_garment_shape(v, "shirt")                     # tam figür
    D.check_garment_shape(v, "pants")                        # alt giyimde bacak olağan
    gv, _ = _torso_garment(v, f, lm, 1.0, np.zeros(3))
    D.check_garment_shape(gv, "shirt")


def test_pole_cut_trims_stand():
    v, f, lm = _body()
    gv, _ = _torso_garment(v, f, lm, 1.0, np.zeros(3))
    y0 = gv[:, 1].min()
    pole = np.column_stack([np.random.default_rng(1).normal(0, 0.003, 400),
                            np.linspace(y0 - 0.4, y0, 400), np.full(400, lm["chest_z"])])
    prof = D.garment_profile(np.vstack([gv, pole]), None)
    cut = D.pole_cut(prof)
    assert cut is not None and y0 - 0.05 < cut <= y0 + 0.03
    assert D.pole_cut(D.garment_profile(gv, None)) is None


def test_sleeveless_arms_clear_flared_skirt():
    """Kolsuz + kloş etek: varsayılan duruşta kol eteği keser; seçilen yön kesmez."""
    v, f, lm = _body()
    H = lm["H"]
    lv = lm["levels"]
    gv, gf = _torso_garment(v, f, lm, 1.0, np.zeros(3))
    # belden aşağı geniş açılan koni (etek): bel yarıçapı → 3.5 kat, diz hizasına
    y0, y1 = lv["waist"], lv["crotch"] - 0.12 * H
    r0 = lm["waist_half"] * 1.1
    cone_v, cone_f = _tube([0, y1, lm["waist_z"]], [0, y0, lm["waist_z"]], 1.0, sections=48, rings=16)
    tt = (cone_v[:, 1] - y1) / (y0 - y1)
    rad = r0 * (1 + 2.5 * (1 - tt))
    cone_v[:, 0] *= rad
    cone_v[:, 2] = lm["waist_z"] + (cone_v[:, 2] - lm["waist_z"]) * rad
    allv = np.vstack([gv, cone_v])
    allf = np.vstack([gf, cone_f + len(gv)])
    prof = D.garment_profile(allv, None)
    occ = D.garment_occupancy(allv, allf, 0.008 * prof["H"])
    smps = {sd: D.arm_samples(v, lm, sd) for sd in (1, -1)}
    zero = np.zeros(3)
    before = max(D.arm_crossing(occ, smps[sd], D.default_arm_dir(sd), 1.0, zero) for sd in (1, -1))
    dirs, rep = D.clear_arm_dirs(occ, smps, 1.0, zero)
    after = max(D.arm_crossing(occ, smps[sd], dirs[sd], 1.0, zero) for sd in (1, -1))
    assert before > 0.03 and after < 0.5 * before, (before, after, rep)


def test_arm_root_clears_wide_bodice():
    """Gövdeden geniş kolsuz korsaj: doğal kol pozunda üst kol yan duvarı keser. Temizlik
    sonrası koltuk altı altındaki duvar kol ile gövde arasına geçer (iç yana), omuz üstü
    ve koldan uzak kumaş yerinde kalır."""
    v, f, lm = _body()
    gv, gf = _torso_garment(v, f, lm, 1.0, np.zeros(3), ease=1.35)
    dirs = {sd: D.default_arm_dir(sd) for sd in (1, -1)}
    posed = D.pose_arms(v, lm, dirs)
    am = D.arm_vertices(v, lm)
    arms = {sd: posed[am & (np.sign(v[:, 0]) == sd)] for sd in (1, -1)}
    prof = D.garment_profile(gv, None)
    occ = D.garment_occupancy(gv, gf, 0.008 * prof["H"])

    def inside(P):
        """Koltuk altı altında, üst kol silindirinin (kol boyunun %15–45'i; eksen ve
        yarıçap o köşelerden) içine düşen kumaş köşeleri."""
        n = 0
        for sd in (1, -1):
            A = arms[sd]
            t = A @ dirs[sd]
            up = (t > t.min() + 0.15 * np.ptp(t)) & (t < t.min() + 0.45 * np.ptp(t))
            c = A[up].mean(axis=0)
            ax = np.linalg.svd(A[up] - c, full_matrices=False)[2][0]
            rad = np.median(np.linalg.norm((A[up] - c) - np.outer((A[up] - c) @ ax, ax), axis=1))
            ta, gt = (A - c) @ ax, (P - c) @ ax
            q = np.linalg.norm((P - c) - np.outer(gt, ax), axis=1)
            n += int(((q < rad) & (gt > ta.min()) & (gt < ta.min() + 0.45 * np.ptp(ta))
                      & (P[:, 1] < lm["levels"]["armpit"])).sum())
        return n

    before = inside(gv)
    new, rep = D.clear_arm_roots(gv, arms, lm, dirs, 1.0, np.zeros(3), occ, 0.005)
    assert before > 0, rep
    assert inside(new) == 0, rep
    moved = np.linalg.norm(new - gv, axis=1) > 1e-9
    assert np.all(np.abs(new[moved, 0]) <= np.abs(gv[moved, 0]) + 1e-9)      # yalnız içe
    assert not moved[gv[:, 1] > lm["levels"]["armpit"] + 0.02 * lm["H"]].any()  # omuz üstü yerinde


@pytest.mark.parametrize("full,last", [
    ([1, 1, 1, 0, 0, 0], 2),          # kısa kolluk: omuzdan başlar
    ([0, 1, 1, 1, 0, 1, 1], 6),       # ilk kesit açık (geniş kolluk ağzı), tek boşluk tolere
    ([1, 1, 0, 0, 1, 1], 1),          # iki boşluk: kolluk biter
    ([0, 0, 1, 1, 1, 0], 4),          # geniş omuz başı: sarılma 3. kesitte başlar
    ([0, 0, 0, 1, 1, 1], -1),         # yalnız dirsekten aşağı sarılma: bol etek, kolluk değil
])
def test_sleeve_run_starts_at_shoulder(full, last):
    assert D.sleeve_run(np.array(full, float)) == last
