"""Ölçüden özel manken testleri (F3).

- common.body_morph: GERÇEK taban GLB'ler (data/templates/mannequins) morflanır;
  üretilen mankende bağımsız ölçülen boy/göğüs/bel/kalça hedefin ±%3 içinde.
- POST /mannequins/custom → GLB + custom_manifest.json; GLB trimesh ile yüklenir,
  gerçek ölçek (metre) doğrulanır.
- GET /templates/mannequins taban + custom birleşik ("custom": true).
- DELETE /mannequins/custom/{id}: yalnız custom-* silinir.
- Türkçe 422 doğrulama mesajları.
"""
import json
import shutil
from pathlib import Path

import numpy as np
import pytest
import trimesh
from fastapi.testclient import TestClient

_REPO = Path(__file__).resolve().parents[3]
_REAL_MANN = _REPO / "data" / "templates" / "mannequins"
_AUTH = {"Authorization": "Bearer test-token-bootstrap"}

pytestmark = pytest.mark.skipif(
    not (_REAL_MANN / "female-a.glb").is_file() or not (_REAL_MANN / "male-a.glb").is_file(),
    reason="taban manken GLB'leri yok",
)


def _rel_err(measured: dict, body: dict, key: str) -> float:
    return abs(measured[key] - body[key]) / body[key]


# --- body_morph birim testleri (gerçek morf) ------------------------------------
@pytest.mark.parametrize("gender,body", [
    ("female", (150, 80, 65, 88)),
    ("female", (165, 88, 70, 96)),
    ("female", (180, 130, 120, 140)),
    ("male", (190, 110, 95, 105)),
    ("male", (170, 90, 75, 95)),
    ("male", (210, 150, 150, 150)),
])
def test_morph_hits_targets_within_3pct(gender, body):
    from common.body_morph import BASE_BY_GENDER, measure_body, morph_to_measurements

    h, c, w, p = body
    mesh, rep = morph_to_measurements(_REAL_MANN / f"{BASE_BY_GENDER[gender]}.glb", h, c, w, p)
    tgt = {"height_cm": h, "chest_cm": c, "waist_cm": w, "hip_cm": p}
    # Rapordaki ölçü ile mesh'in kendisinden yeniden (bağımsız) ölçüm aynı olmalı.
    again = measure_body(np.asarray(mesh.vertices), np.asarray(mesh.faces))
    for k in tgt:
        assert _rel_err(rep["measured"], tgt, k) <= 0.03, (k, rep["measured"], tgt)
        assert _rel_err(again, tgt, k) <= 0.03, (k, again, tgt)
    # Gerçek ölçek (metre), ayak tabanı y=0, topoloji korunur (aynı yüz sayısı).
    assert mesh.bounds[0][1] == pytest.approx(0.0, abs=1e-6)
    assert mesh.extents[1] == pytest.approx(h / 100.0, rel=1e-3)
    assert np.isfinite(mesh.vertices).all()


def test_morph_preserves_topology_and_no_spikes():
    """Morf yalnız vertex taşır: yüz dizisi aynı; kenar uzunlukları patlamaz."""
    from common.body_morph import load_base, morph_to_measurements

    path = _REAL_MANN / "female-a.glb"
    base = load_base(path)
    mesh, _rep = morph_to_measurements(path, 165, 100, 85, 108)
    assert np.array_equal(np.asarray(mesh.faces), base.f)
    e = np.asarray(mesh.edges_unique)
    base_len = np.linalg.norm(base.v[e[:, 0]] - base.v[e[:, 1]], axis=1) * 1.65
    new_len = np.linalg.norm(mesh.vertices[e[:, 0]] - mesh.vertices[e[:, 1]], axis=1)
    ratio = new_len[base_len > 1e-6] / base_len[base_len > 1e-6]
    # Hiçbir kenar 2.5 kattan fazla uzamasın / 0.3 kattan fazla kısalmasın.
    assert ratio.max() < 2.5 and ratio.min() > 0.3, (ratio.min(), ratio.max())


def test_detect_levels_order_on_bases():
    """Seviyeler anatomik sırada: kasık < kalça < bel < göğüs < koltuk altı < boyun."""
    from common.body_morph import load_base

    for name in ("female-a", "male-a"):
        lv = load_base(_REAL_MANN / f"{name}.glb").levels
        assert lv["crotch"] < lv["hip"] < lv["waist"] < lv["chest"] < lv["armpit"] < lv["neck"], lv


# --- route testleri -------------------------------------------------------------
@pytest.fixture
def tdir(tmp_path, monkeypatch):
    """Geçici templates dizini: gerçek taban GLB'ler + manifest kopyalanır."""
    monkeypatch.setenv("TEMPLATES_DIR", str(tmp_path).replace("\\", "/"))
    from common.config import get_settings
    get_settings.cache_clear()
    mdir = tmp_path / "mannequins"
    mdir.mkdir()
    for f in ("female-a.glb", "male-a.glb", "manifest.json"):
        shutil.copy(_REAL_MANN / f, mdir / f)
    yield tmp_path
    get_settings.cache_clear()


