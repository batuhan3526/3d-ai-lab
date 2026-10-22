import fakeredis
import pytest
from fastapi.testclient import TestClient

AUTH = {"Authorization": "Bearer test-token-bootstrap"}


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("APP_TOKEN", "test-token-bootstrap")
    from common.config import get_settings
    get_settings.cache_clear()
    fake = fakeredis.FakeStrictRedis(decode_responses=True)
    import gateway.routes.jobs as jr
    from common.jobs import JobStore
    store = JobStore(fake)
    store.create("j1", {"project_id": "p1"})
    store.set_progress("j1", "shape", 40)
    monkeypatch.setattr(jr, "_job_store", lambda: store)
    from gateway.main import app
    return TestClient(app)


def test_get_job(client):
    resp = client.get("/jobs/j1", headers=AUTH)
    assert resp.status_code == 200
    body = resp.json()
    assert body["state"] == "PROGRESS"
    assert body["stage"] == "shape"
    assert body["percent"] == 40


def test_get_job_missing_404(client):
    assert client.get("/jobs/nope", headers=AUTH).status_code == 404


def test_get_job_requires_auth(client):
    assert client.get("/jobs/j1").status_code == 401
