import fakeredis
import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect


@pytest.fixture
def setup(monkeypatch):
    monkeypatch.setenv("APP_TOKEN", "test-token-bootstrap")
    from common.config import get_settings
    get_settings.cache_clear()
    fake = fakeredis.FakeStrictRedis(decode_responses=True)
    import gateway.routes.ws as ws
    from common.jobs import JobStore
    store = JobStore(fake)
    store.create("j1", {"project_id": "p1"})
    monkeypatch.setattr(ws, "_redis", lambda: fake)
    monkeypatch.setattr(ws, "_job_store", lambda: store)
    from gateway.main import app
    return TestClient(app), store


def test_ws_rejects_bad_token(setup):
    client, _ = setup
    with pytest.raises((WebSocketDisconnect, RuntimeError)):
        with client.websocket_connect("/ws/jobs/j1?token=wrong"):
            pass


def test_ws_sends_initial_then_progress(setup):
    client, store = setup
    with client.websocket_connect("/ws/jobs/j1?token=test-token-bootstrap") as ws:
        first = ws.receive_json()
        assert first["state"] in ("SUBMITTED", "PROGRESS")
        store.set_progress("j1", "shape", 40)
        msg = ws.receive_json()
        assert msg["stage"] == "shape" and msg["percent"] == 40
