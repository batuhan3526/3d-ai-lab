"""POST /patterns/{id}/sew3d route testleri (F2: kalıbı 3D'de mankene dik).

Hermetik: tmp_path DB + PATTERNS_DIR + TEMPLATES_DIR, fakeredis JobStore, celery
send_task monkeypatch'lenir — gerçek redis/celery/blender ÇALIŞMAZ. Gerçek Blender
dikişi worker testlerinde (workers/clothsim/tests/test_sew3d_worker.py).
"""
import json

import fakeredis
import pytest
from fastapi.testclient import TestClient

_AUTH = {"Authorization": "Bearer test-token-bootstrap"}
_PID = "a" * 32
_PID_FLAT = "b" * 32


def _write_pattern(root, pid, design, label, seams, sew3d=True):
    d = root / pid
    d.mkdir(parents=True)
    (d / "meta.json").write_text(json.dumps({
        "pattern_id": pid, "design": design, "label_tr": label, "category": "ust",
        "sew3d": sew3d, "created_at": "2026-10-17T00:00:00+00:00",
        "body": {"gender": "female", "height_cm": 165, "chest_cm": 88, "waist_cm": 70, "hip_cm": 96},
    }, ensure_ascii=False), encoding="utf-8")
    (d / "pieces.json").write_text(json.dumps({
        "pattern_id": pid, "design": design, "units": "mm", "sa_mm": 10, "measurements": {},
        "pieces": [], "seams": seams,
    }), encoding="utf-8")


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("APP_TOKEN", "test-token-bootstrap")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{str(tmp_path / 't.db').replace(chr(92), '/')}")
    monkeypatch.setenv("PROJECTS_DIR", str(tmp_path / "projects"))
    monkeypatch.setenv("PATTERNS_DIR", str(tmp_path / "patterns"))
    monkeypatch.setenv("TEMPLATES_DIR", str(tmp_path / "templates"))
    mdir = tmp_path / "templates" / "mannequins"
    mdir.mkdir(parents=True)
    for mid in ("female-a", "male-a", "custom-0123abcd"):
        (mdir / f"{mid}.glb").write_bytes(b"glTF")
    _write_pattern(tmp_path / "patterns", _PID, "teagan", "Tişört",
                   [{"a": "front.side", "b": "back.side", "reverse": False}])
    _write_pattern(tmp_path / "patterns", _PID_FLAT, "aaron", "Atlet", [], sew3d=False)
    from common.config import get_settings
    get_settings.cache_clear()
    from gateway import db as gdb
    gdb.reset_engine()
    gdb.init_db()
    sent = []
    from common import celery_app as ca
    monkeypatch.setattr(ca.celery_app, "send_task",
                        lambda name, kwargs=None, queue=None, **_: sent.append(
                            {"name": name, "kwargs": kwargs, "queue": queue}))
    import gateway.routes.sew3d as sw
    from common.jobs import JobStore
    store = JobStore(fakeredis.FakeStrictRedis(decode_responses=True))
    monkeypatch.setattr(sw, "_job_store", lambda: store)
    from gateway.main import app
    c = TestClient(app)
    c.sent = sent
    c.store = store
    yield c
    get_settings.cache_clear()


def _post(client, pid=_PID, **body):
    payload = {"mannequin_id": "female-a"}
    payload.update(body)
    return client.post(f"/patterns/{pid}/sew3d", headers=_AUTH, json=payload)


