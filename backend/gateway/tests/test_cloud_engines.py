"""Bulut API motorları: anahtar yoksa kilitli, varsa cloud-cpu kuyruğu; motif motor seçimi."""
import io

import fakeredis
import pytest
from fastapi.testclient import TestClient

_AUTH = {"Authorization": "Bearer test-token-bootstrap"}
_PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 64


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("APP_TOKEN", "test-token-bootstrap")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{str(tmp_path / 't.db').replace(chr(92), '/')}")
    monkeypatch.setenv("UPLOADS_DIR", str(tmp_path / "up").replace(chr(92), "/"))
    monkeypatch.setenv("VISIBLE_GPUS", "0,1")
    # Host .env'inden bağımsız: anahtarlar varsayılan boş; testler gerekirse açar.
    for k in ("TRIPO_API_KEY", "OPENAI_API_KEY", "FAL_KEY"):
        monkeypatch.setenv(k, "")
    from common.config import get_settings
    get_settings.cache_clear()
    from gateway import db as gdb
    gdb.reset_engine()
    gdb.init_db()
    from gateway.models.orm import Project
    with gdb.get_sessionmaker()() as s:
        p = Project(user_id="default", name="p", garment_type="tshirt", template_id="t",
                    customizations={"decals": []})
        s.add(p)
        s.commit()
        pid = p.id
    sent = []
    from common import celery_app as ca
    monkeypatch.setattr(ca.celery_app, "send_task",
                        lambda name, kwargs=None, queue=None, **_: sent.append(
                            {"name": name, "kwargs": kwargs, "queue": queue}))
    import gateway.routes.generate as gr
    from common.jobs import JobStore
    store = JobStore(fakeredis.FakeStrictRedis(decode_responses=True))
    monkeypatch.setattr(gr, "_job_store", lambda: store)
    from gateway.main import app
    c = TestClient(app)
    c.sent, c.pid = sent, pid
    return c


def _set_key(monkeypatch, name, value="sk-test-123"):
    monkeypatch.setenv(name, value)
    from common.config import get_settings
    get_settings.cache_clear()


def test_engines_list_marks_cloud_locked_without_key(client):
    r = client.get("/engines", headers=_AUTH)
    specs = {s["id"]: s for s in r.json()}
    t = specs["cloud-tripo-text"]
    assert t["cloud"] is True and t["key_set"] is False and t["available"] is False
    assert t["requires_key"] == "TRIPO_API_KEY" and t["gpus"] == []
    assert specs["trellis-text"]["cloud"] is False and specs["trellis-text"]["available"] is True
    # Anahtar değeri hiçbir alanda dönmez.
    assert "sk-" not in r.text


def test_locked_cloud_text_rejected_with_key_hint(client):
    r = client.post("/generate/text", headers=_AUTH,
                    json={"prompt": "x", "garment_type": "tshirt", "engine_id": "cloud-tripo-text"})
    assert r.status_code == 422
    assert "TRIPO_API_KEY" in r.text
    assert client.sent == []


def test_cloud_text_routes_to_cpu_queue_with_key(client, monkeypatch):
    _set_key(monkeypatch, "TRIPO_API_KEY")
    r = client.post("/generate/text", headers=_AUTH,
                    json={"prompt": "x", "garment_type": "tshirt", "engine_id": "cloud-tripo-text", "gpu": 1})
    assert r.status_code == 201, r.text
    assert client.sent[-1]["name"] == "text_to_3d.generate"
    assert client.sent[-1]["queue"] == "cloud-cpu"
    assert "sk-test-123" not in str(client.sent[-1]["kwargs"])


def test_cloud_image_locked_then_open(client, monkeypatch):
    files = {"file": ("a.png", io.BytesIO(_PNG), "image/png")}
    r = client.post("/generate/image", headers=_AUTH, files=files,
                    data={"garment_type": "tshirt", "engine_id": "cloud-tripo-image"})
    assert r.status_code == 422 and "TRIPO_API_KEY" in r.text
    _set_key(monkeypatch, "TRIPO_API_KEY")
    files = {"file": ("a.png", io.BytesIO(_PNG), "image/png")}
    r = client.post("/generate/image", headers=_AUTH, files=files,
                    data={"garment_type": "tshirt", "engine_id": "cloud-tripo-image"})
    assert r.status_code == 201, r.text
    assert client.sent[-1]["name"] == "image_to_3d.generate"
    assert client.sent[-1]["queue"] == "cloud-cpu"


def test_local_motif_request_unchanged(client):
    r = client.post("/generate/motif", headers=_AUTH, json={"project_id": client.pid, "prompt": "rose", "gpu": 1})
    assert r.status_code == 201, r.text
    s = client.sent[-1]
    assert s["queue"] == "flux-gpu1" and "engine_id" not in s["kwargs"]


def test_cloud_motif_locked_and_routed(client, monkeypatch):
    body = {"project_id": client.pid, "prompt": "dragon", "engine_id": "cloud-openai-image"}
    r = client.post("/generate/motif", headers=_AUTH, json=body)
    assert r.status_code == 422 and "OPENAI_API_KEY" in r.text
    _set_key(monkeypatch, "OPENAI_API_KEY")
    r = client.post("/generate/motif", headers=_AUTH, json=body)
    assert r.status_code == 201, r.text
    s = client.sent[-1]
    assert s["name"] == "motif.generate" and s["queue"] == "cloud-cpu"
    assert s["kwargs"]["engine_id"] == "cloud-openai-image"


def test_cloud_motif_bake_and_batch_routed(client, monkeypatch):
    _set_key(monkeypatch, "FAL_KEY")
    r = client.post("/generate/motif-bake", headers=_AUTH, json={
        "source_project_id": client.pid, "prompt": "dragon", "center": [0, 0, 0],
        "normal": [0, 0, 1], "scale": 0.3, "engine_id": "cloud-falflux-image"})
    assert r.status_code == 201, r.text
    assert client.sent[-1]["queue"] == "cloud-cpu" and client.sent[-1]["name"] == "motif.bake"
    r = client.post("/generate/batch", headers=_AUTH, json={
        "kind": "motif", "project_id": client.pid, "count": 2, "prompt": "dragon",
        "engine_id": "cloud-falflux-image"})
    assert r.status_code == 201, r.text
    assert [s["queue"] for s in client.sent[-2:]] == ["cloud-cpu", "cloud-cpu"]


def test_motif_rejects_non_motif_engine(client, monkeypatch):
    _set_key(monkeypatch, "TRIPO_API_KEY")
    r = client.post("/generate/motif", headers=_AUTH,
                    json={"project_id": client.pid, "prompt": "x", "engine_id": "cloud-tripo-text"})
    assert r.status_code == 422


def test_queue_for_cpu_and_gpu():
    from common.engines.registry import queue_for
    assert queue_for("cloud-meshy-image", 1) == "cloud-cpu"
    assert queue_for("clothsim-drape", 1) == "clothsim-cpu"
    assert queue_for("trellis-text", 1) == "trellis-gpu1"
