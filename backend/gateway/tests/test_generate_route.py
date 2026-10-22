import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path, monkeypatch):
    db_path = str(tmp_path / "t.db").replace("\\", "/")
    monkeypatch.setenv("APP_TOKEN", "test-token-bootstrap")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    from common.config import get_settings
    get_settings.cache_clear()
    from gateway import db
    db.reset_engine()
    db.init_db()

    sent = {}

    def fake_send_task(name, kwargs=None, queue=None, **_):
        sent["name"] = name
        sent["kwargs"] = kwargs
        sent["queue"] = queue

    from common import celery_app as ca
    monkeypatch.setattr(ca.celery_app, "send_task", fake_send_task)

    from gateway.main import app
    c = TestClient(app)
    c.sent = sent
    return c


_AUTH = {"Authorization": "Bearer test-token-bootstrap"}


def test_routes_to_selected_gpu_queue(client):
    r = client.post("/generate/text", headers=_AUTH, json={
        "prompt": "kirmizi bot", "garment_type": "boots", "gpu": 0, "quality": "fast"})
    assert r.status_code == 201
    assert client.sent["queue"] == "trellis-gpu0"
    assert client.sent["name"] == "text_to_3d.generate"
    assert client.sent["kwargs"]["quality"] == "fast"
    assert client.sent["kwargs"]["prompt"] == "kirmizi bot"
    assert client.sent["kwargs"]["prompt_enhance"] is True


def test_defaults_to_gpu1(client):
    r = client.post("/generate/text", headers=_AUTH, json={
        "prompt": "mavi etek", "garment_type": "skirt"})
    assert r.status_code == 201
    assert client.sent["queue"] == "trellis-gpu1"
