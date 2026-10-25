"""Hi3D worker (ayrı venv). `mesh_refine.generate`'i hi3d-gpuN kuyruğunda dinler.

Kaynak projenin mesh'ini referans görsele göre inceltir, sonucu gateway'in açtığı yeni projeye
yazar (kaynak korunur). Hi3D yalnız geometri üretir: `retexture` açıksa aynı iş UltraTex
kuyruğuna devredilir ve inceltilmiş mesh referans görselle yeniden dokulanır (tek iş kimliği,
ilerleme kaldığı yerden sürer).
"""
from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("CUDA_VISIBLE_DEVICES", os.getenv("GPU_ID", "0"))

from common.celery_app import celery_app  # noqa: E402
from common.config import get_settings  # noqa: E402
from common.db_write import set_mesh_path as _set_mesh_path  # noqa: E402
from common.engines.registry import resolve_engine_params  # noqa: E402
from common.jobs import JobStore  # noqa: E402

_engine = None


def _get():
    global _engine
    if _engine is None:
        from hi3d_worker.engine import Hi3DEngine
        _engine = Hi3DEngine()
    return _engine


@celery_app.task(name="mesh_refine.generate", bind=True)
def mesh_refine(self, job_id: str, project_id: str, source_project_id: str,
                engine_id: str = "hi3d-refine", quality: str = "balanced",
                advanced: dict | None = None, ref_image_name: str | None = None,
                retexture_queue: str | None = None) -> dict:
    store = JobStore()
    settings = get_settings()
    try:
        store.set_state(job_id, "STARTED")
        params = resolve_engine_params(engine_id, quality, advanced)
        base = Path(settings.projects_dir) / "default"
        src = base / source_project_id / "mesh.glb"
        if not src.exists():
            raise RuntimeError("Kaynak projede mesh yok.")
        ref = (Path(settings.uploads_dir) / ref_image_name if ref_image_name
               else base / source_project_id / "ref_image.png")
        if not ref.exists():
            raise RuntimeError("Referans görsel yok: bir görsel yükleyin (kaynak projede ref_image.png da yok).")
        store.set_progress(job_id, "shape", 20)
        out = base / project_id / "mesh.glb"
        _get().refine(str(src), str(ref), params, out)
        _set_mesh_path(settings.database_url, project_id, str(out))
        if retexture_queue:
            store.set_progress(job_id, "texture", 50)
            celery_app.send_task("texture_image.generate", kwargs={
                "job_id": job_id, "project_id": project_id, "source_project_id": project_id,
                "image_name": ref_image_name,     # yoksa gateway'in kopyaladığı ref_image.png
            }, queue=retexture_queue)
            return {"project_id": project_id, "retexture": retexture_queue}
        store.set_progress(job_id, "pack", 95)
        store.succeed(job_id, {"project_id": project_id})
        return {"project_id": project_id}
    except Exception as exc:  # noqa: BLE001
        store.fail(job_id, str(exc))
        raise


@celery_app.task(name="engine.status")
def engine_status() -> dict:
    gpu = os.environ.get("CUDA_VISIBLE_DEVICES", "")
    rep = _engine.mem_report() if _engine else {"loaded": False, "reserved_mb": 0, "allocated_mb": 0}
    return {"gpu": gpu, "loaded": ["hi3d-refine"] if rep["loaded"] else [],
            "reserved_mb": rep["reserved_mb"], "allocated_mb": rep["allocated_mb"]}


@celery_app.task(name="engine.release")
def engine_release(mode: str = "cache") -> dict:
    unloaded = []
    if _engine is not None and _engine.is_loaded():
        _engine.unload()
        unloaded.append("hi3d-refine")
    return {"mode": mode, "unloaded": unloaded}
