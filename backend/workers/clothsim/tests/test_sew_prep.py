"""F2 dikiş hazırlığı (sew_prep) + clothsim.sew3d task testleri.

bpy'siz kısımlar saf Python'da test edilir (üçgenleme, dikiş eşleme, aynalama,
yerleşim). Gerçek Blender testi yerel kurulum varsa koşar (yoksa atlanır); gerçek
taban manken GLB'si (data/templates/mannequins) yoksa ilgili testler atlanır.
"""
import json
import math
import os
import pathlib
import shutil
import sys

import fakeredis
import numpy as np
import pytest

_SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from clothsim_worker import sew_prep as sp  # noqa: E402

_DATA = pathlib.Path(__file__).resolve().parents[4] / "data"
_FEMALE = _DATA / "templates" / "mannequins" / "female-a.glb"
_BLENDER = os.getenv("BLENDER_BIN") or shutil.which("blender") or os.path.join(os.getenv("ENGINES_DIR", str(pathlib.Path(__file__).resolve().parents[4] / "engines")), "blender", "blender")


def _blender_bin():
    return _BLENDER if pathlib.Path(_BLENDER).exists() else None


# --- sentetik kalıp ---------------------------------------------------------------
def _rect(w, h, n_side=1):
    """CCW dikdörtgen poligonu (sol alt (0,0)), kenar başına n_side alt-nokta."""
    pts = []
    for (x0, y0), (x1, y1) in (((0, 0), (w, 0)), ((w, 0), (w, h)), ((w, h), (0, h)), ((0, h), (0, 0))):
        for k in range(n_side):
            t = k / n_side
            pts.append([x0 + (x1 - x0) * t, y0 + (y1 - y0) * t])
    return pts


def _tube_doc(w=260.0, h=420.0):
    """Ön (katlı, merkez x=0) + arka (katlı) iki yarım panel; yan dikişlerle tüp."""
    def panel(name):
        poly = _rect(w, h, n_side=4)  # 16 nokta: 0 alt-sol, 4 alt-sağ, 8 üst-sağ, 12 üst-sol
        return {
            "name": name, "label_tr": name, "quantity": 1, "mirror": True,
            "fold_edge": f"{name}.cf",
            "seam_line": poly, "cut_line": poly, "grain_deg": 90.0,
            "edges": [
                {"id": f"{name}.hem", "from": 0, "to": 4},
                {"id": f"{name}.side", "from": 4, "to": 8},
                {"id": f"{name}.top", "from": 8, "to": 12},
                {"id": f"{name}.cf", "from": 12, "to": 0},
            ],
        }
    return {"pattern_id": "t", "design": "test-tube", "units": "mm", "sa_mm": 10,
            "measurements": {}, "pieces": [panel("front"), panel("back")],
            "seams": [{"a": "front.side", "b": "back.side", "reverse": False}]}


# --- temel geometri ---------------------------------------------------------------
def test_polyline_indices_wraps():
    assert sp.polyline_indices(6, 4, 1) == [4, 5, 0, 1]
    assert sp.polyline_indices(6, 1, 3) == [1, 2, 3]


def test_resample_keeps_endpoints_and_uniform():
    line = np.array([[0.0, 0.0], [100.0, 0.0], [100.0, 50.0]])
    r = sp.resample(line, 6)
    assert len(r) == 7
    assert np.allclose(r[0], [0, 0]) and np.allclose(r[-1], [100, 50])
    seg = np.linalg.norm(np.diff(r, axis=0), axis=1)
    assert seg.max() - seg.min() < 1e-6 or abs(seg.sum() - 150.0) < 30  # köşe kesimi
    assert abs(sp.sample_at(line, [0.5])[0][0] - 75.0) < 1e-9


def test_points_in_polygon_and_reflect():
    sq = np.array(_rect(10, 10))
    inside = sp.points_in_polygon(np.array([[5, 5], [15, 5], [-1, 2]]), sq)
    assert inside.tolist() == [True, False, False]
    r = sp.reflect(np.array([[3.0, 2.0]]), np.array([0.0, 0.0]), np.array([0.0, 1.0]))
    assert np.allclose(r, [[-3.0, 2.0]])


