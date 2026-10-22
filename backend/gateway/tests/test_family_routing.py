import io

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("APP_TOKEN", "test-token-bootstrap")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{str(tmp_path / 't.db').replace(chr(92), '/')}")
    monkeypatch.setenv("UPLOADS_DIR", str(tmp_path / "up").replace(chr(92), "/"))
    # Testler host GPU/.env'den bağımsız olsun: iki GPU görünür varsay
    monkeypatch.setenv("VISIBLE_GPUS", "0,1")
    from common.config import get_settings
    get_settings.cache_clear()
    from gateway import db as gdb
    gdb.reset_engine()
    gdb.init_db()
    sent = {}

    def fake(name, kwargs=None, queue=None, **_):
        sent.update({"name": name, "queue": queue, "kwargs": kwargs})

    from common import celery_app as ca
    monkeypatch.setattr(ca.celery_app, "send_task", fake)
    from gateway.main import app
    c = TestClient(app)
    c.sent = sent
    return c


_AUTH = {"Authorization": "Bearer test-token-bootstrap"}
_PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 64


def test_text_routes_to_trellis_family(client):
    r = client.post("/generate/text", headers=_AUTH,
                    json={"prompt": "x", "garment_type": "tshirt", "gpu": 1})
    assert r.status_code == 201
    assert client.sent["queue"] == "trellis-gpu1"


def test_image_hi3dgen_routes_to_hi3dgen_family(client):
    r = client.post("/generate/image", headers=_AUTH,
                    files={"file": ("p.png", io.BytesIO(_PNG), "image/png")},
                    data={"garment_type": "boots", "gpu": "0", "quality": "fast",
                          "engine_id": "hi3dgen-image"})
    assert r.status_code == 201
    assert client.sent["queue"] == "hi3dgen-gpu0"
    assert client.sent["kwargs"]["engine_id"] == "hi3dgen-image"


def test_image_unavailable_engine_rejected(client):
    # flex4dhuman-4d placeholder (kod/ağırlık yok) -> available=False; route 422 ile reddetmeli
    r = client.post("/generate/image", headers=_AUTH,
                    files={"file": ("p.png", io.BytesIO(_PNG), "image/png")},
                    data={"garment_type": "boots", "gpu": "0", "quality": "fast",
                          "engine_id": "flex4dhuman-4d"})
    assert r.status_code == 422
    assert "queue" not in client.sent


def test_image_default_trellis(client):
    client.post("/generate/image", headers=_AUTH,
                files={"file": ("p.png", io.BytesIO(_PNG), "image/png")},
                data={"garment_type": "boots", "gpu": "1", "quality": "fast"})
    assert client.sent["queue"] == "trellis-gpu1"
    assert client.sent["kwargs"]["engine_id"] == "trellis-image"
