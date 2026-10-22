"""PartCrafter worker (ayrı venv). `image_to_3d.generate`'i partcrafter-gpuN'de dinler.

Gateway engine_id="partcrafter-image" gelince queue=partcrafter-gpuN'e yollar.
Parça-bilinçli foto→3D (TripoSG-tabanlı); parçalar tek GLB'ye birleştirilir.
"""
from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("CUDA_VISIBLE_DEVICES", os.getenv("GPU_ID", "0"))

from common.celery_app import celery_app  # noqa: E402
from common.config import get_settings  # noqa: E402
# WAL+busy_timeout paylaşılan yardımcı (eski ham sqlite3 kopyasının yerine).
from common.db_write import set_mesh_path as _set_mesh_path  # noqa: E402
from common.engines.registry import resolve_engine_params  # noqa: E402
from common.jobs import JobStore  # noqa: E402

_engine = None


def _get():
    global _engine
    if _engine is None:
        from partcrafter_worker.engine import PartCrafterImageEngine
        _engine = PartCrafterImageEngine()
    return _engine


@celery_app.task(name="image_to_3d.generate", bind=True)
def generate_image_to_3d(self, job_id: str, project_id: str, image_name: str,
                         garment_type: str = "tshirt", engine_id: str = "partcrafter-image",
                         quality: str = "balanced", advanced: dict | None = None,
                         precision: str | None = None,
                         device_mode: str | None = None) -> dict:
    store = JobStore()
    settings = get_settings()
    try:
        store.set_state(job_id, "STARTED")
        params = resolve_engine_params(engine_id, quality, advanced)
        store.set_progress(job_id, "shape", 30)
        image_path = str(Path(settings.uploads_dir) / image_name)
        mesh_file = Path(settings.projects_dir) / "default" / project_id / "mesh.glb"
        store.set_progress(job_id, "paint", 75)
        _get().generate(image_path, garment_type, params, mesh_file)
        store.set_progress(job_id, "pack", 95)
        _set_mesh_path(settings.database_url, project_id, str(mesh_file))
        store.succeed(job_id, {"project_id": project_id})
        return {"project_id": project_id}
    except Exception as exc:  # noqa: BLE001
        store.fail(job_id, str(exc))
        raise


@celery_app.task(name="engine.status")
def engine_status() -> dict:
    gpu = os.environ.get("CUDA_VISIBLE_DEVICES", "")
    rep = _engine.mem_report() if _engine else {"loaded": False, "reserved_mb": 0, "allocated_mb": 0}
    return {"gpu": gpu, "loaded": ["partcrafter-image"] if rep["loaded"] else [],
            "reserved_mb": rep["reserved_mb"], "allocated_mb": rep["allocated_mb"]}


@celery_app.task(name="engine.release")
def engine_release(mode: str = "cache") -> dict:
    global _engine
    unloaded = []
    if mode == "model" and _engine is not None:
        try:
            _engine.unload()
            unloaded.append("partcrafter-image")
        except Exception:  # noqa: BLE001
            pass
        _engine = None
    try:
        import torch
        torch.cuda.empty_cache()
    except Exception:  # noqa: BLE001
        pass
    return {"mode": mode, "unloaded": unloaded}