def test_triangulate_concave_polygon_complete():
    """L şekli (içbükey): tüm sınır parçaları üçgenlemede, alan tam, üçgenler CCW."""
    L = np.array([[0, 0], [200, 0], [200, 80], [80, 80], [80, 200], [0, 200]], dtype=float)
    loop = np.concatenate([sp.resample(np.vstack([L[i], L[(i + 1) % 6]]), 10)[:-1] for i in range(6)])
    pts, faces, missing = sp.triangulate_loop(loop, 12.0)
    assert missing == []
    a = pts[faces]
    area = 0.5 * ((a[:, 1, 0] - a[:, 0, 0]) * (a[:, 2, 1] - a[:, 0, 1])
                  - (a[:, 1, 1] - a[:, 0, 1]) * (a[:, 2, 0] - a[:, 0, 0]))
    assert (area > 0).all()
    assert abs(area.sum() - (200 * 200 - 120 * 120)) < 1.0
    # Ortalama kenar ≈ h (düzgün mesh)
    e = np.concatenate([np.linalg.norm(a[:, i] - a[:, (i + 1) % 3], axis=1) for i in range(3)])
    assert 9.0 < np.median(e) < 15.0


def test_triangulate_thin_dart_notch():
    """Pens gibi dar V çentikli kenar: çentik içi üçgenlenmez, sınır eksiksiz."""
    poly = np.array([[0, 0], [300, 0], [300, 200], [160, 200], [150, 90], [140, 200], [0, 200]], float)
    piece = {"name": "p", "label_tr": "P", "seam_line": poly.tolist(),
             "edges": [{"id": "p.a", "from": 3, "to": 4}, {"id": "p.b", "from": 4, "to": 5}]}
    fr, uf = sp.edge_sampling([piece], [{"a": "p.a", "b": "p.b", "reverse": True}], 12.0)
    m = sp.build_piece_mesh(piece, fr, uf, 12.0)
    assert len(m["edges"]["p.a"]) == len(m["edges"]["p.b"])
    cent = m["pts"][m["faces"]].mean(axis=1)
    assert sp.points_in_polygon(cent, poly).all()


# --- dikiş örnekleme / aynalama -----------------------------------------------------
def test_edge_sampling_equal_counts_for_seam_pairs():
    doc = _tube_doc()
    doc["pieces"][1]["seam_line"] = _rect(260.0, 380.0, 4)  # arka yan kenarı daha kısa
    fr, _uf = sp.edge_sampling(doc["pieces"], doc["seams"], 12.0)
    assert len(fr["front.side"]) == len(fr["back.side"])
    assert len(fr["front.side"]) - 1 == round(420 / 12)  # uzun olan belirler


def test_reverse_seam_fractions_mirrored():
    pieces = _tube_doc()["pieces"]
    fr, _ = sp.edge_sampling(pieces, [{"a": "front.side", "b": "back.side", "reverse": True}], 25.0)
    a, b = np.array(fr["front.side"]), np.array(fr["back.side"])
    assert np.allclose(a, 1.0 - b[::-1])


def test_fold_instance_mirrors_and_doubles_area():
    doc = _tube_doc()
    p = doc["pieces"][0]
    fr, uf = sp.edge_sampling(doc["pieces"], doc["seams"], 12.0)
    m = sp.build_piece_mesh(p, fr, uf, 12.0)
    (inst,) = sp.piece_instances(p, m)
    n_fold = len(m["edges"]["front.cf"])
    assert inst["side"] == "F"
    assert len(inst["pts"]) == 2 * len(m["pts"]) - n_fold
    assert "front.side@R" in inst["edges"] and "front.side@L" in inst["edges"]
    assert "front.cf@R" not in inst["edges"]  # katlama kenarı dikilmez, iç çizgi olur
    a = inst["pts"][inst["faces"]]
    area = 0.5 * ((a[:, 1, 0] - a[:, 0, 0]) * (a[:, 2, 1] - a[:, 0, 1])
                  - (a[:, 1, 1] - a[:, 0, 1]) * (a[:, 2, 0] - a[:, 0, 0]))
    assert (area > 0).all()
    assert abs(area.sum() - 2 * 260 * 420) < 2.0
    L = inst["pts"][inst["edges"]["front.side@L"]]
    assert np.allclose(L[:, 0], -260.0, atol=1e-6)


