"""Bulut worker çekirdeği: matte, GLB, anahtar maskeleme, poll, görev akışı (ağ YOK)."""
from __future__ import annotations

import io
import pathlib
import sys

import fakeredis
import numpy as np
import pytest
from PIL import Image

_SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from cloud_worker import http, postprocess  # noqa: E402


def _png(arr: np.ndarray, mode: str = "RGB") -> bytes:
    buf = io.BytesIO()
    Image.fromarray(arr, mode).save(buf, "PNG")
    return buf.getvalue()


def test_matte_removes_white_background_keeps_inner_white(tmp_path):
    a = np.full((64, 64, 3), 255, np.uint8)
    a[16:48, 16:48] = 0            # siyah kare (motif)
    a[28:36, 28:36] = 255          # motifin İÇİNDE beyaz delik: kenara bağlı değil → kalır
    out = postprocess.to_rgba_motif(_png(a), tmp_path / "m.png")
    al = np.asarray(Image.open(out))[:, :, 3]
    assert al[0, 0] == 0 and al[20, 20] == 255 and al[30, 30] == 255


def test_matte_keeps_provider_alpha(tmp_path):
    a = np.zeros((32, 32, 4), np.uint8)
    a[8:24, 8:24] = [200, 10, 10, 255]
    out = postprocess.to_rgba_motif(_png(a, "RGBA"), tmp_path / "m.png")
    al = np.asarray(Image.open(out))[:, :, 3]
    assert al[0, 0] == 0 and al[16, 16] == 255


def test_to_glb_passthrough_and_convert(tmp_path):
    import trimesh
    box = trimesh.creation.box()
    glb = trimesh.Scene(box).export(file_type="glb")
    p = postprocess.to_glb(glb, tmp_path / "a" / "mesh.glb")
    assert p.read_bytes()[:4] == b"glTF"
    obj = box.export(file_type="obj").encode()
    p2 = postprocess.to_glb(obj, tmp_path / "b" / "mesh.glb", "obj")
    assert p2.read_bytes()[:4] == b"glTF"


def test_errors_redact_keys():
    import httpx
    key = http.register_secret("sk-SECRET-999")
    resp = httpx.Response(401, text=f"bad key {key}", request=httpx.Request("GET", "https://x"))
    with pytest.raises(http.CloudError) as e:
        http.check(resp, "Tripo")
    assert "sk-SECRET-999" not in str(e.value) and "geçersiz" in str(e.value)


def test_poll_done_failed_timeout(monkeypatch):
    monkeypatch.setattr(http.time, "sleep", lambda s: None)
    seq = iter([{"s": "run"}, {"s": "run"}, {"s": "ok"}])
    out = http.poll(lambda: next(seq), lambda d: d["s"] == "ok", lambda d: None, provider="X")
    assert out["s"] == "ok"
    with pytest.raises(http.CloudError):
        http.poll(lambda: {"s": "bad"}, lambda d: False, lambda d: "boom", provider="X")
    with pytest.raises(http.CloudError):
        http.poll(lambda: {"s": "run"}, lambda d: False, lambda d: None, provider="X", timeout=-1)


@pytest.fixture
def worker_env(tmp_path, monkeypatch):
    monkeypatch.setenv("PROJECTS_DIR", str(tmp_path / "projects"))
    monkeypatch.setenv("UPLOADS_DIR", str(tmp_path / "up"))
    monkeypatch.setenv("TRIPO_API_KEY", "sk-tripo-test")
    monkeypatch.setenv("OPENAI_API_KEY", "")
    from common.config import get_settings
    get_settings.cache_clear()
    from cloud_worker import worker
    store_r = fakeredis.FakeStrictRedis(decode_responses=True)
    from common.jobs import JobStore
    monkeypatch.setattr(worker, "JobStore", lambda: JobStore(store_r))
    meshes = {}
    monkeypatch.setattr(worker, "_set_mesh_path", lambda db, pid, path: meshes.update({pid: path}))
    yield worker, store_r, meshes, tmp_path
    get_settings.cache_clear()


def test_text_task_writes_glb_and_succeeds(worker_env, monkeypatch):
    worker, r, meshes, tmp = worker_env
    import trimesh
    glb = trimesh.Scene(trimesh.creation.box()).export(file_type="glb")
    seen = {}

    def fake(engine_id, prompt, params, key, tick=None):
        seen.update(engine_id=engine_id, prompt=prompt, key=key, params=params)
        tick(50)
        return glb, "glb"
    monkeypatch.setattr(worker.catalog, "text_to_3d", fake)
    worker.generate_text_to_3d.run(job_id="j1", project_id="p1", prompt="red hoodie",
                                   engine_id="cloud-tripo-text", quality="quality",
                                   prompt_enhance=False)
    assert r.hgetall("job:j1")["state"] == "SUCCESS"
    assert pathlib.Path(meshes["p1"]).read_bytes()[:4] == b"glTF"
    assert seen["key"] == "sk-tripo-test" and seen["params"]["detail"] == "high"


def test_image_task_keeps_input_as_ref_image(worker_env, monkeypatch):
    """UltraTex/Hi3D 'tasarımın kendi görseli'ni ref_image.png'den alır."""
    worker, r, meshes, tmp = worker_env
    import trimesh
    from PIL import Image
    (tmp / "up").mkdir()
    Image.new("RGB", (16, 16), "red").save(tmp / "up" / "in.jpg")
    glb = trimesh.Scene(trimesh.creation.box()).export(file_type="glb")
    monkeypatch.setattr(worker.catalog, "image_to_3d", lambda *a, **k: (glb, "glb"))
    worker.generate_image_to_3d.run(job_id="j3", project_id="p2", image_name="in.jpg",
                                    engine_id="cloud-tripo-image")
    assert r.hgetall("job:j3")["state"] == "SUCCESS"
    ref = pathlib.Path(meshes["p2"]).parent / "ref_image.png"
    assert Image.open(ref).getpixel((0, 0))[0] > 240  # JPEG kaynağı: ~kırmızı


def test_missing_key_fails_with_turkish_hint(worker_env):
    worker, r, _, _ = worker_env
    with pytest.raises(http.CloudError):
        worker.generate_motif.run(job_id="j2", project_id="p1", prompt="dragon",
                                  engine_id="cloud-openai-image", prompt_enhance=False)
    job = r.hgetall("job:j2")
    assert job["state"] == "FAILURE" and "OPENAI_API_KEY" in job["error"]


def test_motif_task_mattes_provider_png(worker_env, monkeypatch):
    worker, r, _, tmp = worker_env
    monkeypatch.setenv("OPENAI_API_KEY", "sk-oa")
    from common.config import get_settings
    get_settings.cache_clear()
    a = np.full((40, 40, 3), 255, np.uint8)
    a[10:30, 10:30] = 0
    monkeypatch.setattr(worker.catalog, "text_to_image", lambda *a_, **k: _png(a))
    res = worker.generate_motif.run(job_id="j3", project_id="p1", prompt="dragon",
                                    engine_id="cloud-openai-image", prompt_enhance=False)
    png = tmp / "projects" / "default" / "p1" / res["decal_path"]
    assert np.asarray(Image.open(png))[0, 0, 3] == 0
    assert r.hgetall("job:j3")["state"] == "SUCCESS"


def test_catalog_covers_registry():
    from cloud_worker.providers import catalog
    from common.engines.registry import list_specs
    cloud = {s["id"] for s in list_specs() if s["id"].startswith("cloud-")}
    assert cloud == catalog.engine_ids()
