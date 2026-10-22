"""Proje sahipliği (attribution) testleri — projects.user_id oturum kullanıcısına
göre atanır, makine token'ında 'default'e düşer; liste/galeri owner_username taşır.

Hermetik: her test tmp_path SQLite kullanır (gerçek data/ dizinine yazmaz),
env monkeypatch + get_settings.cache_clear + db.reset_engine ile izole edilir
(test_gallery.py / test_auth.py deseni — DATABASE_URL/APP_TOKEN app'e böyle geçer).
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

APP = {"Authorization": "Bearer test-token-bootstrap"}


@pytest.fixture
def client(tmp_path, monkeypatch):
    db_path = str(tmp_path / "ownership.db").replace("\\", "/")
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


def _bearer(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _make(client, headers, name="Tasarım A"):
    return client.post("/projects", json={
        "name": name, "garment_type": "tshirt", "template_id": "tshirt-01",
        "customizations": {"color": "#ff0000", "decals": []},
    }, headers=headers)


def _setup_user(client, username="alice", password="pw12345"):
    """İlk admin'i oluştur → oturum token'ı + user_id döner."""
    r = client.post("/auth/setup", json={"username": username, "password": password})
    assert r.status_code == 201, r.text
    token = r.json()["token"]
    from gateway.db import get_sessionmaker
    with get_sessionmaker()() as s:
        uid = s.execute(
            text("SELECT id FROM users WHERE username = :u"), {"u": username}
        ).scalar_one()
    return token, uid


def _db_user_id(project_id: str) -> str:
    from gateway.db import get_sessionmaker
    with get_sessionmaker()() as s:
        return s.execute(
            text("SELECT user_id FROM projects WHERE id = :i"), {"i": project_id}
        ).scalar_one()


# --- create: sahiplik atama ----------------------------------------------------
def test_machine_token_owner_defaults(client):
    """APP_TOKEN (makine token'ı) → request.state.user_id None → user_id 'default'."""
    resp = _make(client, APP)
    assert resp.status_code == 201
    pid = resp.json()["id"]
    assert resp.json()["user_id"] == "default"
    assert _db_user_id(pid) == "default"


def test_session_user_owner_is_set(client):
    """Oturum kullanıcısı oluşturursa → user_id o kullanıcının id'sine ayarlanır."""
    token, uid = _setup_user(client)
    resp = _make(client, _bearer(token), "Alice'in tasarımı")
    assert resp.status_code == 201
    pid = resp.json()["id"]
    assert resp.json()["user_id"] == uid
    assert uid != "default"
    assert _db_user_id(pid) == uid


# --- list: owner_username ------------------------------------------------------
def test_list_includes_owner_username_default(client):
    _make(client, APP)
    items = client.get("/projects", headers=APP).json()
    assert len(items) == 1
    # users tablosunda 'default' kaydı yok → ham user_id'ye düşer.
    assert items[0]["owner_username"] == "default"
    assert items[0]["user_id"] == "default"


def test_list_includes_owner_username_session_user(client):
    """Oturum kullanıcısının projesi listede gerçek username ile görünür ve
    makine token'ıyla da listelenir (tek-ev: sahibe göre filtreleme yok)."""
    token, uid = _setup_user(client)
    _make(client, _bearer(token), "Görünür")
    # Makine token'ı da tüm projeleri görür (single-household).
    items = client.get("/projects", headers=APP).json()
    assert len(items) == 1
    assert items[0]["user_id"] == uid
    assert items[0]["owner_username"] == "alice"


# --- duplicate: kopyanın sahibi çoğaltmayı yapan ------------------------------
def test_duplicate_sets_owner_to_requesting_user(client):
    """Makine token'ıyla oluşturulan projeyi oturum kullanıcısı çoğaltırsa,
    kopyanın sahibi çoğaltmayı yapan oturum kullanıcısı olur."""
    token, uid = _setup_user(client)
    pid = _make(client, APP, "Kaynak").json()["id"]
    dup = client.post(f"/projects/{pid}/duplicate", headers=_bearer(token))
    assert dup.status_code == 201
    new_id = dup.json()["id"]
    assert dup.json()["user_id"] == uid
    assert _db_user_id(new_id) == uid
    # Kaynak hâlâ 'default' sahipli.
    assert _db_user_id(pid) == "default"


# --- gallery: gerçek sahip görünür --------------------------------------------
def test_gallery_shows_real_owner_for_session_project(client):
    """Oturum kullanıcısının paylaştığı proje galeride gerçek username ile çıkar."""
    token, _uid = _setup_user(client)
    pid = _make(client, _bearer(token), "Paylaşılan").json()["id"]
    # Paylaşım (share) tek-ev erişimiyle çalışır (owner filtresi yok).
    assert client.post(f"/projects/{pid}/share", headers=_bearer(token)).status_code == 200
    items = client.get("/projects/gallery", headers=APP).json()
    assert len(items) == 1
    assert items[0]["id"] == pid
    assert items[0]["owner_username"] == "alice"


# --- tek-ev erişimi: oturum kullanıcısının projesi APP ile de açılır ----------
def test_session_project_accessible_via_get(client):
    """Oturum kullanıcısı proje oluşturur → makine token'ıyla GET edilebilir
    (single-household: _get_or_404 sahibe göre filtrelemez)."""
    token, _uid = _setup_user(client)
    pid = _make(client, _bearer(token)).json()["id"]
    assert client.get(f"/projects/{pid}", headers=APP).status_code == 200
    # Sahibi de erişebilir.
    assert client.get(f"/projects/{pid}", headers=_bearer(token)).status_code == 200