def test_seam_pairs_sides_and_self_seam():
    inst = {"a.s@R": (0, [0]), "a.s@L": (0, [1]), "b.s@R": (0, [2]), "b.s@L": (0, [3]),
            "c.cb@R": (0, [4]), "c.cb@L": (0, [5])}
    pairs, warn = sp.seam_pairs([{"a": "a.s", "b": "b.s"}, {"a": "c.cb", "b": "c.cb"},
                                 {"a": "x.y", "b": "z.w"}], inst)
    keys = {(a, b) for a, b, _r, _k in pairs}
    assert ("a.s@R", "b.s@R") in keys and ("a.s@L", "b.s@L") in keys
    assert ("c.cb@R", "c.cb@L") in keys
    assert any("x.y" in w for w in warn)


# --- tam girdi (gerçek manken) -------------------------------------------------------
@pytest.fixture(scope="module")
def female_body():
    if not _FEMALE.exists():
        pytest.skip("taban manken GLB'si yok")
    return sp.load_mannequin(str(_FEMALE), 1.65)


def test_build_sew_input_tube(female_body):
    v, f = female_body
    from common.fabrics import blender_params
    d = sp.build_sew_input(_tube_doc(), v, f, blender_params("cotton"), 60)
    V, R, F = np.array(d["vertices"]), np.array(d["rest"]), np.array(d["faces"])
    assert V.shape == R.shape and len(d["uv"]) == len(V)
    assert F.max() < len(V)
    uv = np.array(d["uv"])
    assert uv.min() >= -1e-9 and uv.max() <= 1.0 + 1e-9
    # Yan dikişler: iki taraf (R, L), eşit sayıda yay; yay uçları ayrı parçalarda.
    assert {s["a"] for s in d["seams"]} == {"front.side@R", "front.side@L"}
    n = len(d["springs"])
    assert n == sum(s["pairs"] for s in d["seams"]) and n > 60
    pr = {(p["name"], p["side"]): p for p in d["pieces"]}
    fs, bs = pr["front", "F"], pr["back", "F"]
    for a, b in d["springs"]:
        assert fs["start"] <= a < fs["start"] + fs["count"]
        assert bs["start"] <= b < bs["start"] + bs["count"]
    # Dinlenme şekli düz (z=0) ve kalıp ölçüsünde (mm→m): ön panel 0.52 x 0.42 m.
    fr = R[fs["start"]:fs["start"] + fs["count"]]
    assert np.allclose(fr[:, 2], 0)
    ext = fr.max(axis=0) - fr.min(axis=0)
    assert abs(ext[0] - 0.52) < 1e-3 and abs(ext[1] - 0.42) < 1e-3
    # Yerleşim: önde (+z) / arkada (−z), mankenin içinde değil, makul boyutta.
    fz = V[fs["start"]:fs["start"] + fs["count"], 2]
    bz = V[bs["start"]:bs["start"] + bs["count"], 2]
    assert np.median(fz) > 0 > np.median(bz)
    assert V[:, 1].max() < v[:, 1].max() and V[:, 1].min() > 0.5
    prof = sp.body_radial_profile(v, sp.analyze_body(v, f), faces=f)
    PP = V.copy()
    n_in, _ = sp.push_out_radial(PP, prof, 0.0)
    assert n_in == 0  # başlangıçta gövde profilinin içinde vertex yok


def test_build_sew_input_no_seams_raises(female_body):
    v, f = female_body
    doc = _tube_doc()
    doc["seams"] = []
    with pytest.raises(sp.SewPrepError, match="3D dikiş bilgisi yok"):
        sp.build_sew_input(doc, v, f, {}, 60)


def test_analyze_body_levels(female_body):
    v, f = female_body
    b = sp.analyze_body(v, f)
    lv = b["levels"]
    assert 0 < lv["crotch"] < lv["hip"] < lv["waist"] < lv["chest"] < lv["armpit"] < lv["neck"] < 1.65
    assert b["arm"] is not None and b["arm"]["x_max"] > 0.6  # T/A-pozu: kollar yana açık
    assert lv["armpit"] < b["shoulder_y"] < lv["neck"]


def test_prepare_mannequin_morph_and_scale():
    if not _FEMALE.exists():
        pytest.skip("taban manken GLB'si yok")
    body = {"gender": "female", "height_cm": 160, "chest_cm": 90, "waist_cm": 72, "hip_cm": 98}
    v, f, info = sp.prepare_mannequin(str(_FEMALE), "female-a", body)
    assert info["fit"] == "morphed"
    assert abs(v[:, 1].max() - 1.60) < 0.01 and abs(v[:, 1].min()) < 1e-9
    v2, _f2, info2 = sp.prepare_mannequin(str(_FEMALE), "female-a", None)
    assert info2["fit"] == "scaled" and abs(v2[:, 1].max() - 1.65) < 1e-6


