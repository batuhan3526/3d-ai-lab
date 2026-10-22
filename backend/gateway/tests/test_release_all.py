import pytest
from fastapi.testclient import TestClient


class _R:
    def get(self, timeout=None):
        return {"mode": "cache", "unloaded": []}


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("APP_TOKEN", "test-token-bootstrap")
    from common.config import get_settings
    get_settings.cache_clear()
    sent = []

    def fake(name, kwargs=None, queue=None, expires=None, **_):
        sent.append((name, queue))
        return _R()

    from common import celery_app as ca
    monkeypatch.setattr(ca.celery_app, "send_task", fake)
    from gateway.main import app
    c = TestClient(app)
    c.sent = sent  # type: ignore[attr-defined]
    return c


_AUTH = {"Authorization": "Bearer test-token-bootstrap"}


def test_release_all_fans_out_to_all_queues(client):
    from common.engines.registry import engine_family, list_specs
    # GPU'suz aileler (clothsim, bulut) VRAM tutmaz → release fan-out'una girmez.
    fams = {engine_family(s["id"]) for s in list_specs() if s.get("gpus")}
    r = client.post("/engines/release-all", headers=_AUTH, json={"mode": "cache"})
    assert r.status_code == 200
    queues = {q for (n, q) in client.sent if n == "engine.release"}
    assert queues == {f"{f}-gpu{g}" for f in fams for g in (0, 1)}


def test_release_all_requires_auth(client):
    assert client.post("/engines/release-all", json={"mode": "cache"}).status_code == 401


def test_release_all_bad_mode_422(client):
    assert client.post("/engines/release-all", headers=_AUTH, json={"mode": "x"}).status_code == 422
