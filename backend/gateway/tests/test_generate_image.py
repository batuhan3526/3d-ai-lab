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


def test_image_upload_enqueues_and_saves(client):
    png = b"\x89PNG\r\n\x1a\n" + b"0" * 64
    r = client.post("/generate/image", headers=_AUTH,
                    files={"file": ("p.png", io.BytesIO(png), "image/png")},
                    data={"garment_type": "boots", "gpu": "1", "quality": "fast"})
    assert r.status_code == 201
    assert client.sent["name"] == "image_to_3d.generate"
    assert client.sent["queue"] == "trellis-gpu1"
    assert client.sent["kwargs"]["image_name"]
    assert client.sent["kwargs"]["garment_type"] == "boots"


def test_image_rejects_unknown_garment(client):
    png = b"\x89PNG\r\n\x1a\n" + b"0" * 64
    r = client.post("/generate/image", headers=_AUTH,
                    files={"file": ("p.png", io.BytesIO(png), "image/png")},
                    data={"garment_type": "xxx", "gpu": "1", "quality": "fast"})
    assert r.status_code == 422
