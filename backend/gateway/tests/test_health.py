"""Health endpoint tests."""
import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    from gateway.main import app

    return TestClient(app)


def test_health_returns_200_without_auth(client):
    """/health is intentionally public — for load balancers, monitoring."""
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert "version" in body
    assert "timestamp" in body


def test_health_response_shape(client):
    response = client.get("/health")
    body = response.json()
    assert set(body.keys()) >= {"status", "version", "timestamp"}


def test_root_redirects_or_responds(client):
    """Root path should not 404 — gateway should respond."""
    response = client.get("/")
    assert response.status_code in (200, 307, 308)
