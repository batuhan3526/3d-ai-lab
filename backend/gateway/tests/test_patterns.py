"""FreeSewing kalıp testleri — F1 (/patterns/*).

Node çağrısı GERÇEK (monkeypatch yok): backend/services/freesewing/draft.mjs +
@freesewing/* v4.10.2. Node ya da node_modules yoksa modül atlanır.

Hermetik: PROJECTS_DIR=tmp → patterns_dir() = tmp/patterns (gerçek data/'ya
yazmaz), env monkeypatch + get_settings.cache_clear (test_sewing.py deseni).
Geometri doğrulamaları: poligonlar kapalı + CCW + alan>0, kesim çizgisi dikiş
çizgisini kapsar, teagan yan dikiş ön/arka farkı <%5, kol takma farkı <%10,
kenar zinciri parça çevresini tam örter, SVG 1:1 mm + 10 cm kalibrasyon karesi.
"""
from __future__ import annotations

import json
import math
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from common import patterns as pat

AUTH = {"Authorization": "Bearer test-token-bootstrap"}
BODY_F = {"gender": "female", "height_cm": 165, "chest_cm": 90, "waist_cm": 72, "hip_cm": 98}
BODY_M = {"gender": "male", "height_cm": 180, "chest_cm": 102, "waist_cm": 86, "hip_cm": 102}

pytestmark = pytest.mark.skipif(
    not (pat.FREESEWING_DIR / "node_modules" / "@freesewing" / "core").is_dir()
    or not Path(pat.node_bin()).exists(),
    reason="FreeSewing node servisi kurulu değil",
)


@pytest.fixture
def ctx(tmp_path, monkeypatch):
    db_path = str(tmp_path / "patterns.db").replace("\\", "/")
    projects_dir = tmp_path / "projects"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    monkeypatch.setenv("APP_TOKEN", "test-token-bootstrap")
    monkeypatch.setenv("PROJECTS_DIR", str(projects_dir).replace("\\", "/"))
    monkeypatch.delenv("PATTERNS_DIR", raising=False)
    from common.config import get_settings
    get_settings.cache_clear()
    from gateway import db
    db.reset_engine()
    db.init_db()
    from gateway.main import app
    yield TestClient(app), tmp_path / "patterns"
    db.reset_engine()
    get_settings.cache_clear()


def _area(poly):
    return pat._area(poly)


def _draft(client, design, body=BODY_F, **extra):
    r = client.post("/patterns/draft", json={"design": design, "body": body, **extra}, headers=AUTH)
    assert r.status_code == 200, r.text
    return r.json()


# --- auth / katalog ----------------------------------------------------------
def test_requires_auth(ctx):
    client, _ = ctx
    assert client.get("/patterns/designs").status_code == 401
    assert client.post("/patterns/draft", json={"design": "teagan"}).status_code == 401


def test_designs_catalog(ctx):
    client, _ = ctx
    r = client.get("/patterns/designs", headers=AUTH)
    assert r.status_code == 200
    ds = r.json()
    assert 8 <= len(ds) <= 12
    by = {d["id"]: d for d in ds}
    assert by["teagan"]["sew3d"] is True and by["teagan"]["label_tr"] == "Tişört"
    assert by["penelope"]["sew3d"] is True and by["sandy"]["sew3d"] is True
    assert by["simon"]["sew3d"] is False
    for d in ds:
        assert d["label_tr"] and d["category_tr"] and d["measurements"]
        assert d["estimable"] is True  # 5 basit alandan tüm ölçüler tahmin edilebilir
        for o in d["options"]:
            assert o["label_tr"] and o["default"] in {c["id"] for c in o["choices"]}


# --- ölçü tahmini ------------------------------------------------------------
def test_estimate_measurements(ctx):
    client, _ = ctx
    r = client.post("/patterns/measurements/estimate", json=BODY_F, headers=AUTH)
    assert r.status_code == 200
    m = r.json()["measurements"]
    assert m["chest"] == 900 and m["waist"] == 720 and m["seat"] == 980
    assert 720 < m["hips"] < 980  # üst kalça bel ile basen arasında
    assert 300 < m["neck"] < 400 and 200 < m["biceps"] < 350
    assert m["shoulderSlope"] == 13
    assert 900 < m["waistToFloor"] < 1150 and 650 < m["inseam"] < 850
    # Tüm tasarımların ölçüleri karşılanıyor.
    for d in pat.CATALOG:
        assert set(pat._DESIGN_MEASUREMENTS[d["id"]]) <= set(m), d["id"]


