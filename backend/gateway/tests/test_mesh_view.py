"""Viewer kopyası (mesh_view.glb): UV'siz/dev mesh → decimate + xatlas unwrap.
mesh.glb (tam çözünürlük) kanonik kalır. GET /mesh ilk istekte orijinali döndürür
ve view'i ARKA PLANDA üretir (xatlas dakikalar sürebilir, istek bloklanmaz)."""
import pathlib
import time

import pytest
import trimesh
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("APP_TOKEN", "test-token-bootstrap")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{str(tmp_path / 't.db').replace(chr(92), '/')}")
    monkeypatch.setenv("PROJECTS_DIR", str(tmp_path / "projects").replace(chr(92), "/"))
    from common.config import get_settings
    get_settings.cache_clear()
    from gateway import db as gdb
    gdb.reset_engine()
    gdb.init_db()
    from gateway.db import get_sessionmaker
    from gateway.models.orm import Project
    with get_sessionmaker()() as s:
        p = Project(user_id="default", name="x", garment_type="boots",
                    template_id="generated", customizations={"color": "#ccc", "decals": []})
        s.add(p)
        s.commit()
        s.refresh(p)
        pid = p.id
    from gateway.routes import projects as pr
    pr._VIEW_STATE.clear()
    from gateway.main import app
    c = TestClient(app)
    c.pid = pid
    c.mesh_dir = pathlib.Path(str(tmp_path / "projects" / "default" / pid))
    c.mesh_dir.mkdir(parents=True, exist_ok=True)
    return c


def test_uvless_mesh_view_is_unwrapped(client):
    # UV'siz icosphere → _ensure_view_mesh çıktısı UV'li olmalı (3D fırça şartı)
    from gateway.routes import projects as pr
    trimesh.creation.icosphere(subdivisions=3).export(str(client.mesh_dir / "mesh.glb"))
    view = pr._ensure_view_mesh(client.pid)
    assert view.name == "mesh_view.glb"
    m = trimesh.load(str(view), force="mesh")
    uv = getattr(m.visual, "uv", None)
    assert uv is not None and len(uv) == len(m.vertices)
    # kanonik mesh dokunulmamış (UV'siz kaldı)
    orig = trimesh.load(str(client.mesh_dir / "mesh.glb"), force="mesh")
    assert getattr(orig.visual, "uv", None) is None


def test_big_mesh_view_is_decimated(client, monkeypatch):
    from gateway.routes import projects as pr
    monkeypatch.setattr(pr, "_VIEW_MAX_FACES", 100)
    trimesh.creation.icosphere(subdivisions=3).export(str(client.mesh_dir / "mesh.glb"))  # 1280 face
    view = pr._ensure_view_mesh(client.pid)
    m = trimesh.load(str(view), force="mesh")
    assert len(m.faces) <= 110  # decimate hedefi (~100)
    orig = trimesh.load(str(client.mesh_dir / "mesh.glb"), force="mesh")
    assert len(orig.faces) == 1280  # tam çözünürlük korunur


def test_view_keeps_double_sided_material(client, monkeypatch):
    """Açık yüzeyli tek katman kumaş (TRELLIS.2) çift taraflı gelir; viewer kopyasının yeni
    malzemesi bunu korumalı (yoksa arkası dönük yüzler görüntüleyicide kaybolur)."""
    import json
    import struct
    import numpy as np
    from PIL import Image
    from gateway.routes import projects as pr
    monkeypatch.setattr(pr, "_VIEW_MAX_FACES", 100)
    sph = trimesh.creation.icosphere(subdivisions=3)
    uv = np.random.default_rng(0).random((len(sph.vertices), 2))
    sph.visual = trimesh.visual.TextureVisuals(uv=uv, material=trimesh.visual.material.PBRMaterial(
        baseColorTexture=Image.new("RGB", (8, 8), (200, 30, 30)), doubleSided=True))
    sph.export(str(client.mesh_dir / "mesh.glb"))
    view = pr._ensure_view_mesh(client.pid)
    raw = view.read_bytes()
    n = struct.unpack("<I", raw[12:16])[0]
    mats = json.loads(raw[20:20 + n])["materials"]
    assert mats and all(m.get("doubleSided") for m in mats)


def test_small_uv_mesh_served_as_is(client):
    from gateway.routes import projects as pr
    box = trimesh.creation.box([1, 1, 1])
    box.visual = trimesh.visual.TextureVisuals(
        uv=[[0.0, 0.0]] * len(box.vertices),
        material=trimesh.visual.material.PBRMaterial())
    box.export(str(client.mesh_dir / "mesh.glb"))
    view = pr._ensure_view_mesh(client.pid)
    assert view.name == "mesh.glb"  # kopya üretilmez
    assert not (client.mesh_dir / "mesh_view.glb").exists()


def test_get_mesh_serves_immediately_and_builds_async(client):
    # İlk GET bloklanmaz (orijinal döner); view arka planda oluşur, sonraki GET hafif kopyayı verir
    trimesh.creation.icosphere(subdivisions=3).export(str(client.mesh_dir / "mesh.glb"))
    r = client.get(f"/projects/{client.pid}/mesh")
    assert r.status_code == 200
    deadline = time.time() + 30
    view = client.mesh_dir / "mesh_view.glb"
    while time.time() < deadline and not view.exists():
        time.sleep(0.2)
    assert view.exists(), "arka plan view üretimi 30sn'de bitmedi"
    r2 = client.get(f"/projects/{client.pid}/mesh")
    assert r2.status_code == 200
    assert len(r2.content) == view.stat().st_size


def test_vertex_colors_are_baked_into_view_texture(client, monkeypatch):
    """Dokusuz ama vertex-renkli mesh (Idol, TripoSR): viewer kopyası gri fallback değil,
    vertex renklerinden bake edilmiş doku taşımalı (canlı vaka 2026-11-02: lacivert tişört gri)."""
    import numpy as np
    from gateway.routes import projects as pr
    monkeypatch.setattr(pr, "_VIEW_MAX_FACES", 300)
    sph = trimesh.creation.icosphere(subdivisions=3)
    cols = np.where(sph.vertices[:, :1] > 0, [[220, 20, 20, 255]], [[20, 20, 220, 255]]).astype(np.uint8)
    sph.visual = trimesh.visual.ColorVisuals(sph, vertex_colors=cols)
    sph.export(str(client.mesh_dir / "mesh.glb"))
    view = pr._ensure_view_mesh(client.pid)
    m = trimesh.load(str(view), force="mesh")
    tex = np.asarray(m.visual.material.baseColorTexture.convert("RGB"))
    assert tex.shape[0] > 16  # gri 16x16 fallback değil
    # yüzeyde örnekle: +x tarafı kırmızı, -x tarafı mavi
    c = m.visual.to_color().vertex_colors[:, :3].astype(int)
    right, left = m.vertices[:, 0] > 0.5, m.vertices[:, 0] < -0.5
    assert c[right, 0].mean() > 150 and c[right, 2].mean() < 80
    assert c[left, 2].mean() > 150 and c[left, 0].mean() < 80
