"""BATCH-F: motif-bake route'un PBR `channels` kwargs'ını worker'a ilettiğini doğrular.
Görsel doğrulama (GLB'de metallicRoughnessTexture) orkestratörde; burada yalnız route
sözleşmesi test edilir: channels YOKSA None (bugünkü davranış), VARSA aynen iletilir."""
import pytest
from fastapi.testclient import TestClient

_AUTH = {"Authorization": "Bearer test-token-bootstrap"}
# küçük geçerli dataURL (içerik önemsiz — route iletimi test edilir)
_DATAURL = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="


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
        p = Project(user_id="default", name="src", garment_type="tshirt",
                    template_id="generated", customizations={"color": "#ccc", "decals": []})
        s.add(p); s.commit(); s.refresh(p)
        pid = p.id
    sent = {}
    from common import celery_app as ca
    monkeypatch.setattr(ca.celery_app, "send_task",
                        lambda name, kwargs=None, queue=None, **_: sent.update(name=name, kwargs=kwargs, queue=queue))
    from gateway.main import app
    c = TestClient(app); c.sent = sent; c.pid = pid
    return c


def _body(client, **extra):
    body = {"source_project_id": client.pid, "prompt": "gold trim",
            "center": [0.0, 0.0, 0.0], "normal": [0.0, 0.0, 1.0], "scale": 0.5, "gpu": 1}
    body.update(extra)
    return body


def test_bake_without_channels_is_none(client):
    """channels alanı yoksa kwargs'a None geçer (bugünkü davranış korunur)."""
    r = client.post("/generate/motif-bake", headers=_AUTH, json=_body(client))
    assert r.status_code == 201, r.text
    assert client.sent["name"] == "motif.bake"
    assert client.sent["queue"] == "flux-gpu1"
    assert client.sent["kwargs"]["channels"] is None
    assert client.sent["kwargs"]["source_project_id"] == client.pid


def test_bake_forwards_both_channels(client):
    """roughness+metallic dataURL'leri worker kwargs'ına aynen iletilir."""
    ch = {"roughness": _DATAURL, "metallic": _DATAURL}
    r = client.post("/generate/motif-bake", headers=_AUTH, json=_body(client, channels=ch))
    assert r.status_code == 201, r.text
    assert client.sent["kwargs"]["channels"] == {"roughness": _DATAURL, "metallic": _DATAURL}


def test_bake_forwards_partial_channel(client):
    """Yalnız roughness verilirse metallic None olarak paketlenir."""
    r = client.post("/generate/motif-bake", headers=_AUTH,
                    json=_body(client, channels={"roughness": _DATAURL}))
    assert r.status_code == 201, r.text
    assert client.sent["kwargs"]["channels"] == {"roughness": _DATAURL, "metallic": None}


def test_bake_unknown_source_404(client):
    r = client.post("/generate/motif-bake", headers=_AUTH,
                    json=_body(client, source_project_id="nope"))
    assert r.status_code == 404
