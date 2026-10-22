import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("APP_TOKEN", "test-token-bootstrap")
    from common.config import get_settings
    get_settings.cache_clear()
    from gateway.main import app
    return TestClient(app)


_AUTH = {"Authorization": "Bearer test-token-bootstrap"}


def test_list_engines_requires_auth(client):
    assert client.get("/engines").status_code == 401


def test_list_engines_returns_catalog(client):
    r = client.get("/engines", headers=_AUTH)
    assert r.status_code == 200
    ids = [e["id"] for e in r.json()]
    assert "trellis-text" in ids


def test_list_engines_exposes_default_gpu(client, monkeypatch):
    """Tek-GPU sözleşmesi: frontend GPU varsayılanını backend'den okur (DEFAULT_GPU)."""
    monkeypatch.setenv("DEFAULT_GPU", "1")
    from common.config import get_settings
    get_settings.cache_clear()
    r = client.get("/engines", headers=_AUTH)
    assert r.status_code == 200
    for e in r.json():
        assert e["default_gpu"] == 1
