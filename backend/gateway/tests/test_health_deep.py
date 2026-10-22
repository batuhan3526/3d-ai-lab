"""GET /health/deep testleri — redis/db/celery inspect monkeypatch'li 3 senaryo."""
import pytest
from fastapi.testclient import TestClient

_AUTH = {"Authorization": "Bearer test-token-bootstrap"}


class _FakeConn:
    def __init__(self, *, fail: bool):
        self._fail = fail

    def ensure_connection(self, max_retries=None, timeout=None):
        if self._fail:
            raise ConnectionError("redis down")

    def release(self):
        pass


class _FakeInspect:
    def __init__(self, replies):
        self._replies = replies

    def active_queues(self):
        return self._replies


@pytest.fixture
def client(tmp_path, monkeypatch):
    # Gerçek yazılabilir bir SQLite → db write-probe gerçekten koşar.
    db_path = str(tmp_path / "deep.db").replace("\\", "/")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    monkeypatch.setenv("APP_TOKEN", "test-token-bootstrap")
    from common.config import get_settings
    get_settings.cache_clear()
    from gateway import db
    db.reset_engine()
    db.init_db()
    from gateway.main import app
    c = TestClient(app)
    yield c
    db.reset_engine()
    get_settings.cache_clear()


def _patch_celery(monkeypatch, *, redis_ok: bool, active_queues):
    from common import celery_app as ca

    monkeypatch.setattr(
        ca.celery_app, "connection", lambda: _FakeConn(fail=not redis_ok)
    )
    monkeypatch.setattr(
        ca.celery_app.control, "inspect",
        lambda timeout=None: _FakeInspect(active_queues),
    )


def _expected(client):
    r = client.get("/health/deep", headers=_AUTH)
    return r


def test_requires_auth(client):
    assert client.get("/health/deep").status_code == 401


def test_all_ok(client, monkeypatch):
    from gateway.routes.health_deep import expected_queues
    # Tüm beklenen kuyrukları tek bir node tüketiyor → hepsi ok.
    exp = expected_queues()
    assert exp, "beklenen kuyruk listesi boş olmamalı"
    replies = {"celery@host": [{"name": q} for q in exp]}
    _patch_celery(monkeypatch, redis_ok=True, active_queues=replies)

    r = client.get("/health/deep", headers=_AUTH)
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["redis"] is True
    assert body["db"] is True
    assert set(body["workers"]) == set(exp)
    assert all(v == "ok" for v in body["workers"].values())


def test_worker_missing_is_degraded(client, monkeypatch):
    from gateway.routes.health_deep import expected_queues
    exp = expected_queues()
    # İlki hariç hepsi tüketiliyor → biri "missing", status degraded, HTTP 200.
    served = exp[1:]
    replies = {"celery@host": [{"name": q} for q in served]}
    _patch_celery(monkeypatch, redis_ok=True, active_queues=replies)

    r = client.get("/health/deep", headers=_AUTH)
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "degraded"
    assert body["redis"] is True
    assert body["workers"][exp[0]] == "missing"
    assert all(body["workers"][q] == "ok" for q in served)


def test_redis_down_is_degraded_not_503(client, monkeypatch):
    # Redis down → inspect çağrılmaz, tüm worker'lar missing, status degraded, 200.
    _patch_celery(monkeypatch, redis_ok=False, active_queues=None)

    r = client.get("/health/deep", headers=_AUTH)
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "degraded"
    assert body["redis"] is False
    assert body["db"] is True
    assert all(v == "missing" for v in body["workers"].values())


def test_expected_queues_only_available_families(monkeypatch):
    """Beklenen kuyruklar yalnız available motor ailelerinden türetilmeli."""
    monkeypatch.setenv("APP_TOKEN", "test-token-bootstrap")
    from common.config import get_settings
    get_settings.cache_clear()
    from gateway.routes.health_deep import expected_queues
    from common.engines.registry import default_gpu, engine_family, list_specs

    exp = set(expected_queues())
    dgpu = default_gpu()
    avail = [s for s in list_specs() if s.get("available", True)]
    unavail_only = {
        engine_family(s["id"]) for s in list_specs() if not s.get("available", True)
    } - {engine_family(s["id"]) for s in avail}
    # available motor: GPU'lu ise YALNIZ default-gpu kuyruğu beklenir (görünür kümenin
    # tamamı değil — 2-GPU host'ta workers tek GPU'da koşabilir); CPU motoru (gpus==[]) -cpu.
    for s in avail:
        fam = engine_family(s["id"])
        if s.get("gpus") == []:
            assert f"{fam}-cpu" in exp
            assert f"{fam}-gpu{dgpu}" not in exp
        else:
            assert f"{fam}-gpu{dgpu}" in exp
    # yalnız-unavailable aile (ör. worldtracing/meshflow) HİÇ görünmemeli
    for fam in unavail_only:
        assert not any(q.startswith(f"{fam}-") for q in exp)
