"""Kullanıcı + oturum (session) veri katmanı — ev/LAN çok-kullanıcı auth.

Tablolar `gateway.db.init_db()` içinde ham SQL ile (idempotent) kurulur; ORM
modeli EKLENMEZ (projects/variations ORM'ine dokunmadan yalın SQL üzerinden
CRUD). Parola hash'i passlib+bcrypt; oturum token'ı opak `secrets.token_urlsafe`.

`verify_token` (auth.py) önce APP_TOKEN'ı (makine token'ı) kontrol eder; eşleşmezse
buradaki `lookup_session_user` ile süresi geçmemiş oturumu arar.
"""
from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from passlib.context import CryptContext
from sqlalchemy import text
from sqlalchemy.orm import Session

# 30 gün: ev/LAN kullanımında sık login istemeyecek kadar uzun.
SESSION_TTL_DAYS = 30

# bcrypt tek şema; passlib truncation/round yönetimini üstlenir.
_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


@dataclass(frozen=True)
class UserRow:
    id: str
    username: str
    is_admin: bool
    created_at: str


# --- Parola --------------------------------------------------------------------
def hash_password(password: str) -> str:
    return _pwd_context.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return _pwd_context.verify(password, password_hash)
    except Exception:  # noqa: BLE001 — bozuk/boş hash → doğrulanmadı
        return False


# --- Kullanıcı CRUD ------------------------------------------------------------
def count_users(session: Session) -> int:
    return int(session.execute(text("SELECT COUNT(*) FROM users")).scalar_one())


def _row_to_user(row) -> UserRow | None:
    if row is None:
        return None
    return UserRow(
        id=row.id,
        username=row.username,
        is_admin=bool(row.is_admin),
        created_at=str(row.created_at),
    )


def get_user_by_username(session: Session, username: str):
    """Ham satır döner (password_hash dahil) — login doğrulaması için."""
    return session.execute(
        text("SELECT id, username, password_hash, is_admin, created_at "
             "FROM users WHERE username = :u"),
        {"u": username},
    ).first()


def get_user_by_id(session: Session, user_id: str) -> UserRow | None:
    row = session.execute(
        text("SELECT id, username, is_admin, created_at FROM users WHERE id = :i"),
        {"i": user_id},
    ).first()
    return _row_to_user(row)


def list_users(session: Session) -> list[UserRow]:
    rows = session.execute(
        text("SELECT id, username, is_admin, created_at FROM users "
             "ORDER BY created_at ASC")
    ).all()
    return [_row_to_user(r) for r in rows]


def username_exists(session: Session, username: str) -> bool:
    return get_user_by_username(session, username) is not None


def create_user(session: Session, username: str, password: str,
                *, is_admin: bool) -> UserRow:
    """Kullanıcı ekle (commit ETMEZ — çağıran commit'ler)."""
    user_id = uuid4().hex
    session.execute(
        text("INSERT INTO users (id, username, password_hash, is_admin, created_at) "
             "VALUES (:i, :u, :h, :a, :c)"),
        {
            "i": user_id,
            "u": username,
            "h": hash_password(password),
            "a": 1 if is_admin else 0,
            "c": datetime.now(UTC).isoformat(),
        },
    )
    return UserRow(id=user_id, username=username, is_admin=is_admin,
                   created_at=datetime.now(UTC).isoformat())


def delete_user(session: Session, user_id: str) -> None:
    """Kullanıcıyı ve tüm oturumlarını sil (commit ETMEZ)."""
    session.execute(text("DELETE FROM sessions WHERE user_id = :i"), {"i": user_id})
    session.execute(text("DELETE FROM users WHERE id = :i"), {"i": user_id})


def set_password(session: Session, user_id: str, new_password: str) -> None:
    """Parolayı değiştir (commit ETMEZ)."""
    session.execute(
        text("UPDATE users SET password_hash = :h WHERE id = :i"),
        {"h": hash_password(new_password), "i": user_id},
    )


# --- Oturum (session) ----------------------------------------------------------
def create_session(session: Session, user_id: str,
                   *, ttl_days: int = SESSION_TTL_DAYS) -> str:
    """Yeni opak token üret + kaydet (commit ETMEZ). Token'ı döner."""
    token = secrets.token_urlsafe(32)
    expires = datetime.now(UTC) + timedelta(days=ttl_days)
    session.execute(
        text("INSERT INTO sessions (token, user_id, expires_at) "
             "VALUES (:t, :u, :e)"),
        {"t": token, "u": user_id, "e": expires.isoformat()},
    )
    return token


def _parse_dt(value) -> datetime | None:
    try:
        dt = datetime.fromisoformat(str(value))
    except (ValueError, TypeError):
        return None
    # Naive gelirse UTC varsay (tutarlı karşılaştırma için).
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt


def lookup_session_user(session: Session, token: str) -> str | None:
    """Token geçerli + süresi dolmamışsa user_id döner; aksi halde None."""
    row = session.execute(
        text("SELECT user_id, expires_at FROM sessions WHERE token = :t"),
        {"t": token},
    ).first()
    if row is None:
        return None
    expires = _parse_dt(row.expires_at)
    if expires is None or expires <= datetime.now(UTC):
        return None
    return row.user_id


def delete_session(session: Session, token: str) -> None:
    session.execute(text("DELETE FROM sessions WHERE token = :t"), {"t": token})