def test_estimate_base_reproduces_freesewing_model(ctx):
    """FreeSewing ortalama kadın modeli girilirse tablo değerleri aynen çıkar."""
    from common.body_measurements import estimate_measurements

    m = estimate_measurements({"gender": "female", "height_cm": 168, "chest_cm": 92.5,
                               "waist_cm": 75, "hip_cm": 101})
    assert m["neck"] == 340 and m["biceps"] == 270 and m["hpsToWaistBack"] == 395


@pytest.mark.parametrize("bad,needle", [
    ({**BODY_F, "gender": "x"}, "Cinsiyet"),
    ({**BODY_F, "height_cm": 20}, "Boy"),
    ({**BODY_F, "chest_cm": 500}, "Göğüs"),
])
def test_estimate_validation_turkish(ctx, bad, needle):
    client, _ = ctx
    r = client.post("/patterns/measurements/estimate", json=bad, headers=AUTH)
    assert r.status_code == 422
    assert needle in r.json()["detail"]


# --- draft -------------------------------------------------------------------
def test_draft_unknown_design_turkish(ctx):
    client, _ = ctx
    r = client.post("/patterns/draft", json={"design": "yokboyle", "body": BODY_F}, headers=AUTH)
    assert r.status_code == 422 and "tasarım" in r.json()["detail"]


def test_draft_bad_option_turkish(ctx):
    client, _ = ctx
    r = client.post("/patterns/draft", json={"design": "teagan", "body": BODY_F,
                                             "options": {"fit": "devasa"}}, headers=AUTH)
    assert r.status_code == 422 and "geçersiz" in r.json()["detail"]


def test_draft_missing_measurements_turkish(ctx):
    client, _ = ctx
    r = client.post("/patterns/draft", json={"design": "teagan"}, headers=AUTH)
    assert r.status_code == 422 and "Ölçü" in r.json()["detail"]
    r = client.post("/patterns/draft", json={"design": "teagan", "measurements": {"chest": 900}},
                    headers=AUTH)
    assert r.status_code == 422 and "eksik ölçü" in r.json()["detail"]


def _check_pieces(doc: dict) -> None:
    assert doc["units"] == "mm" and doc["coords"] == "y_up" and doc["sa_mm"] == 10
    assert doc["pieces"]
    for p in doc["pieces"]:
        for key in ("seam_line", "cut_line"):
            poly = p[key]
            assert len(poly) >= 3
            assert poly[0] != poly[-1]  # ilk nokta tekrarlanmaz
            assert _area(poly) > 0, f"{p['name']}.{key} CCW/alan>0 değil"
        if p["cut_method"] == "none":  # FreeSewing bilerek pay vermemiş (biye şeridi)
            assert _area(p["cut_line"]) == pytest.approx(_area(p["seam_line"]))
        else:
            assert _area(p["cut_line"]) > _area(p["seam_line"])  # pay dışarıda
        assert p["cut_method"] != "offset", f"{p['name']}: FreeSewing payı kullanılamadı"
        n = len(p["seam_line"])
        for e in p["edges"]:
            assert 0 <= e["from"] < n and 0 <= e["to"] < n
        assert isinstance(p["mirror"], bool) and p["quantity"] >= 1
        if p["mirror"]:
            assert p["fold_edge"] in {e["id"] for e in p["edges"]}


