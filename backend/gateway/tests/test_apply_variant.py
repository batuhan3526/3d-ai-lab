"""POST /variations/{id}/apply testleri (3D varyantı projeye uygula).

Hermetik: tmp_path DB + PROJECTS_DIR, sahte mesh.glb ve varyant .glb dosyaları.
Gerçek redis/celery/worker ÇALIŞMAZ — varyasyon zaten SUCCESS + result_path'li.
"""
from pathlib import Path

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
    from gateway.models.orm import Project, Variation
    with get_sessionmaker()() as s:
        p = Project(user_id="default", name="src", garment_type="tshirt",
                    template_id="generated", customizations={"color": "#ccc", "decals": []})
        s.add(p); s.commit(); s.refresh(p)
        pid = p.id
        # Drape/upscale deseni: SUCCESS + .glb result_path (galeri okurken uzlaşmış).
        v = Variation(group_id="g1", project_id=pid, kind="drape", seed=40,
                      prompt=None, job_id="job1", status="SUCCESS",
                      result_path="variations/draped.glb", size_bytes=200)
        s.add(v); s.commit(); s.refresh(v)
        vid = v.id
    proj_dir = Path(tmp_path / "projects" / "default" / pid)
    proj_dir.mkdir(parents=True, exist_ok=True)
    # Kanonik mesh + eski viewer kopyaları + varyant dosyası
    (proj_dir / "mesh.glb").write_bytes(b"OLD-MESH")
    (proj_dir / "mesh_view.glb").write_bytes(b"OLD-VIEW")
    (proj_dir / "mesh_view_20000.glb").write_bytes(b"OLD-VIEW-2")
    var_glb = proj_dir / "variations" / "draped.glb"
    var_glb.parent.mkdir(parents=True, exist_ok=True)
    var_glb.write_bytes(b"NEW-DRAPED-MESH")
    from gateway.main import app
    c = TestClient(app)
    c.pid = pid; c.vid = vid; c.proj_dir = proj_dir
    return c


def test_apply_replaces_mesh_and_backs_up(client):
    r = client.post(f"/variations/{client.vid}/apply", headers=_AUTH)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body == {"ok": True, "project_id": client.pid}
    # mesh.glb varyant içeriğiyle değişti
    assert (client.proj_dir / "mesh.glb").read_bytes() == b"NEW-DRAPED-MESH"
    # Eski mesh yedeklendi (mesh.glb.bak-<ts>)
    backups = list(client.proj_dir.glob("mesh.glb.bak-*"))
    assert len(backups) == 1
    assert backups[0].read_bytes() == b"OLD-MESH"
    # Viewer kopyaları geçersiz kılındı (yeniden üretilecek)
    assert not (client.proj_dir / "mesh_view.glb").exists()
    assert not (client.proj_dir / "mesh_view_20000.glb").exists()
    # Project.mesh_path göreli olarak güncellendi
    from gateway.db import get_sessionmaker
    from gateway.models.orm import Project
    with get_sessionmaker()() as s:
        proj = s.get(Project, client.pid)
        assert proj.mesh_path == f"default/{client.pid}/mesh.glb"


def test_apply_unknown_variation_404(client):
    r = client.post("/variations/nope/apply", headers=_AUTH)
    assert r.status_code == 404


def test_apply_requires_auth(client):
    assert client.post(f"/variations/{client.vid}/apply").status_code == 401
