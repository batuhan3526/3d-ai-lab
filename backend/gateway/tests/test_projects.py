"""Project CRUD + thumbnail testleri."""
import pytest
from fastapi.testclient import TestClient

AUTH = {"Authorization": "Bearer test-token-bootstrap"}


@pytest.fixture
def client(tmp_path, monkeypatch):
    db_path = str(tmp_path / "test.db").replace("\\", "/")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    monkeypatch.setenv("APP_TOKEN", "test-token-bootstrap")
    monkeypatch.setenv("PROJECTS_DIR", str(tmp_path / "projects").replace("\\", "/"))
    from common.config import get_settings
    get_settings.cache_clear()
    from gateway import db
    db.reset_engine()
    db.init_db()
    from gateway.main import app
    yield TestClient(app)
    db.reset_engine()
    get_settings.cache_clear()


def _make(client, name="Tasarım A"):
    return client.post("/projects", json={
        "name": name, "garment_type": "tshirt", "template_id": "tshirt-01",
        "customizations": {"color": "#ff0000", "decals": []},
    }, headers=AUTH)


def test_create_requires_auth(client):
    resp = client.post("/projects", json={"garment_type": "tshirt", "template_id": "tshirt-01"})
    assert resp.status_code == 401


def test_create_and_get(client):
    resp = _make(client)
    assert resp.status_code == 201
    pid = resp.json()["id"]
    assert resp.json()["customizations"]["color"] == "#ff0000"

    got = client.get(f"/projects/{pid}", headers=AUTH)
    assert got.status_code == 200
    assert got.json()["name"] == "Tasarım A"


def test_list_projects(client):
    _make(client, "A")
    _make(client, "B")
    resp = client.get("/projects", headers=AUTH)
    assert resp.status_code == 200
    assert len(resp.json()) == 2


def test_patch_updates_fields(client):
    pid = _make(client).json()["id"]
    resp = client.patch(f"/projects/{pid}", json={
        "name": "Yeni Ad", "customizations": {"color": "#00ff00", "decals": []},
    }, headers=AUTH)
    assert resp.status_code == 200
    assert resp.json()["name"] == "Yeni Ad"
    assert resp.json()["customizations"]["color"] == "#00ff00"


def test_delete_removes_project(client):
    pid = _make(client).json()["id"]
    assert client.delete(f"/projects/{pid}", headers=AUTH).status_code == 204
    assert client.get(f"/projects/{pid}", headers=AUTH).status_code == 404


def test_get_missing_returns_404(client):
    assert client.get("/projects/nope", headers=AUTH).status_code == 404


def test_thumbnail_upload_and_fetch(client):
    pid = _make(client).json()["id"]
    png = b"\x89PNG\r\n\x1a\n" + b"0" * 32
    up = client.put(f"/projects/{pid}/thumbnail", files={"file": ("t.png", png, "image/png")},
                    headers=AUTH)
    assert up.status_code == 200
    assert up.json()["thumbnail_path"]
    got = client.get(f"/projects/{pid}/thumbnail", headers=AUTH)
    assert got.status_code == 200
    assert got.content == png


def test_thumbnail_get_is_public(client):
    """Dashboard thumbnail'ı <img src> ile yükler (Authorization header yok),
    bu yüzden GET token'sız çalışmalı. Yazma (PUT) korumalı kalmalı."""
    pid = _make(client).json()["id"]
    png = b"\x89PNG\r\n\x1a\n" + b"0" * 32
    # Yazma auth ister
    assert client.put(f"/projects/{pid}/thumbnail",
                      files={"file": ("t.png", png, "image/png")}).status_code == 401
    client.put(f"/projects/{pid}/thumbnail", files={"file": ("t.png", png, "image/png")},
               headers=AUTH)
    # Okuma auth istemez (header yok)
    got = client.get(f"/projects/{pid}/thumbnail")
    assert got.status_code == 200
    assert got.content == png


def test_mesh_get_is_public_404_when_absent(client):
    pid = _make(client).json()["id"]
    assert client.get(f"/projects/{pid}/mesh").status_code == 404
