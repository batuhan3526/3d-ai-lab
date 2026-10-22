"""POST /projects/{id}/upscale-texture route testleri (enqueue + varyasyon deseni).

Hermetik: tmp_path DB, fakeredis JobStore, celery send_task monkeypatch'lenir —
gerçek redis/celery/GPU/spandrel ÇALIŞMAZ. Kuyruk flux-gpu{default_gpu}; tek-GPU
host'ta default_gpu=0 → flux-gpu0.
"""
import fakeredis
import pytest
from fastapi.testclient import TestClient

_AUTH = {"Authorization": "Bearer test-token-bootstrap"}


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("APP_TOKEN", "test-token-bootstrap")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{str(tmp_path / 't.db').replace(chr(92), '/')}")
    # Tek-GPU sözleşmesi: görünür küme {0}'a çöksün (test hostunda GPU yok).
    monkeypatch.setenv("DEFAULT_GPU", "0")
    monkeypatch.setenv("VISIBLE_GPUS", "0")
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
    # Celery send_task'ı yakala
    sent = []
    from common import celery_app as ca
    monkeypatch.setattr(ca.celery_app, "send_task",
                        lambda name, kwargs=None, queue=None, **_: sent.append({"name": name, "kwargs": kwargs, "queue": queue}))
    # JobStore'u fakeredis'e bağla (upscale.py içindeki _job_store)
    import gateway.routes.upscale as up
    from common.jobs import JobStore
    fake = fakeredis.FakeStrictRedis(decode_responses=True)
    store = JobStore(fake)
    monkeypatch.setattr(up, "_job_store", lambda: store)
    from gateway.main import app
    c = TestClient(app)
    c.sent = sent; c.pid = pid; c.store = store
    return c


def test_upscale_enqueues_task_and_variation(client):
    r = client.post(f"/projects/{client.pid}/upscale-texture", headers=_AUTH,
                    json={"scale": 4})
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["project_id"] == client.pid
    assert body["job_id"] and body["variation_id"] and body["group_id"]
    # Tek celery task: texture.upscale → flux-gpu0 (default_gpu)
    calls = [c for c in client.sent if c["name"] == "texture.upscale"]
    assert len(calls) == 1
    call = calls[0]
    assert call["queue"] == "flux-gpu0"
    assert call["kwargs"]["project_id"] == client.pid
    assert call["kwargs"]["scale"] == 4
    assert call["kwargs"]["job_id"] == body["job_id"]
    # SUBMITTED Variation satırı (kind=upscale, seed=scale)
    from gateway.db import get_sessionmaker
    from gateway.models.orm import Variation
    with get_sessionmaker()() as s:
        rows = s.query(Variation).filter_by(group_id=body["group_id"]).all()
        assert len(rows) == 1
        assert rows[0].status == "SUBMITTED" and rows[0].kind == "upscale"
        assert rows[0].seed == 4
        assert rows[0].job_id == body["job_id"]


def test_upscale_defaults_scale_4(client):
    r = client.post(f"/projects/{client.pid}/upscale-texture", headers=_AUTH, json={})
    assert r.status_code == 201, r.text
    call = [c for c in client.sent if c["name"] == "texture.upscale"][0]
    assert call["kwargs"]["scale"] == 4


def test_upscale_explicit_gpu_routes_queue(client):
    r = client.post(f"/projects/{client.pid}/upscale-texture", headers=_AUTH,
                    json={"scale": 2, "gpu": 0})
    assert r.status_code == 201, r.text
    call = [c for c in client.sent if c["name"] == "texture.upscale"][0]
    assert call["queue"] == "flux-gpu0"


def test_upscale_rejects_gpu_out_of_range(client):
    r = client.post(f"/projects/{client.pid}/upscale-texture", headers=_AUTH,
                    json={"scale": 2, "gpu": 7})
    assert r.status_code == 422
    assert not [c for c in client.sent if c["name"] == "texture.upscale"]


def test_upscale_rejects_bad_scale(client):
    r = client.post(f"/projects/{client.pid}/upscale-texture", headers=_AUTH,
                    json={"scale": 3})
    assert r.status_code == 422
    # Geçersiz istek hiç enqueue etmemeli
    assert not [c for c in client.sent if c["name"] == "texture.upscale"]


def test_upscale_unknown_project_404(client):
    r = client.post("/projects/nope/upscale-texture", headers=_AUTH, json={"scale": 2})
    assert r.status_code == 404


def test_upscale_requires_auth(client):
    r = client.post(f"/projects/{client.pid}/upscale-texture", json={"scale": 2})
    assert r.status_code in (401, 403)