# --- worker task ---------------------------------------------------------------------
def _store(monkeypatch, worker):
    from common.jobs import JobStore
    fake = fakeredis.FakeStrictRedis(decode_responses=True)
    store = JobStore(fake)
    monkeypatch.setattr(worker, "JobStore", lambda: store)
    return store, fake


def test_sew3d_task_registered():
    from clothsim_worker import worker
    assert worker.sew3d.name == "clothsim.sew3d"
    assert worker._sew_script_path().name == "blender_sew.py"


def test_sew3d_blender_missing(monkeypatch):
    from clothsim_worker import worker
    store, fake = _store(monkeypatch, worker)
    monkeypatch.setattr(worker.shutil, "which", lambda name: None)
    monkeypatch.setattr(worker, "BLENDER_BIN", "blender")
    r = worker.sew3d(job_id="j1", project_id="p1", pattern_id="a" * 32, mannequin_id="female-a")
    assert r == {"error": "blender-missing"}
    assert fake.hgetall("job:j1")["state"] == "FAILURE"


def test_sew3d_unknown_pattern_fails_turkish(monkeypatch, tmp_path):
    from clothsim_worker import worker
    store, fake = _store(monkeypatch, worker)
    monkeypatch.setattr(worker, "_find_blender", lambda: "/bin/true")
    monkeypatch.setenv("PATTERNS_DIR", str(tmp_path))
    with pytest.raises(RuntimeError, match="Kalıp bulunamadı"):
        worker.sew3d(job_id="j2", project_id="p1", pattern_id="c" * 32, mannequin_id="female-a")
    h = fake.hgetall("job:j2")
    assert h["state"] == "FAILURE" and "Kalıp bulunamadı" in h["error"]


def test_run_blender_sew_reports_progress(monkeypatch, tmp_path):
    from clothsim_worker import worker
    store, fake = _store(monkeypatch, worker)
    store.create("j3", {"kind": "sew3d"})
    script = tmp_path / "fake.py"
    script.write_text("print('[sew] kare 10/20', flush=True)\nprint('bitti')\n")
    rc, tail = worker._run_blender_sew([sys.executable, str(script)], "j3", store)
    assert rc == 0 and "bitti" in tail
    h = fake.hgetall("job:j3")
    assert h.get("stage") == "sim" and int(h.get("percent", h.get("progress", 0))) == 52


# --- gerçek Blender (yerel kurulum varsa) ---------------------------------------------
@pytest.mark.skipif(_blender_bin() is None, reason="Blender kurulu değil")
def test_real_blender_sews_tube_on_mannequin(tmp_path, female_body):
    """Tüp (ön+arka katlı panel, iki yan dikiş) female-a üzerinde gerçekten dikilir:
    dikiş aralığı kapanır, GLB yalnız kıyafeti içerir, uzama makul."""
    import subprocess

    import trimesh
    from common.fabrics import blender_params, get_fabric
    v, f = female_body
    d = sp.build_sew_input(_tube_doc(), v, f, blender_params("cotton"), 50, h_mm=18.0)
    d["pbr"] = get_fabric("cotton")["pbr"]
    d["sim"] = {"self_collision": False}
    inp = tmp_path / "in.json"
    inp.write_text(json.dumps(d))
    out = tmp_path / "tube.glb"
    rep = tmp_path / "rep.json"
    script = _SRC / "clothsim_worker" / "blender_sew.py"
    proc = subprocess.run([_blender_bin(), "-b", "-P", str(script), "--", str(inp), str(out),
                           "--report", str(rep)], capture_output=True, text=True, timeout=600)
    assert proc.returncode == 0, proc.stdout[-1500:] + proc.stderr[-1500:]
    r = json.loads(rep.read_text())
    assert r["seam_gap_mm"]["max"] < 15.0, r["seam_gap_mm"]
    assert r["edge_stretch"]["median"] < 1.2
    assert r["loose_edges_removed"] == len(d["springs"])
    g = trimesh.load(str(out), force="mesh")
    assert len(g.faces) == len(d["faces"])
    ext = g.bounds[1] - g.bounds[0]
    assert ext[1] < 0.6 and ext[0] < 0.7  # patlama yok (tüp ~0.42 m boy)
    assert g.bounds[0][1] > 0.4  # mankenden düşmedi