def test_draft_teagan_files_and_geometry(ctx):
    client, pdir = ctx
    res = _draft(client, "teagan")
    pid = res["pattern_id"]
    assert res["design"] == "teagan"
    assert {p["name"] for p in res["pieces"]} == {"front", "back", "sleeve"}
    for name in ("pattern.svg", "pattern.pdf", "pieces.json", "meta.json", "freesewing.svg"):
        assert (pdir / pid / name).is_file(), name
    # Dosya uçları public (token'sız).
    svg_r = client.get(res["svg_url"])
    assert svg_r.status_code == 200 and svg_r.headers["content-type"].startswith("image/svg+xml")
    pdf_r = client.get(res["pdf_url"])
    assert pdf_r.status_code == 200 and pdf_r.content[:5] == b"%PDF-"
    doc = client.get(res["pieces_url"]).json()

    # SVG: parse edilebilir, 1:1 mm, 100 mm kalibrasyon karesi.
    root = ET.fromstring(svg_r.content)
    assert root.attrib["width"].endswith("mm")
    w_mm = float(root.attrib["width"][:-2])
    vb = [float(v) for v in root.attrib["viewBox"].split()]
    assert math.isclose(vb[2], w_mm, rel_tol=1e-3)  # 1 kullanıcı birimi = 1 mm
    ns = "{http://www.w3.org/2000/svg}"
    squares = [r for r in root.iter(f"{ns}rect")
               if r.attrib.get("width") == "100" and r.attrib.get("height") == "100"]
    assert squares, "10 cm kalibrasyon karesi yok"

    _check_pieces(doc)
    by = {p["name"]: p for p in doc["pieces"]}
    assert by["front"]["mirror"] and by["front"]["fold_edge"] == "front.cf"
    assert by["back"]["mirror"] and by["back"]["fold_edge"] == "back.cb"
    assert not by["sleeve"]["mirror"] and by["sleeve"]["quantity"] == 2

    # Kenar zinciri her parçanın çevresini eksiksiz örtmeli.
    for p in doc["pieces"]:
        total = sum(e["length_mm"] for e in p["edges"])
        sl = p["seam_line"]
        perim = sum(math.dist(sl[k], sl[(k + 1) % len(sl)]) for k in range(len(sl)))
        assert math.isclose(total, perim, rel_tol=1e-3), p["name"]

    edges = {e["id"]: e for p in doc["pieces"] for e in p["edges"]}
    seams = {(s["a"], s["b"]): s for s in doc["seams"]}
    assert ("front.side", "back.side") in seams
    assert ("front.shoulder", "back.shoulder") in seams
    assert ("front.armhole", "sleeve.cap_front") in seams
    assert ("back.armhole", "sleeve.cap_back") in seams
    assert ("sleeve.underarm_front", "sleeve.underarm_back") in seams

    def L(eid):
        return edges[eid]["length_mm"]

    assert abs(L("front.side") - L("back.side")) / L("back.side") < 0.05
    assert abs(L("front.shoulder") - L("back.shoulder")) / L("back.shoulder") < 0.05
    assert abs(L("sleeve.cap_front") - L("front.armhole")) / L("front.armhole") < 0.10
    assert abs(L("sleeve.cap_back") - L("back.armhole")) / L("back.armhole") < 0.10
    assert abs(L("sleeve.underarm_front") - L("sleeve.underarm_back")) < 1.0
    # Gerçekçi boyutlar: göğüs 90 cm, normal bolluk → ön+arka yarım genişlik ~ (900*1.12)/2
    front_w = max(q[0] for q in by["front"]["seam_line"]) - min(q[0] for q in by["front"]["seam_line"])
    back_w = max(q[0] for q in by["back"]["seam_line"]) - min(q[0] for q in by["back"]["seam_line"])
    assert 0.9 * 504 < (front_w + back_w) < 1.25 * 504


def test_teagan_seam_directions_geometric(ctx):
    """reverse bayrağı doğru mu: yan dikişte ön/arka etek uçları aynı yükseklikte."""
    client, _ = ctx
    doc = client.get(_draft(client, "teagan")["pieces_url"]).json()
    by = {p["name"]: p for p in doc["pieces"]}
    edges = {e["id"]: (p, e) for p in doc["pieces"] for e in p["edges"]}

    def ends(eid):
        p, e = edges[eid]
        return p["seam_line"][e["from"]], p["seam_line"][e["to"]]

    for s in doc["seams"]:
        (a0, a1), (b0, b1) = ends(s["a"]), ends(s["b"])
        if s["reverse"]:
            b0, b1 = b1, b0
        if s["a"] == "front.side":
            # a0↔b0 aynı uç (ikisi de etek ya da ikisi de koltuk altı) → y'leri yakın
            assert abs(a0[1] - b0[1]) < 20 and abs(a1[1] - b1[1]) < 20
    assert by["front"]["edges"] and by["back"]["edges"]


