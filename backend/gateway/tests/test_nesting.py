"""Kumaş yerleşimi (nesting) testleri — common.nesting + POST /patterns/{id}/nest.

Hermetik: PATTERNS_DIR tmp_path'e yönlendirilir; pieces.json sentetik fixture'dır
(tişört benzeri katlı ön/arka + sağ/sol kol çifti + dikdörtgen bantlar) — F1'e
bağımlı değil. Çakışma kontrolü raster'dan BAĞIMSIZ kesin geometriyle yapılır
(poligon kenar kesişimi + içerme + köşe-kenar mesafesi; aşağıdaki `_exact_dist`).
"""
from __future__ import annotations

import json
import math
import xml.etree.ElementTree as ET
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient

from common.nesting import (NestingError, expand_copies, nest_pieces,
                            polygon_area, polygon_distance, unfold_on_fold)

AUTH = {"Authorization": "Bearer test-token-bootstrap"}


# --- fixture veri ------------------------------------------------------------------
def _offset(poly, d):
    """Konveks olmayan poligonlar için de yeterli kaba dış öteleme (köşe açıortayı)."""
    p = np.asarray(poly, float)
    n = len(p)
    out = []
    for i in range(n):
        a, b, c = p[i - 1], p[i], p[(i + 1) % n]
        e1 = (b - a) / np.linalg.norm(b - a)
        e2 = (c - b) / np.linalg.norm(c - b)
        n1 = np.array([e1[1], -e1[0]])
        n2 = np.array([e2[1], -e2[0]])
        m = n1 + n2
        m = m / np.linalg.norm(m)
        out.append(b + m * d / max(0.3, float(np.dot(m, n1))))
    return [[float(x), float(y)] for x, y in out]


def _piece(name, label, seam, qty, mirror, grain=90, edges=None, fold=None, sa=10.0):
    d = {"name": name, "label_tr": label, "quantity": qty, "mirror": mirror,
         "seam_line": seam, "cut_line": _offset(seam, sa), "grain_deg": grain,
         "edges": edges or []}
    if mirror:
        d["fold_edge"] = fold
    return d


def tshirt_doc(sa=10.0):
    # Ön/arka yarım: x=0 orta ön/arka katlama doğrusu (CCW).
    front = [[0, 0], [260, 0], [260, 430], [300, 470], [250, 560], [180, 640],
             [90, 650], [60, 600], [0, 590]]
    back = [[0, 0], [260, 0], [260, 430], [300, 470], [250, 560], [180, 640],
            [90, 660], [0, 660]]
    sleeve = [[0, 0], [400, 0], [380, 180], [200, 240], [20, 180]]
    band = [[0, 0], [500, 0], [500, 40], [0, 40]]
    pocket = [[0, 0], [150, 0], [150, 170], [75, 190], [0, 170]]
    pieces = [
        # Katlama kenarına pay verilmemesi gerçek kalıpta normaldir; burada offset
        # katlama kenarını da aşıyor → unfold kırpma yolunu da test etmiş oluruz.
        _piece("front", "Ön", front, 1, True,
               edges=[{"id": "front.cf", "from": 8, "to": 0}], fold="front.cf", sa=sa),
        _piece("back", "Arka", back, 1, True,
               edges=[{"id": "back.cb", "from": 7, "to": 0}], fold="back.cb", sa=sa),
        _piece("sleeve", "Kol", sleeve, 1, True, sa=sa),          # sağ/sol çift
        _piece("neckband", "Yaka bandı", band, 1, False, grain=0, sa=sa),
        _piece("pocket", "Cep", pocket, 2, False, grain=90, sa=sa),
    ]
    return {"pattern_id": "tshirt-test", "design": "tshirt", "units": "mm", "sa_mm": sa,
            "measurements": {}, "pieces": pieces, "seams": []}


