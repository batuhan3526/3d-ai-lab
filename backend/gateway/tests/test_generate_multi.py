import io

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path, monkeypatch):
    db = str(tmp_path / "t.db").replace("\\", "/")
    monkeypatch.setenv("APP_TOKEN", "test-token-bootstrap")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db}")
    monkeypatch.setenv("UPLOADS_DIR", str(tmp_path / "uploads").replace("\\", "/"))
    from common.config import get_settings
    get_settings.cache_clear()
    from gateway import db as gdb
    gdb.reset_engine()
    gdb.init_db()
    sent = {}

    def fake_send_task(name, kwargs=None, queue=None, **_):
        sent.update({"name": name, "kwargs": kwargs, "queue": queue})

    from common import celery_app as ca
    monkeypatch.setattr(ca.celery_app, "send_task", fake_send_task)
    from gateway.main import app
    c = TestClient(app)
    c.sent = sent
    return c


_AUTH = {"Authorization": "Bearer test-token-bootstrap"}
_PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 64


def test_multi_upload_enqueues(client):
    files = [("files", ("a.png", io.BytesIO(_PNG), "image/png")),
             ("files", ("b.png", io.BytesIO(_PNG), "image/png"))]
    r = client.post("/generate/multi-image", headers=_AUTH, files=files,
                    data={"garment_type": "boots", "gpu": "1", "quality": "fast"})
    assert r.status_code == 201
    assert client.sent["name"] == "multi_image_to_3d.generate"
    assert client.sent["queue"] == "trellis-gpu1"
    assert len(client.sent["kwargs"]["image_names"]) == 2


def test_multi_rejects_unknown_garment(client):
    files = [("files", ("a.png", io.BytesIO(_PNG), "image/png"))]
    r = client.post("/generate/multi-image", headers=_AUTH, files=files,
                    data={"garment_type": "xxx", "gpu": "1", "quality": "fast"})
    assert r.status_code == 422


def test_multi_rejects_engine_without_multi_capability(client):
    """Sessiz trellis fallback'i kapatıldı: çoklu-foto desteklemeyen motor 422 almalı."""
    files = [("files", ("a.png", io.BytesIO(_PNG), "image/png")),
             ("files", ("b.png", io.BytesIO(_PNG), "image/png"))]
    r = client.post("/generate/multi-image", headers=_AUTH, files=files,
                    data={"garment_type": "boots", "gpu": "1", "quality": "fast",
                          "engine_id": "triposr"})
    assert r.status_code == 422
    assert "çoklu fotoğraf" in r.json()["detail"]


def test_multi_routes_to_engine_family_queue(client):
    files = [("files", ("a.png", io.BytesIO(_PNG), "image/png")),
             ("files", ("b.png", io.BytesIO(_PNG), "image/png"))]
    r = client.post("/generate/multi-image", headers=_AUTH, files=files,
                    data={"garment_type": "boots", "gpu": "0", "quality": "fast",
                          "engine_id": "trellis-image"})
    assert r.status_code == 201
    assert client.sent["queue"] == "trellis-gpu0"
    assert client.sent["kwargs"]["engine_id"] == "trellis-image"
