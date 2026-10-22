import fakeredis
import pytest
from fastapi.testclient import TestClient

AUTH = {"Authorization": "Bearer test-token-bootstrap"}


@pytest.fixture
def client(tmp_path, monkeypatch):
    db_path = str(tmp_path / "t.db").replace("\\", "/")
    monkeypatch.setenv("APP_TOKEN", "test-token-bootstrap")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    monkeypatch.setenv("PROJECTS_DIR", str(tmp_path / "projects").replace("\\", "/"))
    from common.config import get_settings
    get_settings.cache_clear()
    from gateway import db
    db.reset_engine()
    db.init_db()
    fake = fakeredis.FakeStrictRedis(decode_responses=True)
    import gateway.routes.generate as gen
    from common.jobs import JobStore
    monkeypatch.setattr(gen, "_job_store", lambda: JobStore(fake))
    sent = {}
    monkeypatch.setattr(gen, "_enqueue", lambda **kw: sent.update(kw))
    from gateway.main import app
    c = TestClient(app)
    c._sent = sent
    yield c
    db.reset_engine()


def test_generate_text_creates_project_and_job(client):
    resp = client.post("/generate/text",
                       json={"prompt": "kırmızı çiçekli bluz", "garment_type": "tshirt"},
                       headers=AUTH)
    assert resp.status_code == 201
    body = resp.json()
    assert body["job_id"] and body["project_id"]
    assert client._sent["prompt"] == "kırmızı çiçekli bluz"
    assert client._sent["garment_type"] == "tshirt"


def test_generate_requires_auth(client):
    assert client.post("/generate/text",
                       json={"prompt": "x", "garment_type": "tshirt"}).status_code == 401


def test_generate_rejects_unknown_garment(client):
    resp = client.post("/generate/text", json={"prompt": "x", "garment_type": "dress"},
                       headers=AUTH)
    assert resp.status_code == 422
