import pytest
from fastapi.testclient import TestClient

_AUTH = {"Authorization": "Bearer test-token-bootstrap"}


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("APP_TOKEN", "test-token-bootstrap")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{str(tmp_path / 't.db').replace(chr(92), '/')}")
    from common.config import get_settings
    get_settings.cache_clear()
    from gateway import db as gdb
    gdb.reset_engine(); gdb.init_db()
    from gateway.db import get_sessionmaker
    from gateway.models.orm import Project
    with get_sessionmaker()() as s:
        p = Project(user_id="default", name="P", garment_type="tshirt", template_id="generated",
                    customizations={"color": "#fff", "decals": []})
        s.add(p); s.commit(); s.refresh(p); pid = p.id
    from gateway.main import app
    c = TestClient(app); c.pid = pid
    return c


def _cust(color):
    return {"color": color, "decals": []}


def test_version_create_list_restore_delete(client):
    r = client.post(f"/projects/{client.pid}/versions", headers=_AUTH,
                    json={"name": "mavi", "auto": False, "customizations": _cust("#00f")})
    assert r.status_code == 201
    vid = r.json()["id"]
    lst = client.get(f"/projects/{client.pid}/versions", headers=_AUTH).json()
    assert len(lst) == 1 and lst[0]["name"] == "mavi"
    rs = client.post(f"/projects/{client.pid}/versions/{vid}/restore", headers=_AUTH)
    assert rs.status_code == 200 and rs.json()["customizations"]["color"] == "#00f"
    assert client.delete(f"/projects/{client.pid}/versions/{vid}", headers=_AUTH).status_code == 204
    assert client.get(f"/projects/{client.pid}/versions", headers=_AUTH).json() == []


def test_auto_versions_capped_at_10(client):
    for i in range(12):
        client.post(f"/projects/{client.pid}/versions", headers=_AUTH,
                    json={"name": f"oto{i}", "auto": True, "customizations": _cust("#fff")})
    autos = [v for v in client.get(f"/projects/{client.pid}/versions", headers=_AUTH).json() if v["auto"]]
    assert len(autos) == 10
