"""Kumaş hazır ayarları testleri: common.fabrics API + GET /fabrics + drape fabric_id.

Hermetik: tmp_path DB, fakeredis JobStore, celery send_task monkeypatch'lenir —
gerçek redis/celery/blender ÇALIŞMAZ (gerçek Blender karşılaştırması clothsim
worker testlerinde).
"""
import json
import re

import fakeredis
import pytest
from fastapi.testclient import TestClient

from common import fabrics as fb

_AUTH = {"Authorization": "Bearer test-token-bootstrap"}
_IDS = {"cotton", "denim", "silk", "knit", "linen", "leather", "chiffon", "wool"}


# --- common.fabrics -------------------------------------------------------------
def test_eight_fabrics_with_required_fields():
    assert set(fb.fabric_ids()) == _IDS
    for f in fb.FABRICS:
        for k in ("id", "name_tr", "name_en", "desc_tr", "blender", "pbr"):
            assert f[k], (f["id"], k)
        b = f["blender"]
        for k in ("mass", "tension_stiffness", "compression_stiffness",
                  "shear_stiffness", "bending_stiffness", "air_damping", "quality"):
            assert k in b and b[k] >= 0, (f["id"], k)
        p = f["pbr"]
        assert re.fullmatch(r"#[0-9a-f]{6}", p["base_color"])
        assert re.fullmatch(r"#[0-9a-f]{6}", p["sheen_color"])
        for k in ("roughness", "metalness", "sheen", "sheen_roughness"):
            assert 0.0 <= p[k] <= 1.0, (f["id"], k)


def test_denim_is_backward_compatible_default():
    """denim = eski drape değerleri (t/c 80, shear 40, bending 0.5, quality 6)."""
    assert fb.DEFAULT_FABRIC_ID == "denim"
    d = fb.blender_params("denim")
    assert d["quality"] == 6
    assert d["tension_stiffness"] == 80.0 and d["compression_stiffness"] == 80.0
    assert d["shear_stiffness"] == 40.0 and d["bending_stiffness"] == 0.5
    # Diğer alanlar Blender varsayılanı → eski çağrıyla birebir aynı sim.
    assert d["mass"] == 0.3 and d["air_damping"] == 1.0
    assert fb.blender_params(None) == d


def test_blender_params_flat_and_json_serializable():
    for fid in fb.fabric_ids():
        p = fb.blender_params(fid)
        assert set(p) <= set(fb.BLENDER_KEYS)
        assert json.loads(json.dumps(p)) == p


def test_relative_physics_silk_light_leather_stiff():
    silk, leather, denim = (fb.blender_params(x) for x in ("silk", "leather", "denim"))
    assert silk["mass"] < denim["mass"] < leather["mass"]
    assert silk["bending_stiffness"] < denim["bending_stiffness"] < leather["bending_stiffness"]


def test_unknown_fabric():
    assert fb.get_fabric("kadife") is None
    assert fb.get_fabric(None) is None
    with pytest.raises(KeyError, match="Bilinmeyen kumaş"):
        fb.blender_params("kadife")


def test_list_and_get_return_copies():
    lst = fb.list_fabrics()
    lst[0]["blender"]["mass"] = 999
    g = fb.get_fabric("denim")
    g["blender"]["tension_stiffness"] = 1
    assert fb.FABRICS[0]["blender"]["mass"] != 999
    assert fb.blender_params("denim")["tension_stiffness"] == 80.0


# --- Rotalar --------------------------------------------------------------------
@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("APP_TOKEN", "test-token-bootstrap")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{str(tmp_path / 't.db').replace(chr(92), '/')}")
    from common.config import get_settings
    get_settings.cache_clear()
    from gateway import db as gdb
    gdb.reset_engine()
    gdb.init_db()
    from gateway.db import get_sessionmaker
    from gateway.models.orm import Project
    with get_sessionmaker()() as s:
        p = Project(user_id="default", name="src", garment_type="tshirt",
                    template_id="generated", customizations={"color": "#ccc", "decals": []})
        s.add(p); s.commit(); s.refresh(p)
        pid = p.id
    sent = []
    from common import celery_app as ca
    monkeypatch.setattr(ca.celery_app, "send_task",
                        lambda name, kwargs=None, queue=None, **_: sent.append({"name": name, "kwargs": kwargs, "queue": queue}))
    import gateway.routes.drape as dr
    from common.jobs import JobStore
    store = JobStore(fakeredis.FakeStrictRedis(decode_responses=True))
    monkeypatch.setattr(dr, "_job_store", lambda: store)
    from gateway.main import app
    c = TestClient(app)
    c.sent = sent; c.pid = pid
    return c


def test_get_fabrics_lists_all(client):
    r = client.get("/fabrics", headers=_AUTH)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["default"] == "denim"
    assert {f["id"] for f in body["fabrics"]} == _IDS
    silk = next(f for f in body["fabrics"] if f["id"] == "silk")
    assert silk["name_tr"] == "İpek" and "pbr" in silk and "blender" in silk


def test_get_fabrics_requires_token(client):
    assert client.get("/fabrics").status_code == 401


def test_drape_passes_fabric_id(client):
    r = client.post(f"/projects/{client.pid}/drape", headers=_AUTH,
                    json={"frames": 30, "fabric_id": "silk"})
    assert r.status_code == 201, r.text
    call = [c for c in client.sent if c["name"] == "clothsim.drape"][0]
    assert call["kwargs"]["fabric_id"] == "silk"


def test_drape_without_fabric_sends_none(client):
    r = client.post(f"/projects/{client.pid}/drape", headers=_AUTH, json={})
    assert r.status_code == 201, r.text
    call = [c for c in client.sent if c["name"] == "clothsim.drape"][0]
    assert call["kwargs"]["fabric_id"] is None


def test_drape_unknown_fabric_422_turkish(client):
    r = client.post(f"/projects/{client.pid}/drape", headers=_AUTH,
                    json={"fabric_id": "kadife"})
    assert r.status_code == 422
    assert "Bilinmeyen kumaş" in r.json()["detail"]
    assert not [c for c in client.sent if c["name"] == "clothsim.drape"]
