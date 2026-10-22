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
    store.create("j1", {"project_id": "p1", "kind": "motif"})
    store.set_progress("j1", "generate", 30)
    store.create("j2", {"project_id": "p2", "kind": "tile"})
    store.succeed("j2", {"project_id": "p2"})
    monkeypatch.setattr(jr, "_job_store", lambda: store)
    from gateway.main import app
    return TestClient(app)


def test_list_jobs(client):
    r = client.get("/jobs", headers=AUTH)
    assert r.status_code == 200
    jobs = r.json()
    assert {j["job_id"] for j in jobs} == {"j1", "j2"}
    # çalışan (PROGRESS) bitenden (SUCCESS) önce
    assert jobs[0]["job_id"] == "j1"
    j1 = next(j for j in jobs if j["job_id"] == "j1")
    assert j1["kind"] == "motif" and j1["percent"] == 30


def test_list_jobs_requires_auth(client):
    assert client.get("/jobs").status_code == 401
