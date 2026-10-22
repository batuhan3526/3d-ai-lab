"""DB engine/session yönetimi.

Engine settings.database_url'den lazy kurulur; testler reset_engine() ile
sıfırlayıp DATABASE_URL'i geçici dosyaya yönlendirebilir (config pattern'iyle uyumlu).
"""
from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

from common.config import get_settings
from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from gateway.models.orm import Base

_engine: Engine | None = None
_sessionmaker: sessionmaker[Session] | None = None


def _apply_sqlite_pragmas(dbapi_conn, _connection_record) -> None:
    """Her yeni SQLite bağlantısında WAL + busy_timeout ayarla.

    9 worker + gateway aynı SQLite dosyasına yazıyor. WAL okuyucu/yazıcı
    çakışmasını azaltır; busy_timeout=5000 kilit beklerken 5 sn geri çekilir
    (aksi halde "database is locked" ile anında patlar).
    """
    cur = dbapi_conn.cursor()
    try:
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA busy_timeout=5000")
    finally:
        cur.close()


def get_engine() -> Engine:
    global _engine
    if _engine is None:
        url = get_settings().database_url
        connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
        _engine = create_engine(url, connect_args=connect_args, future=True)
        if url.startswith("sqlite"):
            event.listen(_engine, "connect", _apply_sqlite_pragmas)
    return _engine


def get_sessionmaker() -> sessionmaker[Session]:
    global _sessionmaker
    if _sessionmaker is None:
        _sessionmaker = sessionmaker(bind=get_engine(), expire_on_commit=False, future=True)
    return _sessionmaker


def init_db() -> None:
    """Tabloları oluştur (idempotent)."""
    # SQLite dosya yolu için klasörün var olduğundan emin ol (fresh clone'da data/ olmayabilir)
    url = get_settings().database_url
    prefix = "sqlite:///"
    if url.startswith(prefix):
        db_file = url[len(prefix):]
        if db_file and db_file != ":memory:":
            Path(db_file).parent.mkdir(parents=True, exist_ok=True)
    Base.metadata.create_all(get_engine())
    # Dev migration: create_all mevcut tablolara kolon eklemez; elle ALTER TABLE.
    from sqlalchemy import inspect, text
    insp = inspect(get_engine())
    cols = {c["name"] for c in insp.get_columns("projects")}
    if "mesh_path" not in cols:
        with get_engine().begin() as conn:
            conn.execute(text("ALTER TABLE projects ADD COLUMN mesh_path VARCHAR"))
    if "engine_id" not in cols:
        with get_engine().begin() as conn:
            conn.execute(text("ALTER TABLE projects ADD COLUMN engine_id VARCHAR"))
    if "animation_path" not in cols:
        with get_engine().begin() as conn:
            conn.execute(text("ALTER TABLE projects ADD COLUMN animation_path VARCHAR"))
    # Auth (ev/LAN çok-kullanıcı): projects.shared galeri paylaşımı için.
    # projects.user_id ZATEN ORM'de var (default 'default'); ekstra ALTER gerekmez.
    if "shared" not in cols:
        with get_engine().begin() as conn:
            conn.execute(text("ALTER TABLE projects ADD COLUMN shared INTEGER DEFAULT 0"))

    # users/sessions tabloları — ORM'e dokunmadan ham SQL (idempotent).
    # bkz. gateway/users.py (yalın SQL CRUD katmanı).
    with get_engine().begin() as conn:
        conn.execute(text(
            "CREATE TABLE IF NOT EXISTS users ("
            "id TEXT PRIMARY KEY, "
            "username TEXT UNIQUE NOT NULL, "
            "password_hash TEXT NOT NULL, "
            "is_admin INTEGER NOT NULL DEFAULT 0, "
            "created_at TEXT NOT NULL)"
        ))
        conn.execute(text(
            "CREATE TABLE IF NOT EXISTS sessions ("
            "token TEXT PRIMARY KEY, "
            "user_id TEXT NOT NULL, "
            "expires_at TEXT NOT NULL)"
        ))


def reset_engine() -> None:
    """Test izolasyonu: engine/sessionmaker'ı sıfırla."""
    global _engine, _sessionmaker
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _sessionmaker = None


def get_db() -> Iterator[Session]:
    """FastAPI dependency: request başına bir Session."""
    Session = get_sessionmaker()
    with Session() as session:
        yield session
