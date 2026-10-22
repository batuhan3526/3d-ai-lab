def test_celery_app_uses_redis_url(monkeypatch):
    monkeypatch.setenv("APP_TOKEN", "x")
    monkeypatch.setenv("REDIS_URL", "redis://127.0.0.1:6379/2")
    from common.config import get_settings
    get_settings.cache_clear()
    from common.celery_app import make_celery
    app = make_celery()
    assert app.conf.broker_url == "redis://127.0.0.1:6379/2"
    assert app.conf.result_backend == "redis://127.0.0.1:6379/2"