def _exact_dist(p, q) -> float:
    """Testin KENDİ kesin mesafesi (common.nesting'ten bağımsız, döngüsel)."""
    p = [tuple(map(float, v)) for v in p]
    q = [tuple(map(float, v)) for v in q]

    def seg_dist(a, b, c, d):
        def cross(o, u, v):
            return (u[0] - o[0]) * (v[1] - o[1]) - (u[1] - o[1]) * (v[0] - o[0])
        d1, d2 = cross(a, b, c), cross(a, b, d)
        d3, d4 = cross(c, d, a), cross(c, d, b)
        if ((d1 > 0) != (d2 > 0)) and ((d3 > 0) != (d4 > 0)) and d1 * d2 < 0 and d3 * d4 < 0:
            return 0.0

        def pt_seg(pt, s0, s1):
            vx, vy = s1[0] - s0[0], s1[1] - s0[1]
            L = vx * vx + vy * vy
            t = 0.0 if L == 0 else max(0.0, min(1.0, ((pt[0] - s0[0]) * vx + (pt[1] - s0[1]) * vy) / L))
            return math.hypot(pt[0] - s0[0] - t * vx, pt[1] - s0[1] - t * vy)
        return min(pt_seg(a, c, d), pt_seg(b, c, d), pt_seg(c, a, b), pt_seg(d, a, b))

    def inside(pt, poly):
        x, y = pt
        c = False
        for i in range(len(poly)):
            x1, y1 = poly[i]
            x2, y2 = poly[(i + 1) % len(poly)]
            if (y1 > y) != (y2 > y) and x < x1 + (y - y1) * (x2 - x1) / (y2 - y1):
                c = not c
        return c

    if inside(p[0], q) or inside(q[0], p):
        return 0.0
    best = math.inf
    for i in range(len(p)):
        for j in range(len(q)):
            best = min(best, seg_dist(p[i], p[(i + 1) % len(p)], q[j], q[(j + 1) % len(q)]))
    return best


def _assert_valid_layout(res, width_cm, gap_mm):
    pl = res["placements"]
    width = width_cm * 10.0
    for p in pl:
        poly = np.asarray(p["polygon_mm"])
        assert poly[:, 1].min() >= -1e-6, p
        assert poly[:, 1].max() <= width + 1e-6, p
        assert poly[:, 0].min() >= -1e-6, p
        assert poly[:, 0].max() <= res["used_length_mm"] + 1e-6
    for i in range(len(pl)):
        for j in range(i + 1, len(pl)):
            d = _exact_dist(pl[i]["polygon_mm"], pl[j]["polygon_mm"])
            assert d >= gap_mm - 1e-3, (pl[i]["piece"], pl[i]["copy"], pl[j]["piece"], pl[j]["copy"], d)


# --- birim testler -------------------------------------------------------------------
def test_copy_rules():
    copies, warns = expand_copies(tshirt_doc())
    assert warns == []
    by = {}
    for c in copies:
        by.setdefault(c["piece"], []).append(c)
    # Katlı parçalar: tek tam kopya, açılmış.
    assert len(by["front"]) == 1 and by["front"][0]["unfolded"]
    assert len(by["back"]) == 1 and by["back"][0]["unfolded"]
    # Katsız mirror → sağ/sol çift; ikincisi ters.
    assert [c["flipped"] for c in by["sleeve"]] == [False, True]
    assert by["sleeve"][1]["mirror_twin"]
    # Normal parça quantity kadar.
    assert len(by["pocket"]) == 2 and not any(c["flipped"] for c in by["pocket"])
    assert len(by["neckband"]) == 1


def test_unfold_is_symmetric_full_piece():
    doc = tshirt_doc(sa=0.0)
    fr = doc["pieces"][0]
    seam = np.asarray(fr["seam_line"], float)
    full = unfold_on_fold(seam, seam, seam[8], seam[0])
    assert full is not None
    # Yarım alanın tam 2 katı; x ekseninde -300..300 simetrik.
    assert abs(polygon_area(full) - 2 * polygon_area(seam)) < 1e-6
    assert abs(full[:, 0].min() + 300) < 1e-9 and abs(full[:, 0].max() - 300) < 1e-9


