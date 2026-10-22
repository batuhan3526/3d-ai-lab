"""POST /convert/video testleri — turntable webm → mp4 (ffmpeg).

Hermetik: ffmpeg binary GEREKMEZ. `subprocess.run` ve ffmpeg çözümleyicisi
modül attribute'ları üzerinden monkeypatch'lenir; gerçek ffmpeg asla çağrılmaz.
"""
from __future__ import annotations

import types
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

AUTH = {"Authorization": "Bearer test-token-bootstrap"}
_WEBM = b"\x1aE\xdf\xa3fake-webm-payload"
_MP4_MAGIC = b"\x00\x00\x00\x18ftypmp42fake-mp4"


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("APP_TOKEN", "test-token-bootstrap")
    from common.config import get_settings
    get_settings.cache_clear()
    from gateway.main import app
    return TestClient(app)


def _fake_run_ok(cmd, **kwargs):
    """ffmpeg başarılı: çıktı yoluna (cmd son eleman) sahte mp4 yazar."""
    out = Path(cmd[-1])
    out.write_bytes(_MP4_MAGIC)
    return types.SimpleNamespace(returncode=0, stdout=b"", stderr=b"")


def _fake_run_fail(cmd, **kwargs):
    """ffmpeg hata: çıktı üretmez, returncode != 0."""
    return types.SimpleNamespace(returncode=1, stdout=b"", stderr=b"boom")


# --- auth ----------------------------------------------------------------------
def test_convert_requires_auth(client):
    r = client.post("/convert/video",
                    files={"file": ("turntable.webm", _WEBM, "video/webm")})
    assert r.status_code == 401


# --- başarı --------------------------------------------------------------------
def test_convert_returns_mp4_bytes(client, monkeypatch):
    import gateway.routes.media as media
    monkeypatch.setattr(media, "_resolve_ffmpeg", lambda: "/fake/ffmpeg")
    monkeypatch.setattr(media.subprocess, "run", _fake_run_ok)

    r = client.post("/convert/video", headers=AUTH,
                    files={"file": ("turntable.webm", _WEBM, "video/webm")})
    assert r.status_code == 200, r.text
    assert r.headers["content-type"] == "video/mp4"
    assert "attachment" in r.headers["content-disposition"]
    assert "turntable.mp4" in r.headers["content-disposition"]
    assert r.content == _MP4_MAGIC


def test_convert_invokes_ffmpeg_with_libx264(client, monkeypatch):
    import gateway.routes.media as media
    captured = {}

    def spy(cmd, **kwargs):
        captured["cmd"] = cmd
        return _fake_run_ok(cmd, **kwargs)

    monkeypatch.setattr(media, "_resolve_ffmpeg", lambda: "/fake/ffmpeg")
    monkeypatch.setattr(media.subprocess, "run", spy)
    r = client.post("/convert/video", headers=AUTH,
                    files={"file": ("turntable.webm", _WEBM, "video/webm")})
    assert r.status_code == 200
    cmd = captured["cmd"]
    assert cmd[0] == "/fake/ffmpeg"
    assert "libx264" in cmd
    assert "yuv420p" in cmd
    assert "+faststart" in cmd
    assert cmd[-1].endswith(".mp4")


# --- ffmpeg yok → 422 ----------------------------------------------------------
def test_convert_missing_ffmpeg_returns_422(client, monkeypatch):
    import gateway.routes.media as media
    monkeypatch.setattr(media, "_resolve_ffmpeg", lambda: None)
    r = client.post("/convert/video", headers=AUTH,
                    files={"file": ("turntable.webm", _WEBM, "video/webm")})
    assert r.status_code == 422
    assert "ffmpeg" in r.json()["detail"].lower()


# --- ffmpeg hata → 422 ---------------------------------------------------------
def test_convert_ffmpeg_failure_returns_422(client, monkeypatch):
    import gateway.routes.media as media
    monkeypatch.setattr(media, "_resolve_ffmpeg", lambda: "/fake/ffmpeg")
    monkeypatch.setattr(media.subprocess, "run", _fake_run_fail)
    r = client.post("/convert/video", headers=AUTH,
                    files={"file": ("turntable.webm", _WEBM, "video/webm")})
    assert r.status_code == 422


# --- boş dosya → 422 -----------------------------------------------------------
def test_convert_empty_upload_returns_422(client, monkeypatch):
    import gateway.routes.media as media
    monkeypatch.setattr(media, "_resolve_ffmpeg", lambda: "/fake/ffmpeg")
    monkeypatch.setattr(media.subprocess, "run", _fake_run_ok)
    r = client.post("/convert/video", headers=AUTH,
                    files={"file": ("turntable.webm", b"", "video/webm")})
    assert r.status_code == 422


# --- ffmpeg çözümleme sırası (env → which → default) ---------------------------
def test_resolve_ffmpeg_prefers_env(monkeypatch, tmp_path):
    import gateway.routes.media as media
    fake = tmp_path / "ffmpeg"
    fake.write_text("#!/bin/sh\n")
    monkeypatch.setenv("FFMPEG_BIN", str(fake))
    assert media._resolve_ffmpeg() == str(fake)


def test_resolve_ffmpeg_none_when_absent(monkeypatch):
    import gateway.routes.media as media
    monkeypatch.delenv("FFMPEG_BIN", raising=False)
    monkeypatch.setattr(media.shutil, "which", lambda _: None)
    monkeypatch.setattr(media.Path, "is_file", lambda self: False)
    assert media._resolve_ffmpeg() is None
