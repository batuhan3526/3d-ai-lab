"""DB katmanı testleri (geçici SQLite dosyası)."""
import pytest


@pytest.fixture
def fresh_db(tmp_path, monkeypatch):
    db_path = str(tmp_path / "test.db").replace("\\", "/")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    monkeypatch.setenv("APP_TOKEN", "test-token-bootstrap")
    from common.config import get_settings
    get_settings.cache_clear()
    from gateway import db
    db.reset_engine()
    db.init_db()
    yield db
    db.reset_engine()
    get_settings.cache_clear()


def test_init_db_creates_projects_table(fresh_db):
    from sqlalchemy import inspect
    engine = fresh_db.get_engine()
    assert "projects" in inspect(engine).get_table_names()


def test_session_insert_and_query(fresh_db):
    from gateway.models.orm import Project
    Session = fresh_db.get_sessionmaker()
    with Session() as s:
        p = Project(name="Deneme", garment_type="tshirt", template_id="tshirt-01",
                    customizations={"color": "#ff0000", "decals": []})
        s.add(p)
        s.commit()
        pid = p.id
    with Session() as s:
        loaded = s.get(Project, pid)
        assert loaded.name == "Deneme"
        assert loaded.user_id == "default"
        assert loaded.customizations["color"] == "#ff0000"
        assert loaded.created_at is not None


def test_project_has_mesh_path_default_none(tmp_path, monkeypatch):
    db_path = str(tmp_path / "t.db").replace("\\", "/")
    monkeypatch.setenv("APP_TOKEN", "x")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    from common.config import get_settings
    get_settings.cache_clear()
    from gateway import db
    db.reset_engine()
    db.init_db()
    from gateway.db import get_sessionmaker
    from gateway.models.orm import Project
    with get_sessionmaker()() as s:
        p = Project(user_id="default", name="x", garment_type="tshirt", template_id="t1",
                    customizations={"color": "#fff", "decals": []})
        s.add(p)
        s.flush()
        assert p.mesh_path is None
    db.reset_engine()


def test_variation_and_favorite_tables_created(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{str(tmp_path / 'v.db').replace(chr(92), '/')}")
    from common.config import get_settings
    get_settings.cache_clear()
    from gateway import db as gdb
    gdb.reset_engine()
    gdb.init_db()
    from sqlalchemy import inspect
    names = set(inspect(gdb.get_engine()).get_table_names())
    assert {"variations", "favorites"} <= names


def test_versions_table_created(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{str(tmp_path / 'ver.db').replace(chr(92), '/')}")
    from common.config import get_settings
    get_settings.cache_clear()
    from gateway import db as gdb
    gdb.reset_engine(); gdb.init_db()
    from sqlalchemy import inspect
    assert "versions" in set(inspect(gdb.get_engine()).get_table_names())


def test_sqlite_pragmas_wal_and_busy_timeout(fresh_db):
    """Engine connect event WAL + busy_timeout uygular (eşzamanlı yazım güvenliği)."""
    from sqlalchemy import text
    with fresh_db.get_engine().connect() as conn:
        journal = conn.execute(text("PRAGMA journal_mode")).scalar()
        busy = conn.execute(text("PRAGMA busy_timeout")).scalar()
    assert str(journal).lower() == "wal"
    assert int(busy) == 5000


def test_db_write_set_mesh_path(tmp_path, monkeypatch):
    """common.db_write.set_mesh_path projects.mesh_path'i WAL ile yazar."""
    db_path = str(tmp_path / "w.db").replace("\\", "/")
    monkeypatch.setenv("APP_TOKEN", "x")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    from common.config import get_settings
    get_settings.cache_clear()
    from gateway import db as gdb
    gdb.reset_engine()
    gdb.init_db()
    from gateway.db import get_sessionmaker
    from gateway.models.orm import Project
    with get_sessionmaker()() as s:
        p = Project(user_id="default", name="x", garment_type="tshirt", template_id="t1",
                    customizations={"color": "#fff", "decals": []})
        s.add(p)
        s.commit()
        pid = p.id

    from common.db_write import set_mesh_path
    set_mesh_path(f"sqlite:///{db_path}", pid, "/data/projects/default/x/mesh.glb")

    gdb.reset_engine()
    with get_sessionmaker()() as s:
        loaded = s.get(Project, pid)
        assert loaded.mesh_path == "/data/projects/default/x/mesh.glb"
    # helper WAL bıraktı mı
    import sqlite3
    conn = sqlite3.connect(db_path)
    try:
        assert str(conn.execute("PRAGMA journal_mode").fetchone()[0]).lower() == "wal"
    finally:
        conn.close()
    gdb.reset_engine()
