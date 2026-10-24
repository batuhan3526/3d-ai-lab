"""UltraTex worker (ayrı conda ortamı). `texture_image.generate`'i ultratex-gpuN kuyruğunda dinler.

Mevcut bir projenin mesh'ini referans görsele göre yeniden dokular (geometri aynı kalır):
gateway /generate/retexture-image yeni proje açar, bu görev sonucu onun mesh.glb'sine
yazar. Referans: yüklenen görsel, yoksa kaynak projenin ref_image.png'si. İki GPU varsa
metin kodlayıcı öbür GPU'da çalışır (9B DiT + 8B kodlayıcı tek 24 GB karta sığmaz).
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path


def _visible_gpus() -> str:
    gid = os.getenv("GPU_ID", "0")
    try:
        n = len(subprocess.run(["nvidia-smi", "-L"], capture_output=True, text=True, timeout=10).stdout.splitlines())
    except (OSError, subprocess.SubprocessError):
        n = 1
    others = [str(i) for i in range(n) if str(i) != gid]
    return ",".join([gid] + others[:1])


os.environ.setdefault("CUDA_VISIBLE_DEVICES", _visible_gpus())

from common.celery_app import celery_app  # noqa: E402
from common.config import get_settings  # noqa: E402
from common.db_write import set_mesh_path as _set_mesh_path  # noqa: E402
from common.engines.registry import resolve_engine_params  # noqa: E402
from common.jobs import JobStore  # noqa: E402

_engine = None


def _get():
    global _engine
    if _engine is None:
        from ultratex_worker.engine import UltraTexEngine
        _engine = UltraTexEngine()
    return _engine


@celery_app.task(name="texture_image.generate", bind=True)
def generate_texture(self, job_id: str, project_id: str, source_project_id: str,
                     image_name: str | None = None, engine_id: str = "ultratex-retexture",
                     quality: str = "balanced", advanced: dict | None = None) -> dict:
    store = JobStore()
    settings = get_settings()
    try:
        store.set_state(job_id, "STARTED")
        params = resolve_engine_params(engine_id, quality, advanced)
        base = Path(settings.projects_dir) / "default"
        src = base / source_project_id / "mesh.glb"
        if not src.exists():
            raise RuntimeError("Kaynak projede mesh yok.")
        ref = Path(settings.uploads_dir) / image_name if image_name else base / source_project_id / "ref_image.png"
        if not ref.exists():
            raise RuntimeError("Referans görsel yok: bir görsel yükleyin (kaynak projede ref_image.png da yok).")
        store.set_progress(job_id, "texture", 30)
        out = base / project_id / "mesh.glb"
        _get().retexture(str(src), str(ref), params, out)
        store.set_progress(job_id, "pack", 95)
        _set_mesh_path(settings.database_url, project_id, str(out))
        store.succeed(job_id, {"project_id": project_id})
        return {"project_id": project_id}
    except Exception as exc:  # noqa: BLE001
        store.fail(job_id, str(exc))
        raise


@celery_app.task(name="engine.status")
def engine_status() -> dict:
    gpu = os.environ.get("CUDA_VISIBLE_DEVICES", "")
    rep = _engine.mem_report() if _engine else {"loaded": False, "reserved_mb": 0, "allocated_mb": 0}
    return {"gpu": gpu, "loaded": ["ultratex-retexture"] if rep["loaded"] else [],
            "reserved_mb": rep["reserved_mb"], "allocated_mb": rep["allocated_mb"]}


@celery_app.task(name="engine.release")
def engine_release(mode: str = "cache") -> dict:
    try:
        import torch
        torch.cuda.empty_cache()
    except Exception:  # noqa: BLE001
        pass
    return {"mode": mode, "unloaded": []}
