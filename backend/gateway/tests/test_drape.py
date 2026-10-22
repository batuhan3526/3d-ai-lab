"""POST /projects/{id}/drape route testleri (enqueue + varyasyon deseni).

Hermetik: tmp_path DB, fakeredis JobStore, celery send_task monkeypatch'lenir —
gerçek redis/celery/blender ÇALIŞMAZ.
"""
import fakeredis
import pytest
from fastapi.testclient import TestClient

_AUTH = {"Authorization": "Bearer test-token-bootstrap"}


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
    # Celery send_task'ı yakala
    sent = []
    from common import celery_app as ca
    monkeypatch.setattr(ca.celery_app, "send_task",
                        lambda name, kwargs=None, queue=None, **_: sent.append({"name": name, "kwargs": kwargs, "queue": queue}))
    # JobStore'u fakeredis'e bağla (drape.py içindeki _job_store)
    import gateway.routes.drape as dr
    from common.jobs import JobStore
    fake = fakeredis.FakeStrictRedis(decode_responses=True)
    store = JobStore(fake)
    monkeypatch.setattr(dr, "_job_store", lambda: store)
    from gateway.main import app
    c = TestClient(app)
    c.sent = sent; c.pid = pid; c.store = store
    return c


def test_drape_enqueues_clothsim_task_and_variation(client):
    r = client.post(f"/projects/{client.pid}/drape", headers=_AUTH,
                    json={"frames": 30})
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["project_id"] == client.pid
    assert body["job_id"] and body["variation_id"] and body["group_id"]
    # Tek celery task: clothsim.drape + clothsim-cpu (GPU YOK)
    calls = [c for c in client.sent if c["name"] == "clothsim.drape"]
    assert len(calls) == 1
    call = calls[0]
    assert call["queue"] == "clothsim-cpu"
    assert call["kwargs"]["project_id"] == client.pid
    assert call["kwargs"]["frames"] == 30
    assert call["kwargs"]["mannequin_id"] is None
    # SUBMITTED Variation satırı (kind=drape)
    from gateway.db import get_sessionmaker
    from gateway.models.orm import Variation
    with get_sessionmaker()() as s:
        rows = s.query(Variation).filter_by(group_id=body["group_id"]).all()
        assert len(rows) == 1
        assert rows[0].status == "SUBMITTED" and rows[0].kind == "drape"
        assert rows[0].job_id == body["job_id"]


def test_drape_passes_mannequin_id(client):
    r = client.post(f"/projects/{client.pid}/drape", headers=_AUTH,
                    json={"mannequin_id": "male_a", "frames": 40})
    assert r.status_code == 201, r.text
    call = [c for c in client.sent if c["name"] == "clothsim.drape"][0]
    assert call["kwargs"]["mannequin_id"] == "male_a"
    assert call["kwargs"]["frames"] == 40


def test_drape_defaults_frames_40(client):
    r = client.post(f"/projects/{client.pid}/drape", headers=_AUTH, json={})
    assert r.status_code == 201, r.text
    call = [c for c in client.sent if c["name"] == "clothsim.drape"][0]
    assert call["kwargs"]["frames"] == 40


def test_drape_unknown_project_404(client):
    r = client.post("/projects/nope/drape", headers=_AUTH, json={"frames": 20})
    assert r.status_code == 404


def test_drape_rejects_out_of_range_frames(client):
    r = client.post(f"/projects/{client.pid}/drape", headers=_AUTH,
                    json={"frames": 1})
    assert r.status_code == 422
    # Aralık dışı istek hiç enqueue etmemeli
    assert not [c for c in client.sent if c["name"] == "clothsim.drape"]
