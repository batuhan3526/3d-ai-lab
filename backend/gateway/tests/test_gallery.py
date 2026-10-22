"""Galeri paylaşımı testleri — POST /projects/{id}/share + GET /projects/gallery.

Hermetik: her test tmp_path SQLite kullanır (gerçek data/ dizinine yazmaz),
env monkeypatch + get_settings.cache_clear + db.reset_engine ile izole edilir
(test_projects.py / test_auth.py deseni).
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

AUTH = {"Authorization": "Bearer test-token-bootstrap"}


@pytest.fixture
def client(tmp_path, monkeypatch):
    db_path = str(tmp_path / "gallery.db").replace("\\", "/")
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
    }, headers=AUTH).json()["id"]


# --- auth ----------------------------------------------------------------------
def test_gallery_requires_auth(client):
    assert client.get("/projects/gallery").status_code == 401


def test_share_requires_auth(client):
    pid = _make(client)
    assert client.post(f"/projects/{pid}/share").status_code == 401


# --- gallery listesi -----------------------------------------------------------
def test_gallery_empty_initially(client):
    r = client.get("/projects/gallery", headers=AUTH)
    assert r.status_code == 200
    assert r.json() == []


def test_share_toggle_adds_and_removes_from_gallery(client):
    pid = _make(client, "Paylaşılan")
    # İlk toggle → paylaş.
    r = client.post(f"/projects/{pid}/share", headers=AUTH)
    assert r.status_code == 200
    assert r.json() == {"id": pid, "shared": True}

    items = client.get("/projects/gallery", headers=AUTH).json()
    assert len(items) == 1
    it = items[0]
    assert it["id"] == pid
    assert it["name"] == "Paylaşılan"
    assert it["thumb"] == f"/projects/{pid}/thumbnail"
    assert it["owner_username"] == "default"  # projects.user_id varsayılanı
    assert it["shared_at"]  # updated_at ile temsil, boş değil

    # İkinci toggle → paylaşımı kaldır.
    r2 = client.post(f"/projects/{pid}/share", headers=AUTH)
    assert r2.json() == {"id": pid, "shared": False}
    assert client.get("/projects/gallery", headers=AUTH).json() == []


def test_only_shared_projects_listed(client):
    shared = _make(client, "Görünür")
    _make(client, "Gizli")
    client.post(f"/projects/{shared}/share", headers=AUTH)
    items = client.get("/projects/gallery", headers=AUTH).json()
    assert [it["id"] for it in items] == [shared]


def test_owner_username_resolves_from_users(client):
    """owner_username, projects.user_id → users.id JOIN'inden gelir."""
    client.post("/auth/setup", json={"username": "alice", "password": "pw12345"})
    pid = _make(client, "Alice'in tasarımı")
    client.post(f"/projects/{pid}/share", headers=AUTH)  # _get_or_404 'default' bekler
    # Paylaşım sonrası projeyi gerçek kullanıcıya bağla → JOIN username'i çözer.
    from gateway.db import get_sessionmaker
    with get_sessionmaker()() as s:
        uid = s.execute(text("SELECT id FROM users WHERE username = 'alice'")).scalar_one()
        s.execute(text("UPDATE projects SET user_id = :u WHERE id = :i"),
                  {"u": uid, "i": pid})
        s.commit()
    items = client.get("/projects/gallery", headers=AUTH).json()
    assert len(items) == 1
    assert items[0]["owner_username"] == "alice"


def test_share_missing_project_404(client):
    assert client.post("/projects/does-not-exist/share", headers=AUTH).status_code == 404
