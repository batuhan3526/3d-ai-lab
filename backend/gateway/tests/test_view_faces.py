"""R2 serbest görüntüleme çözünürlüğü seçici: GET /projects/{id}/mesh?faces=...

- faces serbesttir ama 1_000..1_000_000 aralığında olmalı → aralık dışı 422.
- Her çözünürlük ayrı viewer kopyasına önbelleklenir (mesh_view_<faces>.glb);
  faces yoksa eski davranış (mesh_view.glb) korunur.
- Farklı faces → farklı dosya adı + farklı face sayısı (decimation hedefi)."""
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


def _wait(path: pathlib.Path, timeout: float = 30.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline and not path.exists():
        time.sleep(0.2)
    assert path.exists(), f"arka plan view üretimi {timeout}sn'de bitmedi: {path.name}"


def test_out_of_range_faces_rejected(client):
    trimesh.creation.icosphere(subdivisions=2).export(str(client.mesh_dir / "mesh.glb"))
    # aralık altı (< 1000) → 422
    assert client.get(f"/projects/{client.pid}/mesh?faces=500").status_code == 422
    # aralık üstü (> 1_000_000) → 422
    assert client.get(f"/projects/{client.pid}/mesh?faces=2000000").status_code == 422
    # sayı olmayan string (full dışında) → 422
    assert client.get(f"/projects/{client.pid}/mesh?faces=abc").status_code == 422
    assert client.get(f"/projects/{client.pid}/mesh?faces=20k").status_code == 422


def test_faces_full_serves_canonical_bytes(client):
    """R3: faces=full, decimate edilmemiş KANONİK mesh.glb baytlarını verir —
    düşük çözünürlük view'dan (decimate+doku) farklıdır."""
    # 81920 face: view (20k) mutlaka decimate olur → full'den farklı bayt.
    trimesh.creation.icosphere(subdivisions=6).export(str(client.mesh_dir / "mesh.glb"))
    canonical = (client.mesh_dir / "mesh.glb").read_bytes()

    r_full = client.get(f"/projects/{client.pid}/mesh?faces=full")
    assert r_full.status_code == 200
    assert r_full.content == canonical, "faces=full kanonik mesh.glb baytlarını vermeli"

    # düşük çözünürlük view farklı olmalı (decimate + yeniden parametrize)
    r_view = client.get(f"/projects/{client.pid}/mesh?faces=20000")
    assert r_view.status_code == 200
    assert r_view.content != canonical, "20k view kanonikten farklı olmalı"
    # kanonik dosya dokunulmadı
    assert (client.mesh_dir / "mesh.glb").read_bytes() == canonical


@pytest.mark.parametrize("faces", [1000, 5000, 20000, 40000, 80000, 1000000])
def test_in_range_faces_accepted(client, faces):
    trimesh.creation.icosphere(subdivisions=2).export(str(client.mesh_dir / "mesh.glb"))
    r = client.get(f"/projects/{client.pid}/mesh?faces={faces}")
    assert r.status_code == 200


def test_no_faces_uses_default_filename(client):
    trimesh.creation.icosphere(subdivisions=3).export(str(client.mesh_dir / "mesh.glb"))
    r = client.get(f"/projects/{client.pid}/mesh")
    assert r.status_code == 200
    _wait(client.mesh_dir / "mesh_view.glb")
    # faces'siz istek eski dosyayı kullanır, faces'li varyant üretmez
    assert not (client.mesh_dir / "mesh_view_80000.glb").exists()


def test_distinct_faces_cache_distinct_files(client):
    # Builder'ı doğrudan çağırırız (endpoint'in _VIEW_FACE_OPTIONS doğrulaması
    # dışı): her cap ayrı dosyaya ve ayrı decimation hedefine gider.
    from gateway.routes import projects as pr
    trimesh.creation.icosphere(subdivisions=4).export(str(client.mesh_dir / "mesh.glb"))  # 5120 face
    v100 = pr._ensure_view_mesh(client.pid, 100)
    v200 = pr._ensure_view_mesh(client.pid, 200)
    # farklı dosya adları (per-faces önbellek)
    assert v100.name == "mesh_view_100.glb"
    assert v200.name == "mesh_view_200.glb"
    assert v100 != v200
    assert v100.exists() and v200.exists()
    # farklı face sayıları (ayrı decimation hedefleri)
    m100 = trimesh.load(str(v100), force="mesh")
    m200 = trimesh.load(str(v200), force="mesh")
    assert len(m100.faces) <= 130
    assert len(m200.faces) <= 240
    assert len(m100.faces) < len(m200.faces)
    # kanonik mesh dokunulmamış
    orig = trimesh.load(str(client.mesh_dir / "mesh.glb"), force="mesh")
    assert len(orig.faces) == 5120


def _write_textured_sphere(mesh_dir: pathlib.Path) -> dict:
    """UV + 4-renk kadran dokulu, decimation gerektirecek kadar yoğun bir küre
    üret (T1 view doku yeniden-bake testi için). Renkleri geri döndür."""
    import numpy as np
    import xatlas
    from PIL import Image

    sph = trimesh.creation.icosphere(subdivisions=5)  # 20480 face
    vmapping, indices, uvs = xatlas.parametrize(
        np.asarray(sph.vertices), np.asarray(sph.faces))
    m = trimesh.Trimesh(vertices=sph.vertices[vmapping], faces=indices, process=False)
    colors = {
        "red": (220, 30, 30), "green": (30, 180, 30),
        "blue": (30, 30, 220), "yellow": (220, 200, 30),
    }
    tex = np.zeros((256, 256, 3), np.uint8)
    tex[:128, :128] = colors["red"]
    tex[:128, 128:] = colors["green"]
    tex[128:, :128] = colors["blue"]
    tex[128:, 128:] = colors["yellow"]
    m.visual = trimesh.visual.TextureVisuals(
        uv=uvs,
        material=trimesh.visual.material.PBRMaterial(
            baseColorTexture=Image.fromarray(tex, "RGB")))
    m.export(str(mesh_dir / "mesh.glb"))
    return colors


def test_view_texture_rebaked_not_white(client):
    """Dokulu bir mesh decimate+reparametrize edilince, view dokusu ORİJİNAL
    dokudan yeniden bake edilmeli: çıktı çoğunlukla beyaz OLMAMALI (mipmap beyaz
    sızıntısı = eski bug) ve dört kadran rengi de hayatta kalmalı."""
    import time

    import numpy as np
    from gateway.routes import projects as pr

    colors = _write_textured_sphere(client.mesh_dir)
    t0 = time.time()
    view = pr._ensure_view_mesh(client.pid, 2000)  # 20480 → 2000: decimation + rebake
    elapsed = time.time() - t0
    assert elapsed < 60.0, f"bake çok yavaş: {elapsed:.1f}s"

    out = trimesh.load(str(view), force="mesh")
    assert len(out.faces) <= 2200  # decimate oldu
    bct = out.visual.material.baseColorTexture
    img = np.asarray(bct.convert("RGB"), dtype=np.float64) / 255.0
    # 16x16 gri fallback DEĞİL — gerçek 1024² bake üretildi
    assert img.shape[0] == pr._VIEW_BAKE_SIZE and img.shape[1] == pr._VIEW_BAKE_SIZE
    # çoğunlukla beyaz değil (beyaz kılcal/üçgen artefaktı → ortalama ~1.0 olurdu)
    assert img.mean() < 0.9, f"doku çoğunlukla beyaz: mean={img.mean():.3f}"
    # dört kadran rengi de örneklerde hayatta kalmalı (en-yakın-komşu → tam renk)
    flat = img.reshape(-1, 3)
    for name, rgb in colors.items():
        c = np.asarray(rgb, dtype=np.float64) / 255.0
        present = (np.abs(flat - c).sum(axis=1) < 0.15).any()
        assert present, f"{name} rengi view dokusunda kaybolmuş"
