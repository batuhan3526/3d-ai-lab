import pytest
import trimesh
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("APP_TOKEN", "test-token-bootstrap")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{str(tmp_path / 't.db').replace(chr(92), '/')}")
    monkeypatch.setenv("PROJECTS_DIR", str(tmp_path / "projects").replace(chr(92), "/"))
    from common.config import get_settings
    get_settings.cache_clear()
    from gateway import db as gdb
    gdb.reset_engine()
    gdb.init_db()
    # bir proje + sahte mesh.glb (trimesh kutu)
    from gateway.db import get_sessionmaker
    from gateway.models.orm import Project
    with get_sessionmaker()() as s:
        p = Project(user_id="default", name="x", garment_type="boots",
                    template_id="generated", customizations={"color": "#ccc", "decals": []})
        s.add(p)
        s.commit()
        s.refresh(p)
        pid = p.id
    import pathlib
    mp = pathlib.Path(str(tmp_path / "projects" / "default" / pid))
    mp.mkdir(parents=True, exist_ok=True)
    trimesh.creation.box([1, 1, 1]).export(str(mp / "mesh.glb"))
    from gateway.main import app
    c = TestClient(app)
    c.pid = pid
    return c


def test_stl_export(client):
    r = client.get(f"/projects/{client.pid}/mesh.stl")
    assert r.status_code == 200
    assert r.content[:5] == b"solid" or len(r.content) > 80  # STL (ascii ya da binary)


def test_obj_export(client):
    r = client.get(f"/projects/{client.pid}/mesh.obj")
    assert r.status_code == 200
    assert b"v " in r.content  # OBJ vertex


def test_glb_passthrough(client):
    r = client.get(f"/projects/{client.pid}/mesh.glb")
    assert r.status_code == 200


def test_unknown_format_422(client):
    assert client.get(f"/projects/{client.pid}/mesh.xyz").status_code == 422