def test_draft_skirts_seams(ctx):
    client, _ = ctx
    pen = client.get(_draft(client, "penelope")["pieces_url"]).json()
    _check_pieces(pen)
    pby = {p["name"]: p for p in pen["pieces"]}
    assert pby["front"]["mirror"] and pby["front"]["fold_edge"] == "front.cf"
    assert pby["back"]["quantity"] == 2
    kinds = [s.get("kind") for s in pen["seams"]]
    assert kinds.count("dart") >= 2
    pairs = {(s["a"], s["b"]) for s in pen["seams"]}
    assert ("front.side", "back.side") in pairs and ("back.cb", "back.cb") in pairs
    e = {x["id"]: x for p in pen["pieces"] for x in p["edges"]}
    assert abs(e["front.side"]["length_mm"] - e["back.side"]["length_mm"]) / e["back.side"]["length_mm"] < 0.05
    for s in pen["seams"]:
        if s.get("kind") == "dart":
            assert abs(e[s["a"]]["length_mm"] - e[s["b"]]["length_mm"]) < 2.0

    sandy = client.get(_draft(client, "sandy")["pieces_url"]).json()
    _check_pieces(sandy)
    sk = {p["name"]: p for p in sandy["pieces"]}["skirt"]
    assert sk["mirror"] and sk["fold_edge"] == "skirt.cf"
    assert {(s["a"], s["b"]) for s in sandy["seams"]} == {("skirt.cb", "skirt.cb")}


def test_draft_male_and_options(ctx):
    client, _ = ctx
    a = client.get(_draft(client, "teagan", body=BODY_M, options={"fit": "dar"})["pieces_url"]).json()
    b = client.get(_draft(client, "teagan", body=BODY_M, options={"fit": "bol", "sleeve": "uzun"})["pieces_url"]).json()
    fa = {p["name"]: p for p in a["pieces"]}
    fb = {p["name"]: p for p in b["pieces"]}
    assert fb["front"]["area_cm2"] > fa["front"]["area_cm2"]  # bol > dar
    assert fb["sleeve"]["area_cm2"] > 1.5 * fa["sleeve"]["area_cm2"]  # uzun kol


@pytest.mark.parametrize("design", ["aaron", "sven", "hugo", "simon", "bella", "titan", "lily", "waralee"])
def test_draft_other_designs(ctx, design):
    client, _ = ctx
    res = _draft(client, design, body=BODY_F)
    doc = client.get(res["pieces_url"]).json()
    _check_pieces(doc)
    assert doc["seams"] == []  # sew3d=false tasarımlar


def test_list_get_delete(ctx):
    client, pdir = ctx
    res = _draft(client, "sandy")
    pid = res["pattern_id"]
    lst = client.get("/patterns", headers=AUTH).json()
    assert [x["pattern_id"] for x in lst] == [pid]
    meta = client.get(f"/patterns/{pid}", headers=AUTH).json()
    assert meta["design"] == "sandy" and meta["measurements_source"] == "estimated"
    assert meta["fold_edges"]["skirt"] == "skirt.cf"
    assert client.get("/patterns/../../etc", headers=AUTH).status_code == 404
    assert client.get("/patterns/zzzz", headers=AUTH).status_code == 404
    assert client.delete(f"/patterns/{pid}", headers=AUTH).json() == {"deleted": pid}
    assert not (pdir / pid).exists()
    assert client.get(f"/patterns/{pid}", headers=AUTH).status_code == 404
    assert client.get(f"/patterns/{pid}/pattern.svg").status_code == 404


def test_custom_measurements_override(ctx):
    client, _ = ctx
    res = _draft(client, "teagan", measurements={"neck": 420})
    meta = client.get(f"/patterns/{res['pattern_id']}", headers=AUTH).json()
    assert meta["measurements"]["neck"] == 420 and meta["measurements_source"] == "estimated+custom"
    assert json.loads(json.dumps(meta))  # serileşebilir
