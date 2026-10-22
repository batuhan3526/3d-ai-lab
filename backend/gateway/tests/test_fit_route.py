"""POST /projects/{id}/fit (mankene giydir) + üretimle zincirleme giydirme + ölçü tablosu."""
import io
import shutil
from pathlib import Path

import fakeredis
import pytest
from fastapi.testclient import TestClient

_AUTH = {"Authorization": "Bearer test-token-bootstrap"}
_T = {"position": [0.0, -0.42, 0.03], "rotation": [0, 0, 0], "scale": 2.2}
_REAL_MQ = Path(__file__).resolve().parents[3] / "data" / "templates" / "mannequins"
_BODY = {"gender": "female", "height_cm": 160, "chest_cm": 96, "waist_cm": 80, "hip_cm": 102}
_PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 64


@pytest.fixture
def client(tmp_path, monkeypatch):
    # Gerçek manken klasörünü kirletme: taban mankenleri geçici şablon dizinine kopyala.
    mq = tmp_path / "templates" / "mannequins"
    mq.mkdir(parents=True)
    for name in ("female-a.glb", "male-a.glb", "manifest.json"):
        if (_REAL_MQ / name).exists():
            shutil.copy2(_REAL_MQ / name, mq / name)
    monkeypatch.setenv("TEMPLATES_DIR", str(tmp_path / "templates"))
    monkeypatch.setenv("APP_TOKEN", "test-token-bootstrap")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{str(tmp_path / 't.db').replace(chr(92), '/')}")
    monkeypatch.setenv("UPLOADS_DIR", str(tmp_path / "up"))
    monkeypatch.setenv("PROJECTS_DIR", str(tmp_path / "projects"))
    monkeypatch.setenv("VISIBLE_GPUS", "0,1")
    from common.config import get_settings
    get_settings.cache_clear()
    from gateway import db as gdb
    gdb.reset_engine()
    gdb.init_db()
    from gateway.models.orm import Project
    with gdb.get_sessionmaker()() as s:
        bare = Project(user_id="default", name="a", garment_type="shirt", template_id="t",
                       customizations={"decals": []})
        withm = Project(user_id="default", name="b", garment_type="shirt", template_id="t",
                        customizations={"decals": [], "mannequin": {"id": "male-a", "transform": _T}})
        boots = Project(user_id="default", name="c", garment_type="boots", template_id="t",
                        customizations={})
        s.add_all([bare, withm, boots])
        s.commit()
        ids = (bare.id, withm.id, boots.id)
    sent = []
    from common import celery_app as ca
    monkeypatch.setattr(ca.celery_app, "send_task",
                        lambda name, kwargs=None, queue=None, **kw: sent.append((name, kwargs, queue, kw)))
    store = __import__("common.jobs", fromlist=["JobStore"]).JobStore(fakeredis.FakeStrictRedis(decode_responses=True))
    import gateway.routes.drape as dr
    import gateway.routes.generate as gr
    monkeypatch.setattr(dr, "_job_store", lambda: store)
    monkeypatch.setattr(gr, "_job_store", lambda: store)
    from gateway.main import app
    c = TestClient(app)
    c.sent, c.ids, c.store, c.mq = sent, ids, store, mq
    return c


def test_fit_defaults_to_base_mannequin_and_auto_transform(client):
    r = client.post(f"/projects/{client.ids[0]}/fit", headers=_AUTH, json={})
    assert r.status_code == 201, r.text
    name, kw, queue, _ = client.sent[-1]
    assert name == "clothsim.fit" and queue == "clothsim-cpu"
    assert kw["mannequin_id"] == "female-a" and kw["transform"] is None and kw["auto_apply"] is False


def test_fit_uses_saved_mannequin(client):
    r = client.post(f"/projects/{client.ids[1]}/fit", headers=_AUTH, json={})
    assert r.status_code == 201, r.text
    assert client.sent[-1][1]["mannequin_id"] == "male-a"


def test_fit_with_body_creates_and_reuses_custom_mannequin(client):
    r = client.post(f"/projects/{client.ids[0]}/fit", headers=_AUTH, json={"body": _BODY, "auto_apply": True})
    assert r.status_code == 201, r.text
    mid = client.sent[-1][1]["mannequin_id"]
    assert mid.startswith("custom-") and (client.mq / f"{mid}.glb").exists()
    assert client.sent[-1][1]["auto_apply"] is True
    client.post(f"/projects/{client.ids[0]}/fit", headers=_AUTH, json={"body": _BODY})
    assert client.sent[-1][1]["mannequin_id"] == mid          # aynı ölçü → aynı manken
    assert len(list(client.mq.glob("custom-*.glb"))) == 1


def test_fit_rejects_unsupported_garment(client):
    r = client.post(f"/projects/{client.ids[2]}/fit", headers=_AUTH, json={})
    assert r.status_code == 422


def test_generate_text_with_dress_links_fit(client):
    r = client.post("/generate/text", headers=_AUTH, json={
        "prompt": "x", "garment_type": "tshirt", "dress": {"mannequin_id": "male-a"}})
    assert r.status_code == 201, r.text
    out = r.json()
    assert out["dress_job_id"]
    name, kw, queue, extra = client.sent[-1]
    assert name == "text_to_3d.generate"
    link = extra["link"]
    assert link.task == "clothsim.fit" and link.options["queue"] == "clothsim-cpu" and link.immutable
    assert link.kwargs["job_id"] == out["dress_job_id"] and link.kwargs["auto_apply"] is True
    assert link.kwargs["project_id"] == out["project_id"]
    assert client.store.get(out["dress_job_id"])["state"] == "SUBMITTED"


def test_generate_image_with_dress_body(client):
    files = {"file": ("a.png", io.BytesIO(_PNG), "image/png")}
    import json
    r = client.post("/generate/image", headers=_AUTH, files=files,
                    data={"garment_type": "shirt", "dress": json.dumps({"body": _BODY})})
    assert r.status_code == 201, r.text
    link = client.sent[-1][3]["link"]
    assert link.kwargs["mannequin_id"].startswith("custom-")


def test_generate_without_dress_unchanged(client):
    r = client.post("/generate/text", headers=_AUTH, json={"prompt": "x", "garment_type": "tshirt"})
    assert r.status_code == 201 and r.json()["dress_job_id"] is None
    assert "link" not in client.sent[-1][3]


def test_generate_dress_invalid_type_creates_no_project(client):
    before = len(client.get("/projects", headers=_AUTH).json())
    r = client.post("/generate/text", headers=_AUTH, json={
        "prompt": "x", "garment_type": "boots", "dress": {"mannequin_id": "male-a"}})
    assert r.status_code == 422
    assert len(client.get("/projects", headers=_AUTH).json()) == before
    assert client.sent == []


def test_measurements_endpoint(client):
    pid = client.ids[0]
    assert client.get(f"/projects/{pid}/measurements", headers=_AUTH).status_code == 404
    d = Path(client.mq).parents[1] / "projects" / "default" / pid
    d.mkdir(parents=True)
    (d / "measurements.json").write_text('{"rows": [{"key": "chest", "garment_cm": 100}]}')
    r = client.get(f"/projects/{pid}/measurements", headers=_AUTH)
    assert r.status_code == 200 and r.json()["rows"][0]["garment_cm"] == 100
