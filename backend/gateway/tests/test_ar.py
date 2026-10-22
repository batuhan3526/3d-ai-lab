"""AR varlığı testleri — POST /projects/{id}/ar-asset + GET /projects/{id}/ar.usdz.

Hermetik: her test tmp_path SQLite + PROJECTS_DIR kullanır (gerçek data/ dizinine
yazmaz), env monkeypatch + get_settings.cache_clear + db.reset_engine ile izole
edilir (test_gallery.py deseni).
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

AUTH = {"Authorization": "Bearer test-token-bootstrap"}
# Gerçek USDZ = zip; içerik-tipi ve yuvarlak-tur (yükle→GET) için ikili yeterli.
_USDZ_BYTES = b"PK\x03\x04fake-usdz-payload"


@pytest.fixture
def client(tmp_path, monkeypatch):
    db_path = str(tmp_path / "ar.db").replace("\\", "/")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    monkeypatch.setenv("APP_TOKEN", "test-token-bootstrap")
    monkeypatch.setenv("PROJECTS_DIR", str(tmp_path / "projects").replace("\\", "/"))
    from common.config import get_settings
    get_settings.cache_clear()
    from gateway import db
    db.reset_engine()
    db.init_db()
    from gateway.main import app
    yield TestClient(app)
    db.reset_engine()
    get_settings.cache_clear()


def _make(client) -> str:
    return client.post("/projects", json={
        "name": "AR Tasarımı", "garment_type": "tshirt", "template_id": "tshirt-01",
        "customizations": {"color": "#00ff00", "decals": []},
    }, headers=AUTH).json()["id"]


# --- auth ----------------------------------------------------------------------
def test_upload_requires_auth(client):
    pid = _make(client)
    r = client.post(f"/projects/{pid}/ar-asset",
                    files={"file": ("ar.usdz", _USDZ_BYTES, "model/vnd.usd+zip")})
    assert r.status_code == 401


# --- upload + serve ------------------------------------------------------------
def test_upload_returns_usdz_and_glb_urls(client):
    pid = _make(client)
    r = client.post(f"/projects/{pid}/ar-asset", headers=AUTH,
                    files={"file": ("ar.usdz", _USDZ_BYTES, "model/vnd.usd+zip")})
    assert r.status_code == 200
    body = r.json()
    assert body["usdz_url"] == f"/projects/{pid}/ar.usdz"
    assert body["glb_url"] == f"/projects/{pid}/mesh"


def test_get_usdz_serves_bytes_with_content_type(client):
    pid = _make(client)
    client.post(f"/projects/{pid}/ar-asset", headers=AUTH,
                files={"file": ("ar.usdz", _USDZ_BYTES, "model/vnd.usd+zip")})
    # GET public: Authorization header'sız erişilebilmeli (iOS Quick Look deseni).
    r = client.get(f"/projects/{pid}/ar.usdz")
    assert r.status_code == 200
    assert r.headers["content-type"] == "model/vnd.usd+zip"
    assert r.content == _USDZ_BYTES


def test_get_usdz_before_upload_404(client):
    pid = _make(client)
    assert client.get(f"/projects/{pid}/ar.usdz").status_code == 404


def test_upload_missing_project_404(client):
    r = client.post("/projects/does-not-exist/ar-asset", headers=AUTH,
                    files={"file": ("ar.usdz", _USDZ_BYTES, "model/vnd.usd+zip")})
    assert r.status_code == 404


def test_get_usdz_missing_project_404(client):
    assert client.get("/projects/nope/ar.usdz").status_code == 404


# --- UA-yönlendirmeli açılış sayfası (R4) --------------------------------------
_IPHONE_UA = ("Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
              "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1")
_ANDROID_UA = ("Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 "
               "(KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36")


def test_ar_landing_iphone_redirects_to_usdz(client):
    pid = _make(client)
    # Açılış sayfası public (tokensız) — QR'ı tarayan telefon header ekleyemez.
    r = client.get(f"/projects/{pid}/ar", headers={"User-Agent": _IPHONE_UA})
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    assert f"/projects/{pid}/ar.usdz" in r.text
    # iOS için Android Scene Viewer intent'i olmamalı.
    assert "scene-viewer" not in r.text


def test_ar_landing_android_uses_scene_viewer_intent(client):
    pid = _make(client)
    r = client.get(f"/projects/{pid}/ar", headers={"User-Agent": _ANDROID_UA})
    assert r.status_code == 200
    assert "intent://arvr.google.com/scene-viewer" in r.text
    assert f"/projects/{pid}/mesh" in r.text
    assert "com.google.ar.core" in r.text
    assert "browser_fallback_url" in r.text


def test_ar_landing_desktop_shows_both_links(client):
    pid = _make(client)
    r = client.get(f"/projects/{pid}/ar", headers={"User-Agent": "Mozilla/5.0 (X11; Linux)"})
    assert r.status_code == 200
    assert f"/projects/{pid}/ar.usdz" in r.text
    assert f"/projects/{pid}/mesh" in r.text


def test_ar_landing_missing_project_404(client):
    assert client.get("/projects/does-not-exist/ar").status_code == 404


def test_ar_landing_absolute_urls_use_host_header(client):
    pid = _make(client)
    r = client.get(f"/projects/{pid}/ar", headers={
        "User-Agent": _ANDROID_UA, "Host": "192.0.2.10:9000"})
    assert "192.0.2.10:9000/projects" in r.text
