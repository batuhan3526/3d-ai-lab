import fakeredis
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
    # proje + bir varyasyon (SUBMITTED) + işin SUCCESS olduğu sahte job + decal dosyası
    from gateway.db import get_sessionmaker
    from gateway.models.orm import Project, Variation
    with get_sessionmaker()() as s:
        p = Project(user_id="default", name="src", garment_type="tshirt",
                    template_id="generated", customizations={"color": "#ccc", "decals": []})
        s.add(p); s.commit(); s.refresh(p)
        pid = p.id
        v = Variation(group_id="g1", project_id=pid, kind="motif", seed=5,
                      prompt="gül", job_id="job1", status="SUBMITTED")
        s.add(v); s.commit(); s.refresh(v)
        vid = v.id
    # decal dosyası
    from pathlib import Path
    rel = "decals/abc.png"
    fp = Path(tmp_path / "projects" / "default" / pid / rel)
    fp.parent.mkdir(parents=True, exist_ok=True)
    fp.write_bytes(b"\x89PNG" + b"0" * 100)
    # fakeredis job: SUCCESS + decal_path
    import gateway.routes.variations as vr
    from common.jobs import JobStore
    fake = fakeredis.FakeStrictRedis(decode_responses=True)
    store = JobStore(fake)
    store.create("job1", {"project_id": pid})
    store.succeed("job1", {"project_id": pid, "decal_path": rel})
    monkeypatch.setattr(vr, "_job_store", lambda: store)
    from gateway.main import app
    c = TestClient(app); c.pid = pid; c.vid = vid
    return c


def test_list_reconciles_success(client):
    r = client.get("/variations?group_id=g1", headers=_AUTH)
    assert r.status_code == 200, r.text
    rows = r.json()
    assert len(rows) == 1
    assert rows[0]["status"] == "SUCCESS"
    assert rows[0]["result_path"] == "decals/abc.png"
    assert rows[0]["size_bytes"] == 104


def test_favorite_toggle(client):
    assert client.post(f"/variations/{client.vid}/favorite", headers=_AUTH).status_code == 200
    rows = client.get("/variations?group_id=g1", headers=_AUTH).json()
    assert rows[0]["favorite"] is True
    assert client.delete(f"/variations/{client.vid}/favorite", headers=_AUTH).status_code == 200
    rows = client.get("/variations?group_id=g1", headers=_AUTH).json()
    assert rows[0]["favorite"] is False


def test_storage_summary(client):
    client.get("/variations?group_id=g1", headers=_AUTH)  # önce uzlaştır
    r = client.get("/variations/storage", headers=_AUTH)
    assert r.status_code == 200
    body = r.json()
    assert body["count"] == 1
    assert body["total_bytes"] == 104
    assert body["groups"][0]["group_id"] == "g1"


def test_delete_variation_removes_row_and_file(client):
    client.get("/variations?group_id=g1", headers=_AUTH)  # uzlaştır → result_path dolsun
    assert client.delete(f"/variations/{client.vid}", headers=_AUTH).status_code == 200
    assert client.get("/variations?group_id=g1", headers=_AUTH).json() == []


def test_delete_group(client):
    assert client.delete("/variations/group/g1", headers=_AUTH).status_code == 200
    assert client.get("/variations?group_id=g1", headers=_AUTH).json() == []


def test_requires_auth(client):
    assert client.get("/variations?group_id=g1").status_code == 401