def test_unfold_clips_allowance_beyond_fold():
    # Paylı kesim katlama doğrusunu aşar → kırpılıp birleşmeli, alan ~ 2×(x≥0 kısmı).
    doc = tshirt_doc(sa=10.0)
    fr = doc["pieces"][0]
    seam = np.asarray(fr["seam_line"], float)
    cut = np.asarray(fr["cut_line"], float)
    assert cut[:, 0].min() < 0          # pay katlama doğrusunu gerçekten aşıyor
    full = unfold_on_fold(cut, seam, seam[8], seam[0])
    assert full is not None
    assert abs(full[:, 0].min() + full[:, 0].max()) < 1e-6   # simetrik


def test_unfold_with_extra_points_on_fold_line():
    # FreeSewing katlama kenarına ara noktalar (çentik vb.) koyar; bunlar kenarı
    # bölse de parça açılabilmeli (teagan cf/cb gerçek hatası, 2026-10-17).
    half = np.array([[0, 0], [200, 0], [200, 500], [0, 500],
                     [0, 400], [0, 250], [0, 100]], float)
    full = unfold_on_fold(half, half, half[3], half[0])
    assert full is not None
    assert abs(polygon_area(full) - 2 * polygon_area(half)) < 1e-6
    assert abs(full[:, 0].min() + 200) < 1e-9


def test_polygon_distance_basic():
    a = [[0, 0], [10, 0], [10, 10], [0, 10]]
    b = [[15, 0], [25, 0], [25, 10], [15, 10]]
    assert abs(polygon_distance(a, b) - 5.0) < 1e-9
    c = [[5, 5], [20, 5], [20, 20], [5, 20]]
    assert polygon_distance(a, c) == 0.0
    inner = [[2, 2], [3, 2], [3, 3], [2, 3]]
    assert polygon_distance(a, inner) == 0.0


@pytest.mark.parametrize("width_cm,gap", [(150, 5), (110, 5), (140, 0), (150, 12)])
def test_nest_no_overlap_and_inside_fabric(width_cm, gap):
    res = nest_pieces(tshirt_doc(), fabric_width_cm=width_cm, gap_mm=gap)
    assert res["verified"] is True
    assert len(res["placements"]) == 7   # ön, arka, 2 kol, yaka, 2 cep
    _assert_valid_layout(res, width_cm, gap)
    # Verim tanımı: parça alanı / (en × kullanılan boy).
    area = sum(abs(polygon_area(np.asarray(p["polygon_mm"]))) for p in res["placements"])
    exp = 100 * area / (width_cm * 10 * res["used_length_mm"])
    assert abs(res["efficiency_pct"] - exp) < 0.2
    assert 20 < res["efficiency_pct"] <= 100


def test_grain_preserved_only_0_180():
    res = nest_pieces(tshirt_doc(), fabric_width_cm=150, gap_mm=5, allow_flip=False)
    for p in res["placements"]:
        g = p["grain_deg"]
        # Dönüşüm sonrası düz boy yönü x eksenine paralel olmalı.
        v = np.array([math.cos(math.radians(g)), math.sin(math.radians(g))])
        if p["flipped"]:
            v[1] = -v[1]
        r = math.radians(p["rot_deg"])
        w = np.array([v[0] * math.cos(r) - v[1] * math.sin(r), v[0] * math.sin(r) + v[1] * math.cos(r)])
        assert abs(w[1]) < 1e-9 and abs(abs(w[0]) - 1) < 1e-9
    # allow_flip=False → yalnız zorunlu ikiz ters.
    flipped = [(p["piece"], p["copy"]) for p in res["placements"] if p["flipped"]]
    assert flipped == [("sleeve", 2)]


def test_polygon_matches_transform():
    from common.nesting import transform
    doc = tshirt_doc()
    copies, _ = expand_copies(doc)
    poly_by = {(c["piece"], c["copy"]): c["poly"] for c in copies}
    res = nest_pieces(doc, fabric_width_cm=150, gap_mm=5)
    for p in res["placements"]:
        q = transform(poly_by[(p["piece"], p["copy"])], p["flipped"], p["rot_deg"], p["x_mm"], p["y_mm"])
        assert np.allclose(q, np.asarray(p["polygon_mm"]), atol=0.01)


