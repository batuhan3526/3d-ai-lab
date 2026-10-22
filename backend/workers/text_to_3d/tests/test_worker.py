import fakeredis
import pytest


@pytest.fixture
def env(tmp_path, monkeypatch):
    # template GLB hazırla
    tdir = tmp_path / "templates" / "tshirt"
    tdir.mkdir(parents=True)
    glb = tdir / "tshirt-01.glb"
    import trimesh
    trimesh.creation.box([1, 1, 1]).export(glb, file_type="glb")
    pdir = tmp_path / "projects"
    pdir.mkdir()
    db_path = str(tmp_path / "t.db").replace("\\", "/")
    monkeypatch.setenv("APP_TOKEN", "x")
    monkeypatch.setenv("TEMPLATES_DIR", str(tmp_path / "templates").replace("\\", "/"))
    monkeypatch.setenv("PROJECTS_DIR", str(pdir).replace("\\", "/"))
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    from common.config import get_settings
    get_settings.cache_clear()
    from gateway import db
    db.reset_engine()
    db.init_db()
    from gateway.db import get_sessionmaker
    from gateway.models.orm import Project
    with get_sessionmaker()() as s:
        p = Project(user_id="default", name="x", garment_type="tshirt",
                    template_id="generated", customizations={"color": "#ccc", "decals": []})
        s.add(p)
        s.commit()
        s.refresh(p)
        pid = p.id
    fake = fakeredis.FakeStrictRedis(decode_responses=True)
    import text_to_3d.worker as w
    from common.jobs import JobStore
    store = JobStore(fake)
    store.create("j1", {"project_id": pid})
    monkeypatch.setattr(w, "_job_store", lambda: store)
    monkeypatch.setattr(w, "_stage_delay", 0)
    return w, store, pid, pdir


def test_worker_produces_mesh_and_succeeds(env):
    w, store, pid, pdir = env
    w.generate_text_to_3d.run(job_id="j1", project_id=pid,
                              prompt="red blouse", garment_type="tshirt",
                              quality="balanced", prompt_enhance=False)
    assert (pdir / "default" / pid / "mesh.glb").exists()
    assert store.get("j1")["state"] == "SUCCESS"
    assert store.get("j1")["project_id"] == pid
