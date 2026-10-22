import pytest
from fastapi.testclient import TestClient


class _FakeResult:
    def __init__(self, value=None, raise_timeout=False):
        self._v = value
        self._t = raise_timeout

    def get(self, timeout=None):
        if self._t:
            from celery.exceptions import TimeoutError as CeleryTimeout
            raise CeleryTimeout("yok")
        return self._v


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("APP_TOKEN", "test-token-bootstrap")
    from common.config import get_settings
    get_settings.cache_clear()
    sent = []

    def fake_send_task(name, kwargs=None, queue=None, expires=None, **_):
        sent.append((name, queue, kwargs))
        # sadece trellis-gpu1 online
        if queue == "trellis-gpu1":
            return _FakeResult({"gpu": "1", "loaded": ["trellis-image"],
                                "reserved_mb": 9000, "allocated_mb": 8000})
        return _FakeResult(raise_timeout=True)

    from common import celery_app as ca
    monkeypatch.setattr(ca.celery_app, "send_task", fake_send_task)
    from gateway.main import app
    c = TestClient(app)
    c.sent = sent
    return c


_AUTH = {"Authorization": "Bearer test-token-bootstrap"}


def test_status_covers_all_families_and_gpus(client):
    from common.engines.registry import engine_family, list_specs
    # GPU'suz aileler (clothsim, bulut) VRAM paneline girmez.
    fams = sorted({engine_family(s["id"]) for s in list_specs() if s.get("gpus")})
    r = client.get("/engines/status", headers=_AUTH)
    assert r.status_code == 200
    data = r.json()
    # her aile x gpu0/1 (aileler registry'den dinamik: trellis/hunyuan/triposr...)
    keys = {(d["family"], d["gpu"]) for d in data}
    assert keys == {(f, g) for f in fams for g in (0, 1)}
    assert "trellis" in fams and "hunyuan" in fams
    online = [d for d in data if d["online"]]
    assert len(online) == 1
    assert online[0]["family"] == "trellis" and online[0]["gpu"] == 1
    assert online[0]["reserved_mb"] == 9000
    assert sum(1 for (n, q, _k) in client.sent if n == "engine.status") == len(fams) * 2


def test_status_requires_auth(client):
    assert client.get("/engines/status").status_code == 401


def test_release_routes_to_family_gpu_queue(client):
    r = client.post("/engines/release", headers=_AUTH,
                    json={"family": "hunyuan", "gpu": 0, "mode": "model"})
    assert r.status_code == 200
    assert any(n == "engine.release" and q == "hunyuan-gpu0" for (n, q, _k) in client.sent)


def test_release_invalid_family_rejected(client):
    r = client.post("/engines/release", headers=_AUTH,
                    json={"family": "nope", "gpu": 0, "mode": "model"})
    assert r.status_code == 422


def test_release_invalid_mode_rejected(client):
    r = client.post("/engines/release", headers=_AUTH,
                    json={"family": "trellis", "gpu": 1, "mode": "x"})
    assert r.status_code == 422
