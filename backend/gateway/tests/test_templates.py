"""Templates router testleri."""
import json

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def templates_dir(tmp_path, monkeypatch):
    """Geçici templates dizini + manifest + bir sahte GLB hazırla."""
    monkeypatch.setenv("TEMPLATES_DIR", str(tmp_path).replace("\\", "/"))
    from common.config import get_settings
    get_settings.cache_clear()

    (tmp_path / "tshirt").mkdir()
    (tmp_path / "tshirt" / "tshirt-01.glb").write_bytes(b"GLB-DATA")
    manifest = {"garments": [{"type": "tshirt", "label": "Tişört", "templates": [
        {"id": "tshirt-01", "name": "Tişört 1", "glb": "tshirt/tshirt-01.glb",
         "thumbnail": "tshirt/tshirt-01.png", "license": "CC0 (procedural)",
         "source": "generated"}]}]}
    (tmp_path / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    yield tmp_path
    get_settings.cache_clear()


@pytest.fixture
def client(templates_dir):
    from gateway.main import app
    return TestClient(app)


def test_get_manifest_public_no_auth(client):
    resp = client.get("/templates")
    assert resp.status_code == 200
    body = resp.json()
    assert body["garments"][0]["type"] == "tshirt"
    assert len(body["garments"][0]["templates"]) == 1


def test_get_template_glb_file(client):
    resp = client.get("/template-assets/tshirt/tshirt-01.glb")
    assert resp.status_code == 200
    assert resp.content == b"GLB-DATA"


def test_missing_glb_returns_404(client):
    resp = client.get("/template-assets/tshirt/nope.glb")
    assert resp.status_code == 404


def test_manifest_missing_returns_503(tmp_path, monkeypatch):
    """manifest.json yoksa anlamlı hata (generate.py çalıştırılmamış)."""
    monkeypatch.setenv("TEMPLATES_DIR", str(tmp_path / "empty").replace("\\", "/"))
    from common.config import get_settings
    get_settings.cache_clear()
    from gateway.main import app
    c = TestClient(app)
    resp = c.get("/templates")
    assert resp.status_code == 503
    get_settings.cache_clear()
