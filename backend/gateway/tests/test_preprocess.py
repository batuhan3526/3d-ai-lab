import io

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("APP_TOKEN", "test-token-bootstrap")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{str(tmp_path / 't.db').replace(chr(92), '/')}")
    monkeypatch.setenv("UPLOADS_DIR", str(tmp_path / "up").replace(chr(92), "/"))
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

    # JobStore.create Redis'e dokunmasın (hermetik).
    from common import jobs as jobs_mod
    monkeypatch.setattr(jobs_mod.JobStore, "__init__", lambda self, *a, **k: None)
    monkeypatch.setattr(jobs_mod.JobStore, "create", lambda self, job_id, meta: None)

    from gateway.main import app
    c = TestClient(app)
    c.sent = sent
    c.uploads = tmp_path / "up"
    return c


_AUTH = {"Authorization": "Bearer test-token-bootstrap"}
_PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 64


def test_matte_enqueues_image_matte_task(client):
    r = client.post("/preprocess/matte", headers=_AUTH,
                    files={"file": ("photo.png", io.BytesIO(_PNG), "image/png")},
                    data={"gpu": "1"})
    assert r.status_code == 201
    body = r.json()
    assert "job_id" in body and body["job_id"]
    # out_url PNG'yi serve eden GET route'una işaret eder (matte_<uuid>.png).
    assert body["out_url"].startswith("/preprocess/matte/matte_")
    assert body["out_url"].endswith(".png")

    assert client.sent["name"] == "image.matte"
    assert client.sent["queue"] == "flux-gpu1"
    kw = client.sent["kwargs"]
    assert kw["job_id"] == body["job_id"]
    assert kw["image_path"].endswith(".png")
    # out_path adı out_url'deki dosya adıyla eşleşir.
    out_name = body["out_url"].rsplit("/", 1)[-1]
    assert kw["out_path"].endswith(out_name)
    # Yüklenen orijinal foto UPLOADS_DIR'e yazıldı.
    from pathlib import Path
    assert Path(kw["image_path"]).exists()
    assert Path(kw["image_path"]).parent == client.uploads


def test_matte_default_gpu_when_omitted(client):
    # gpu verilmezse settings.default_gpu (tek-GPU sözleşmesi) doldurur.
    r = client.post("/preprocess/matte", headers=_AUTH,
                    files={"file": ("photo.png", io.BytesIO(_PNG), "image/png")})
    assert r.status_code == 201
    assert client.sent["queue"].startswith("flux-gpu")


def test_matte_requires_auth(client):
    r = client.post("/preprocess/matte",
                    files={"file": ("photo.png", io.BytesIO(_PNG), "image/png")})
    assert r.status_code in (401, 403)
    assert "name" not in client.sent


def test_get_matte_serves_written_png_tokenless(client):
    client.uploads.mkdir(parents=True, exist_ok=True)
    (client.uploads / "matte_abc123.png").write_bytes(_PNG)
    # GET token'sız (Authorization header YOK) çalışmalı.
    r = client.get("/preprocess/matte/matte_abc123.png")
    assert r.status_code == 200
    assert r.headers["content-type"] == "image/png"
    assert r.content == _PNG


def test_get_matte_missing_is_404(client):
    r = client.get("/preprocess/matte/matte_missing.png")
    assert r.status_code == 404


def test_get_matte_rejects_path_traversal(client):
    r = client.get("/preprocess/matte/..%2F..%2Fetc%2Fpasswd")
    assert r.status_code in (400, 404)
    r2 = client.get("/preprocess/matte/evil.txt")
    assert r2.status_code == 400