@pytest.fixture
def client(tdir):
    from gateway.main import app
    return TestClient(app)


def test_requires_auth(client):
    r = client.post("/mannequins/custom", json={"gender": "female"})
    assert r.status_code == 401


def test_create_list_serve_delete(client, tdir):
    body = {"gender": "female", "height_cm": 158, "chest_cm": 92, "waist_cm": 76, "hip_cm": 100}
    r = client.post("/mannequins/custom", json=body, headers=_AUTH)
    assert r.status_code == 200, r.text
    out = r.json()
    mid = out["id"]
    assert mid.startswith("custom-")
    assert out["file"] == f"mannequins/{mid}.glb"
    assert out["url"] == f"/template-assets/mannequins/{mid}.glb"
    assert out["custom"] is True and out["base"] == "female-a" and out["license"] == "CC0"
    assert "158" in out["label"]
    for k in ("height_cm", "chest_cm", "waist_cm", "hip_cm"):
        assert _rel_err(out["measured"], body, k) <= 0.03

    # GLB diskte, trimesh ile yüklenir, gerçek ölçekte (1.58 m).
    glb = tdir / "mannequins" / f"{mid}.glb"
    m = trimesh.load(str(glb), force="mesh")
    assert m.extents[1] == pytest.approx(1.58, rel=1e-3)
    # custom_manifest.json girdisi
    man = json.loads((tdir / "mannequins" / "custom_manifest.json").read_text(encoding="utf-8"))
    assert [e["id"] for e in man] == [mid]
    assert man[0]["body"]["gender"] == "female"

    # Statik servis (public)
    g = client.get(out["url"])
    assert g.status_code == 200 and g.content[:4] == b"glTF"

    # Birleşik liste: 3 taban + 1 custom; custom bayraklı, available True
    lst = client.get("/templates/mannequins").json()
    by_id = {e["id"]: e for e in lst}
    assert {"male-a", "female-a", "neutral-t", mid} <= set(by_id)
    assert by_id[mid]["custom"] is True and by_id[mid]["available"] is True
    assert not by_id["male-a"].get("custom")

    # Sil
    d = client.delete(f"/mannequins/custom/{mid}", headers=_AUTH)
    assert d.status_code == 200 and d.json() == {"deleted": mid}
    assert not glb.exists()
    assert mid not in {e["id"] for e in client.get("/templates/mannequins").json()}
    # İkinci silme → 404
    assert client.delete(f"/mannequins/custom/{mid}", headers=_AUTH).status_code == 404


def test_male_custom_label_and_base(client):
    body = {"gender": "male", "height_cm": 182, "chest_cm": 104, "waist_cm": 90,
            "hip_cm": 102, "label": "Abim"}
    out = client.post("/mannequins/custom", json=body, headers=_AUTH).json()
    assert out["label"] == "Abim" and out["base"] == "male-a"


def test_cannot_delete_base_mannequin(client, tdir):
    r = client.delete("/mannequins/custom/male-a", headers=_AUTH)
    assert r.status_code == 400
    assert "özel" in r.json()["detail"]
    assert (tdir / "mannequins" / "male-a.glb").exists()


@pytest.mark.parametrize("payload,needle", [
    ({"height_cm": 165, "chest_cm": 88, "waist_cm": 70, "hip_cm": 96}, "Cinsiyet"),
    ({"gender": "female", "chest_cm": 88, "waist_cm": 70, "hip_cm": 96}, "Boy girilmedi"),
    ({"gender": "female", "height_cm": 300, "chest_cm": 88, "waist_cm": 70, "hip_cm": 96},
     "Boy 120–215 cm"),
    ({"gender": "male", "height_cm": 175, "chest_cm": "abc", "waist_cm": 70, "hip_cm": 96},
     "Göğüs çevresi bir sayı"),
    ({"gender": "male", "height_cm": 175, "chest_cm": 90, "waist_cm": 20, "hip_cm": 96},
     "Bel çevresi 45–160"),
])
def test_validation_turkish_422(client, payload, needle):
    r = client.post("/mannequins/custom", json=payload, headers=_AUTH)
    assert r.status_code == 422
    assert needle in r.json()["detail"], r.json()


def test_comma_decimal_accepted(client):
    body = {"gender": "female", "height_cm": "162,5", "chest_cm": "86,5",
            "waist_cm": 68, "hip_cm": 94}
    r = client.post("/mannequins/custom", json=body, headers=_AUTH)
    assert r.status_code == 200, r.text
    assert r.json()["body"]["height_cm"] == 162.5