def test_sew3d_creates_project_and_enqueues(client):
    r = _post(client, fabric_id="silk", frames=90)
    assert r.status_code == 201, r.text
    body = r.json()
    assert set(body) == {"job_id", "project_id"}
    calls = [c for c in client.sent if c["name"] == "clothsim.sew3d"]
    assert len(calls) == 1
    call = calls[0]
    assert call["queue"] == "clothsim-cpu"  # GPU YOK
    assert call["kwargs"] == {"job_id": body["job_id"], "project_id": body["project_id"],
                              "pattern_id": _PID, "mannequin_id": "female-a",
                              "fabric_id": "silk", "frames": 90}
    # Proje satırı: Dashboard'da görünür (mesh_path worker'da yazılır).
    from gateway.db import get_sessionmaker
    from gateway.models.orm import Project
    with get_sessionmaker()() as s:
        p = s.get(Project, body["project_id"])
        assert p is not None
        assert p.name == "Tişört (kalıptan)"
        assert p.garment_type == "tshirt"
        assert p.engine_id == "sew3d"
        assert p.template_id == f"pattern-{_PID}"
        assert p.mesh_path is None
        assert p.customizations["material"] == "fabric:silk"
        assert p.customizations["decals"] == []
        assert p.customizations["sew3d"]["pattern_id"] == _PID
    # Job kaydı oluşturuldu (kind=sew3d, kalıp id'si meta'da).
    job = client.store.get(body["job_id"])
    assert job is not None
    assert job["kind"] == "sew3d" and job["pattern_id"] == _PID
    assert job["project_id"] == body["project_id"]


def test_sew3d_project_listed(client):
    r = _post(client)
    assert r.status_code == 201
    lst = client.get("/projects", headers=_AUTH)
    assert lst.status_code == 200
    ids = [p["id"] for p in (lst.json() if isinstance(lst.json(), list) else lst.json().get("items", []))]
    assert r.json()["project_id"] in ids


def test_sew3d_defaults(client):
    r = _post(client)
    assert r.status_code == 201, r.text
    kw = client.sent[-1]["kwargs"]
    assert kw["fabric_id"] == "cotton" and kw["frames"] == 120


def test_sew3d_custom_mannequin_ok(client):
    r = _post(client, mannequin_id="custom-0123abcd")
    assert r.status_code == 201, r.text
    assert client.sent[-1]["kwargs"]["mannequin_id"] == "custom-0123abcd"


def test_sew3d_unsupported_design_422(client):
    r = _post(client, pid=_PID_FLAT)
    assert r.status_code == 422
    msg = r.json()["detail"]
    assert "Atlet" in msg and "henüz 3D'de dikilemiyor" in msg
    assert "Tişört" in msg  # desteklenen tasarımlar listelenir
    assert not client.sent


def test_sew3d_unknown_pattern_404(client):
    r = _post(client, pid="c" * 32)
    assert r.status_code == 404
    assert r.json()["detail"] == "Kalıp bulunamadı"


def test_sew3d_path_traversal_404(client):
    r = client.post("/patterns/..%2F..%2Fetc/sew3d", headers=_AUTH, json={"mannequin_id": "female-a"})
    assert r.status_code in (404, 405)
    r = _post(client, pid="ZZZ")
    assert r.status_code == 404


@pytest.mark.parametrize("mid", ["yok-boyle", "../female-a", "Female-A", ""])
def test_sew3d_bad_mannequin_422(client, mid):
    r = _post(client, mannequin_id=mid)
    assert r.status_code == 422
    assert "manken" in r.json()["detail"].lower()
    assert not client.sent


def test_sew3d_mannequin_required(client):
    r = client.post(f"/patterns/{_PID}/sew3d", headers=_AUTH, json={})
    assert r.status_code == 422


def test_sew3d_unknown_fabric_422(client):
    r = _post(client, fabric_id="kadife")
    assert r.status_code == 422
    assert r.json()["detail"].startswith("Bilinmeyen kumaş: 'kadife'")


@pytest.mark.parametrize("frames", [5, 500])
def test_sew3d_frames_range_422(client, frames):
    r = _post(client, frames=frames)
    assert r.status_code == 422
    assert "kare sayısı" in r.json()["detail"]


def test_sew3d_requires_token(client):
    r = client.post(f"/patterns/{_PID}/sew3d", json={"mannequin_id": "female-a"})
    assert r.status_code == 401


def test_sew3d_route_registered():
    from gateway.main import app
    paths = {getattr(r, "path", None) for r in app.routes}
    assert "/patterns/{pattern_id}/sew3d" in paths
