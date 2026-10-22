import fakeredis
import pytest
from fastapi.testclient import TestClient

_AUTH = {"Authorization": "Bearer test-token-bootstrap"}


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("APP_TOKEN", "test-token-bootstrap")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{str(tmp_path / 't.db').replace(chr(92), '/')}")
    # 2-GPU düzenini simüle et → gpu=1 geçerli (tek-GPU host'ta küme {0}'a çökerdi).
    monkeypatch.setenv("VISIBLE_GPUS", "0,1")
    from common.config import get_settings
    get_settings.cache_clear()
    from gateway import db as gdb
    gdb.reset_engine()
    gdb.init_db()
    from gateway.db import get_sessionmaker
    from gateway.models.orm import Project
    with get_sessionmaker()() as s:
        p = Project(user_id="default", name="src", garment_type="tshirt",
                    template_id="generated", customizations={"color": "#ccc", "decals": []})
        s.add(p); s.commit(); s.refresh(p)
        pid = p.id
    # Celery send_task'ı yakala
    sent = []
    from common import celery_app as ca
    monkeypatch.setattr(ca.celery_app, "send_task",
                        lambda name, kwargs=None, queue=None, **_: sent.append({"name": name, "kwargs": kwargs, "queue": queue}))
    # JobStore'u fakeredis'e bağla (generate.py içindeki _job_store)
    import gateway.routes.generate as gr
    from common.jobs import JobStore
    fake = fakeredis.FakeStrictRedis(decode_responses=True)
    store = JobStore(fake)
    monkeypatch.setattr(gr, "_job_store", lambda: store)
    from gateway.main import app
    c = TestClient(app)
    c.sent = sent; c.pid = pid; c.store = store
    return c


def test_batch_motif_creates_n_jobs_and_variations(client):
    r = client.post("/generate/batch", headers=_AUTH,
                    json={"kind": "motif", "project_id": client.pid, "count": 4,
                          "prompt": "kırmızı gül", "gpu": 1, "seed_base": 100})
    assert r.status_code == 201, r.text
    body = r.json()
    assert len(body["jobs"]) == 4
    assert len({j["seed"] for j in body["jobs"]}) == 4          # farklı seed'ler
    assert {j["seed"] for j in body["jobs"]} == {100, 101, 102, 103}
    # 4 celery task, hepsi motif.generate + flux-gpu1, seed kwargs'ta
    motif_calls = [c for c in client.sent if c["name"] == "motif.generate"]
    assert len(motif_calls) == 4
    assert all(c["queue"] == "flux-gpu1" for c in motif_calls)
    assert {c["kwargs"]["seed"] for c in motif_calls} == {100, 101, 102, 103}
    # 4 Variation satırı SUBMITTED
    from gateway.db import get_sessionmaker
    from gateway.models.orm import Variation
    with get_sessionmaker()() as s:
        rows = s.query(Variation).filter_by(group_id=body["group_id"]).all()
        assert len(rows) == 4
        assert all(v.status == "SUBMITTED" and v.kind == "motif" for v in rows)


def test_batch_unknown_project_404(client):
    r = client.post("/generate/batch", headers=_AUTH,
                    json={"kind": "motif", "project_id": "nope", "count": 2, "prompt": "x"})
    assert r.status_code == 404


def test_batch_style_passes_style_payload(client):
    style = {"image_name": "style_x.png", "crop": [0.1, 0.1, 0.5, 0.5], "ai": True}
    r = client.post("/generate/batch", headers=_AUTH,
                    json={"kind": "style", "project_id": client.pid, "count": 2, "style": style})
    assert r.status_code == 201, r.text
    motif_calls = [c for c in client.sent if c["name"] == "motif.generate"]
    assert len(motif_calls) == 2
    assert all(c["kwargs"]["style"] == style for c in motif_calls)
