"""Auth testleri — verify_token (APP_TOKEN + oturum) ve /auth/* akışı.

Hermetik: her test tmp_path SQLite kullanır (gerçek data/ dizinine yazmaz),
env monkeypatch + get_settings.cache_clear + db.reset_engine ile izole edilir.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

_APP = {"Authorization": "Bearer test-token-bootstrap"}


@pytest.fixture
def client(tmp_path, monkeypatch):
    db_path = str(tmp_path / "auth.db").replace("\\", "/")
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


def _bearer(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


# --- verify_token (makine token'ı + header davranışı) --------------------------
def test_no_token_returns_401(client):
    r = client.get("/auth/me")
    assert r.status_code == 401
    assert r.json()["detail"] == "Missing or invalid token"


def test_wrong_token_returns_401(client):
    r = client.get("/auth/me", headers=_bearer("wrong-token"))
    assert r.status_code == 401


def test_token_without_bearer_prefix_returns_401(client):
    r = client.get("/auth/me", headers={"Authorization": "test-token-bootstrap"})
    assert r.status_code == 401


def test_app_token_still_works_as_machine(client):
    """APP_TOKEN her zaman geçerli (worker/e2e kırılmaz) → makine bağlamı."""
    r = client.get("/auth/me", headers=_APP)
    assert r.status_code == 200
    body = r.json()
    assert body["machine"] is True
    assert body["is_admin"] is True
    assert body["username"] is None


# --- setup (ilk admin) ---------------------------------------------------------
def test_needs_setup_true_initially(client):
    r = client.get("/auth/needs-setup")
    assert r.status_code == 200
    assert r.json() == {"needs_setup": True}


def test_setup_creates_admin_and_returns_token(client):
    r = client.post("/auth/setup", json={"username": "alice", "password": "pw12345"})
    assert r.status_code == 201
    body = r.json()
    assert body["username"] == "alice"
    assert body["is_admin"] is True
    assert body["token"]
    # Dönen oturum token'ı yetkilendirir.
    me = client.get("/auth/me", headers=_bearer(body["token"]))
    assert me.status_code == 200
    assert me.json()["username"] == "alice"
    assert me.json()["machine"] is False


def test_setup_only_once(client):
    client.post("/auth/setup", json={"username": "alice", "password": "pw12345"})
    r = client.post("/auth/setup", json={"username": "iki", "password": "pw12345"})
    assert r.status_code == 409


def test_needs_setup_false_after_setup(client):
    client.post("/auth/setup", json={"username": "alice", "password": "pw12345"})
    assert client.get("/auth/needs-setup").json() == {"needs_setup": False}


# --- login ---------------------------------------------------------------------
def test_login_wrong_password_401(client):
    client.post("/auth/setup", json={"username": "alice", "password": "pw12345"})
    r = client.post("/auth/login", json={"username": "alice", "password": "yanlis"})
    assert r.status_code == 401


def test_login_unknown_user_401(client):
    client.post("/auth/setup", json={"username": "alice", "password": "pw12345"})
    r = client.post("/auth/login", json={"username": "yok", "password": "pw12345"})
    assert r.status_code == 401


def test_login_success_returns_token(client):
    client.post("/auth/setup", json={"username": "alice", "password": "pw12345"})
    r = client.post("/auth/login", json={"username": "alice", "password": "pw12345"})
    assert r.status_code == 200
    body = r.json()
    assert body["username"] == "alice"
    assert body["is_admin"] is True
    assert client.get("/auth/me", headers=_bearer(body["token"])).status_code == 200


# --- oturum süresi -------------------------------------------------------------
def test_expired_session_401(client):
    setup = client.post(
        "/auth/setup", json={"username": "alice", "password": "pw12345"}
    ).json()
    # Token'ın süresini geçmişe çek → 401.
    from gateway.db import get_sessionmaker
    past = (datetime.now(UTC) - timedelta(seconds=1)).isoformat()
    with get_sessionmaker()() as s:
        s.execute(
            text("UPDATE sessions SET expires_at = :e WHERE token = :t"),
            {"e": past, "t": setup["token"]},
        )
        s.commit()
    assert client.get("/auth/me", headers=_bearer(setup["token"])).status_code == 401


# --- admin CRUD ----------------------------------------------------------------
def test_admin_create_and_list_users(client):
    admin = client.post(
        "/auth/setup", json={"username": "alice", "password": "pw12345"}
    ).json()
    h = _bearer(admin["token"])
    r = client.post("/auth/users", headers=h,
                    json={"username": "bob", "password": "pw67890"})
    assert r.status_code == 201
    assert r.json()["is_admin"] is False
    users = client.get("/auth/users", headers=h).json()
    assert {u["username"] for u in users} == {"alice", "bob"}


def test_duplicate_username_409(client):
    admin = client.post(
        "/auth/setup", json={"username": "alice", "password": "pw12345"}
    ).json()
    h = _bearer(admin["token"])
    client.post("/auth/users", headers=h,
                json={"username": "bob", "password": "pw67890"})
    r = client.post("/auth/users", headers=h,
                    json={"username": "bob", "password": "baska"})
    assert r.status_code == 409


def test_non_admin_cannot_create_user(client):
    admin = client.post(
        "/auth/setup", json={"username": "alice", "password": "pw12345"}
    ).json()
    client.post("/auth/users", headers=_bearer(admin["token"]),
                json={"username": "bob", "password": "pw67890"})
    tok = client.post(
        "/auth/login", json={"username": "bob", "password": "pw67890"}
    ).json()["token"]
    r = client.post("/auth/users", headers=_bearer(tok),
                    json={"username": "uc", "password": "pw"})
    assert r.status_code == 403


def test_admin_delete_user(client):
    admin = client.post(
        "/auth/setup", json={"username": "alice", "password": "pw12345"}
    ).json()
    h = _bearer(admin["token"])
    uid = client.post("/auth/users", headers=h,
                      json={"username": "bob", "password": "pw67890"}).json()["id"]
    assert client.delete(f"/auth/users/{uid}", headers=h).status_code == 200
    assert {u["username"] for u in client.get("/auth/users", headers=h).json()} == {"alice"}


def test_delete_missing_user_404(client):
    admin = client.post(
        "/auth/setup", json={"username": "alice", "password": "pw12345"}
    ).json()
    r = client.delete("/auth/users/does-not-exist", headers=_bearer(admin["token"]))
    assert r.status_code == 404


def test_admin_cannot_delete_self(client):
    admin = client.post(
        "/auth/setup", json={"username": "alice", "password": "pw12345"}
    ).json()
    h = _bearer(admin["token"])
    my_id = client.get("/auth/me", headers=h).json()["id"]
    r = client.delete(f"/auth/users/{my_id}", headers=h)
    assert r.status_code == 400


# --- parola değişimi -----------------------------------------------------------
def test_change_password(client):
    admin = client.post(
        "/auth/setup", json={"username": "alice", "password": "pw12345"}
    ).json()
    h = _bearer(admin["token"])
    r = client.post("/auth/password", headers=h,
                    json={"old": "pw12345", "new": "yenipw99"})
    assert r.status_code == 200
    # Eski parola artık geçmez, yenisi geçer.
    assert client.post(
        "/auth/login", json={"username": "alice", "password": "pw12345"}
    ).status_code == 401
    assert client.post(
        "/auth/login", json={"username": "alice", "password": "yenipw99"}
    ).status_code == 200


def test_change_password_wrong_old_401(client):
    admin = client.post(
        "/auth/setup", json={"username": "alice", "password": "pw12345"}
    ).json()
    r = client.post("/auth/password", headers=_bearer(admin["token"]),
                    json={"old": "yanlis", "new": "yenipw99"})
    assert r.status_code == 401


def test_machine_token_cannot_change_password(client):
    r = client.post("/auth/password", headers=_APP,
                    json={"old": "x", "new": "y"})
    assert r.status_code == 400
