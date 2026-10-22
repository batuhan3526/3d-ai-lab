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
    gdb.reset_engine(); gdb.init_db()
    from gateway.db import get_sessionmaker
    from gateway.models.orm import Project
    with get_sessionmaker()() as s:
        p = Project(user_id="default", name="src", garment_type="tshirt",
                    template_id="generated", customizations={"color": "#ccc", "decals": []})
        s.add(p); s.commit(); s.refresh(p)
        pid = p.id
    sent = {}
    from common import celery_app as ca
    monkeypatch.setattr(ca.celery_app, "send_task",
                        lambda name, kwargs=None, queue=None, **_: sent.update(name=name, kwargs=kwargs, queue=queue))
    from gateway.main import app
    c = TestClient(app); c.sent = sent; c.pid = pid
    return c


def test_tile_enqueues(client):
    r = client.post("/generate/tile", headers=_AUTH, json={
        "source_project_id": client.pid, "motif_rel": "decals/x.png", "repeat": 5, "gpu": 1})
    assert r.status_code == 201, r.text
    assert client.sent["name"] == "tile.bake"
    assert client.sent["queue"] == "flux-gpu1"
    assert client.sent["kwargs"]["motif_rel"] == "decals/x.png"
    assert client.sent["kwargs"]["repeat"] == 5
    assert client.sent["kwargs"]["source_project_id"] == client.pid


def test_tile_unknown_source_404(client):
    r = client.post("/generate/tile", headers=_AUTH,
                    json={"source_project_id": "nope", "motif_rel": "decals/x.png"})
    assert r.status_code == 404


def test_tile_repeat_clamp_422(client):
    r = client.post("/generate/tile", headers=_AUTH,
                    json={"source_project_id": client.pid, "motif_rel": "decals/x.png", "repeat": 99})
    assert r.status_code == 422