def test_too_wide_raises_turkish():
    with pytest.raises(NestingError) as ei:
        nest_pieces(tshirt_doc(), fabric_width_cm=50, gap_mm=5)
    assert "sığmıyor" in str(ei.value) and "Arka" in str(ei.value)


def test_many_rectangles():
    rects = [{"name": f"r{i}", "label_tr": f"Parça {i}", "quantity": 1, "mirror": False,
              "seam_line": [[0, 0], [w, 0], [w, h], [0, h]], "cut_line": [[0, 0], [w, 0], [w, h], [0, h]],
              "grain_deg": 0, "edges": []}
             for i, (w, h) in enumerate([(300, 200), (250, 400), (120, 120), (600, 150),
                                         (90, 300), (400, 400), (200, 100), (50, 50)])]
    res = nest_pieces({"pieces": rects}, fabric_width_cm=90, gap_mm=3, grid_mm=3)
    _assert_valid_layout(res, 90, 3)
    assert res["efficiency_pct"] > 55


# --- route -----------------------------------------------------------------------------
@pytest.fixture
def ctx(tmp_path, monkeypatch):
    pdir = tmp_path / "patterns"
    monkeypatch.setenv("APP_TOKEN", "test-token-bootstrap")
    monkeypatch.setenv("PATTERNS_DIR", str(pdir))
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{(tmp_path / 'n.db').as_posix()}")
    from common.config import get_settings
    get_settings.cache_clear()
    from gateway import db
    db.reset_engine()
    db.init_db()
    from gateway.main import app
    d = pdir / "tshirt-test"
    d.mkdir(parents=True)
    (d / "pieces.json").write_text(json.dumps(tshirt_doc(), ensure_ascii=False), encoding="utf-8")
    (d / "meta.json").write_text(json.dumps({"name": "Test Tişört"}), encoding="utf-8")
    yield TestClient(app), d
    db.reset_engine()
    get_settings.cache_clear()


def test_route_requires_auth(ctx):
    client, _ = ctx
    assert client.post("/patterns/tshirt-test/nest", json={}).status_code == 401


def test_route_nest_writes_svg_json(ctx):
    client, d = ctx
    r = client.post("/patterns/tshirt-test/nest",
                    json={"fabric_width_cm": 140, "gap_mm": 5, "allow_flip": True}, headers=AUTH)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["svg_url"] == "/patterns/tshirt-test/nest.svg"
    assert body["used_length_cm"] > 0 and body["efficiency_pct"] > 0
    assert isinstance(body["warnings"], list)
    _assert_valid_layout(body, 140, 5)
    for p in body["placements"]:
        assert {"piece", "copy", "x_mm", "y_mm", "rot_deg", "flipped"} <= p.keys()
    # nest.json diskte, aynı sonuç.
    saved = json.loads((d / "nest.json").read_text(encoding="utf-8"))
    assert saved["used_length_cm"] == body["used_length_cm"]
    # SVG: geçerli XML, 1:1 mm, her kopya için bir path + Türkçe etiketler.
    g = client.get("/patterns/tshirt-test/nest.svg")   # public
    assert g.status_code == 200 and g.headers["content-type"].startswith("image/svg+xml")
    root = ET.fromstring(g.content)
    assert root.get("width").endswith("mm")
    ns = "{http://www.w3.org/2000/svg}"
    paths = root.findall(f".//{ns}path")
    assert len(paths) == len(body["placements"])
    texts = " ".join(t.text or "" for t in root.iter(f"{ns}text"))
    assert "Ön 1/1" in texts and "Kol 2/2 (ters)" in texts and "Cep 2/2" in texts


def test_route_too_wide_422(ctx):
    client, _ = ctx
    r = client.post("/patterns/tshirt-test/nest", json={"fabric_width_cm": 40}, headers=AUTH)
    assert r.status_code == 422
    assert "sığmıyor" in r.json()["detail"]


def test_route_missing_and_bad_id(ctx):
    client, _ = ctx
    assert client.post("/patterns/yok/nest", json={}, headers=AUTH).status_code == 404
    assert client.post("/patterns/..%2Fx/nest", json={}, headers=AUTH).status_code == 404
    assert client.get("/patterns/yok/nest.svg").status_code == 404
