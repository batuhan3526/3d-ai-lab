"""texture.upscale worker testleri (mesh I/O gerçek trimesh; ESRGAN/GPU mock'lu).

Hermetik: worker src'i zaten common venv'de kurulu (flux_motif_worker); PROJECTS_DIR
tmp_path'e alınır; JobStore fake ile değiştirilir; motor upscale_image mock'lanır ya
da gerçek EsrganMissing (spandrel kurulu değil) yolu test edilir. GPU/spandrel gerçek
çıkarım ÇALIŞMAZ.
"""
import pathlib
import sys
from pathlib import Path

# Worker src'ini import edilebilir yap (flux venv'de kurulu; gateway-minimal'de değil).
_SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

import numpy as np
import trimesh
from PIL import Image


def _write_textured_glb(path: Path, size=8, color=(200, 60, 60)):
    """UV'li + baseColorTexture'lı minik bir kutu GLB yaz (trimesh export)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    m = trimesh.creation.box(extents=(1, 1, 1))
    uv = np.random.default_rng(0).random((len(m.vertices), 2))
    tex = Image.new("RGB", (size, size), color)
    m.visual = trimesh.visual.TextureVisuals(
        uv=uv, material=trimesh.visual.material.PBRMaterial(baseColorTexture=tex))
    m.export(str(path))


class _FakeStore:
    def __init__(self):
        self.events = {}
    def set_state(self, j, s): self.events["state"] = s
    def set_progress(self, j, st, p): self.events.setdefault("prog", []).append((st, p))
    def succeed(self, j, r): self.events["ok"] = r
    def fail(self, j, e): self.events["fail"] = e


def _setup(tmp_path, monkeypatch):
    monkeypatch.setenv("PROJECTS_DIR", str(tmp_path / "projects"))
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{str(tmp_path / 't.db').replace(chr(92), '/')}")
    from common.config import get_settings
    get_settings.cache_clear()
    import flux_motif_worker.worker as w
    store = _FakeStore()
    monkeypatch.setattr(w, "JobStore", lambda: store)
    return w, store


def test_upscale_task_registered_name():
    import flux_motif_worker.worker as w
    assert w.upscale_texture.name == "texture.upscale"


def test_upscale_writes_variation_glb(tmp_path, monkeypatch):
    w, store = _setup(tmp_path, monkeypatch)
    base = Path(tmp_path / "projects" / "default")
    _write_textured_glb(base / "p1" / "mesh_view.glb")

    # Motoru mock'la: 2x büyütülmüş düz görsel döndür (GPU/spandrel'e dokunmaz).
    class FakeEngine:
        def upscale_image(self, img, *, scale=2, tile=1024):
            return img.convert("RGB").resize((img.width * scale, img.height * scale))
    monkeypatch.setattr(w, "_get", lambda: FakeEngine())

    out = w.upscale_texture.run("job1", "p1", 2)
    assert out["project_id"] == "p1"
    rel = out["decal_path"]
    assert rel == out["upscale_path"]
    assert rel.startswith("variations/upscale_") and rel.endswith(".glb")
    # decal_path → /variations reconcile kancası
    written = base / "p1" / rel
    assert written.exists() and written.stat().st_size > 0
    assert store.events["ok"] == out
    # Kaynak mesh dokunulmamış (güvenli varyant deseni)
    assert (base / "p1" / "mesh_view.glb").exists()


def test_upscale_esrgan_missing_fails_gracefully(tmp_path, monkeypatch):
    w, store = _setup(tmp_path, monkeypatch)
    base = Path(tmp_path / "projects" / "default")
    _write_textured_glb(base / "p2" / "mesh.glb")

    from flux_motif_worker.engine import EsrganMissing

    class MissingEngine:
        def upscale_image(self, img, *, scale=2, tile=1024):
            raise EsrganMissing("spandrel-missing")
    monkeypatch.setattr(w, "_get", lambda: MissingEngine())

    out = w.upscale_texture.run("job2", "p2", 4)
    assert out == {"error": "esrgan-missing"}
    assert store.events["fail"] == "esrgan-missing"


def test_upscale_no_texture_fails(tmp_path, monkeypatch):
    w, store = _setup(tmp_path, monkeypatch)
    base = Path(tmp_path / "projects" / "default")
    # Dokusuz mesh (baseColorTexture yok)
    plain = base / "p3"
    plain.mkdir(parents=True)
    trimesh.creation.box(extents=(1, 1, 1)).export(str(plain / "mesh.glb"))

    import pytest
    with pytest.raises(Exception):
        w.upscale_texture.run("job3", "p3", 2)
    assert store.events["fail"]


def test_engine_load_esrgan_missing_raises():
    """spandrel kurulu değil (gateway-minimal) → _load_esrgan EsrganMissing verir,
    torch'a hiç değinmeden. Gerçek 'missing' davranışının motor-seviyesi kanıtı."""
    from flux_motif_worker.engine import EsrganMissing, FluxMotifEngine
    import pytest
    eng = FluxMotifEngine()
    with pytest.raises(EsrganMissing):
        eng._load_esrgan()
