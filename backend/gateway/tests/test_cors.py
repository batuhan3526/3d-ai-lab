"""CORS yapılandırma testleri.

Wildcard "*" + allow_credentials=True tarayıcılarca reddedilen geçersiz bir
kombinasyondu; origin'ler artık açık bir listeden okunur (varsayılan: localhost).
"""
import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    from gateway.main import app

    return TestClient(app)


def test_allowed_origin_is_echoed_on_preflight(client):
    resp = client.options(
        "/health",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert resp.headers["access-control-allow-origin"] == "http://localhost:3000"


def test_disallowed_origin_is_not_echoed(client):
    resp = client.options(
        "/health",
        headers={
            "Origin": "http://evil.example",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert resp.headers.get("access-control-allow-origin") != "http://evil.example"


def test_no_wildcard_with_credentials(client):
    """Geçersiz kombo regresyon koruması: '*' origin + credentials birlikte gelmez."""
    resp = client.get("/health", headers={"Origin": "http://localhost:3000"})
    assert resp.headers.get("access-control-allow-origin") != "*"
    assert "access-control-allow-credentials" not in resp.headers


def test_cors_origins_list_parsing():
    from common.config import Settings

    s = Settings(app_token="x", cors_origins="http://a:3000, http://b:3000 ,")
    assert s.cors_origins_list == ["http://a:3000", "http://b:3000"]
