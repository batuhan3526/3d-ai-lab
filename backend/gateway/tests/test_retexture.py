import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("APP_TOKEN", "test-token-bootstrap")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{str(tmp_path / 't.db').replace(chr(92), '/')}")
    # Gerçek uploads/projects/cache dizinine yazmayı engelle — test izolasyonu.
    monkeypatch.setenv("UPLOADS_DIR", str(tmp_path / "uploads"))
    monkeypatch.setenv("PROJECTS_DIR", str(tmp_path / "projects"))
    monkeypatch.setenv("CACHE_DIR", str(tmp_path / "cache"))
    from common.config import get_settings
    get_settings.cache_clear()
    from gateway import db as gdb
    gdb.reset_engine()
    gdb.init_db()
    # kaynak proje
    from gateway.db import get_sessionmaker
    from gateway.models.orm import Project
    with get_sessionmaker()() as s:
        p = Project(
            user_id="default",
            name="src",
            garment_type="boots",
            template_id="generated",
            customizations={"color": "#ccc", "decals": []},
        )
        s.add(p)
        s.commit()
        s.refresh(p)
        pid = p.id
    sent = {}

    def fake(name, kwargs=None, queue=None, **_):
        sent.update({"name": name, "kwargs": kwargs, "queue": queue})

    from common import celery_app as ca
    monkeypatch.setattr(ca.celery_app, "send_task", fake)
    from gateway.main import app
    c = TestClient(app)
    c.sent = sent
    c.pid = pid
    return c


_AUTH = {"Authorization": "Bearer test-token-bootstrap"}


def test_retexture_enqueues_to_intex(client):
    r = client.post("/generate/retexture", headers=_AUTH,
                    json={"source_project_id": client.pid, "prompt": "kırmızı desenli", "gpu": 1})
    assert r.status_code == 201
    assert client.sent["name"] == "texture_edit.generate"
    assert client.sent["queue"] == "intex-gpu1"
    assert client.sent["kwargs"]["source_project_id"] == client.pid


def test_retexture_unknown_source_404(client):
    r = client.post("/generate/retexture", headers=_AUTH,
                    json={"source_project_id": "nope", "prompt": "x"})
    assert r.status_code == 404


# F5 v2: bölge-maskeli yeniden dokula
_PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4"
    "890000000a49444154789c63000100000500010d0a2db40000000049454e44ae426082"
)


def test_retexture_region_enqueues_with_mask(client):
    r = client.post("/generate/retexture-region", headers=_AUTH,
                    files={"mask": ("mask.png", _PNG, "image/png")},
                    data={"source_project_id": client.pid, "prompt": "kırmızı deri", "gpu": "1"})
    assert r.status_code == 201
    assert client.sent["name"] == "texture_edit.generate"
    assert client.sent["queue"] == "intex-gpu1"
    assert client.sent["kwargs"]["mask_name"].endswith(".png")
    assert client.sent["kwargs"]["source_project_id"] == client.pid


def test_retexture_region_unknown_source_404(client):
    r = client.post("/generate/retexture-region", headers=_AUTH,
                    files={"mask": ("mask.png", _PNG, "image/png")},
                    data={"source_project_id": "nope", "prompt": "x", "gpu": "1"})
    assert r.status_code == 404
