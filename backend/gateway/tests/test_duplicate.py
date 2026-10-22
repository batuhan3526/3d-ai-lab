import pytest
from fastapi.testclient import TestClient

_AUTH = {"Authorization": "Bearer test-token-bootstrap"}


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("APP_TOKEN", "test-token-bootstrap")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{str(tmp_path / 't.db').replace(chr(92), '/')}")
    monkeypatch.setenv("PROJECTS_DIR", str(tmp_path / "projects"))
    from common.config import get_settings
    get_settings.cache_clear()
    from gateway import db as gdb
    gdb.reset_engine(); gdb.init_db()
    from gateway.db import get_sessionmaker
    from gateway.models.orm import Project
    with get_sessionmaker()() as s:
        p = Project(user_id="default", name="Tişört", garment_type="tshirt", template_id="generated",
                    customizations={"color": "#abc", "decals": [
                        {"id": "d1", "image": "/api/projects/SRCID/decals/x.png",
                         "position": [0, 0, 0], "rotation": [0, 0, 0], "scale": 0.3}]})
        s.add(p); s.commit(); s.refresh(p); pid = p.id
    # SRCID'yi gerçek id ile değiştir + dosyalar
    from pathlib import Path
    import json
    with get_sessionmaker()() as s:
        proj = s.get(Project, pid)
        proj.customizations = json.loads(json.dumps(proj.customizations).replace("SRCID", pid))
        s.commit()
    d = Path(tmp_path / "projects" / "default" / pid)
    (d / "decals").mkdir(parents=True)
    (d / "mesh.glb").write_bytes(b"glb"); (d / "decals" / "x.png").write_bytes(b"png")
    from gateway.main import app
    c = TestClient(app); c.pid = pid; c.tmp = tmp_path
    return c


def test_duplicate_copies_project_files_and_rewrites_urls(client):
    r = client.post(f"/projects/{client.pid}/duplicate", headers=_AUTH)
    assert r.status_code == 201, r.text
    new = r.json()
    assert new["id"] != client.pid
    assert "(kopya)" in new["name"]
    # decal URL yeni id'ye yazıldı (fixture'daki /api/ ön eki korunur)
    assert f"/api/projects/{new['id']}/decals/x.png" == new["customizations"]["decals"][0]["image"]
    # mesh + decal dosyaları kopyalandı
    from pathlib import Path
    nd = Path(client.tmp / "projects" / "default" / new["id"])
    assert (nd / "mesh.glb").exists() and (nd / "decals" / "x.png").exists()


def test_duplicate_unknown_404(client):
    assert client.post("/projects/nope/duplicate", headers=_AUTH).status_code == 404
