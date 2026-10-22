"""Hunyuan worker (ayrı venv). `image_to_3d.generate`'i hunyuan-gpuN queue'sunda dinler.

Gateway, engine_id="hunyuan-image" gelince queue=hunyuan-gpuN'e yollar; bu worker
consume eder. TRELLIS worker'la aynı task adını kullanır ama farklı queue'da dinler
(routing queue ile yapılır). common (broker/jobs/params) PYTHONPATH ile import edilir.
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

_ENGINES: dict[str, object] = {}


def _make_engine(engine_id: str):
    if engine_id == "hunyuan-image":
        from hunyuan_worker.engine import HunyuanImageEngine
        return HunyuanImageEngine()
    if engine_id == "hunyuan-textured":
        from hunyuan_worker.engine_textured import HunyuanTexturedEngine
        return HunyuanTexturedEngine()
    if engine_id == "hunyuan-mv":
        from hunyuan_worker.engine_mv import HunyuanMVEngine
        return HunyuanMVEngine()
    raise ValueError(f"Bu worker'da yok: {engine_id}")


def _get(engine_id: str = "hunyuan-image"):
    """Tek-resident: istenen dışındaki motorları boşalt (textured aşaması neredeyse
    tüm GPU'yu kullandığından shape-only motorla aynı anda yüklü kalmamalı)."""
    for eid in list(_ENGINES):
        if eid != engine_id:
            try:
                _ENGINES[eid].unload()
            except Exception:  # noqa: BLE001
                pass
            del _ENGINES[eid]
    if engine_id not in _ENGINES:
        _ENGINES[engine_id] = _make_engine(engine_id)
    return _ENGINES[engine_id]


@celery_app.task(name="image_to_3d.generate", bind=True)
def generate_image_to_3d(self, job_id: str, project_id: str, image_name: str,
                         garment_type: str = "tshirt", engine_id: str = "hunyuan-image",
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
        _get(engine_id).generate(image_path, garment_type, params, mesh_file)
        store.set_progress(job_id, "pack", 95)
        _set_mesh_path(settings.database_url, project_id, str(mesh_file))
        store.succeed(job_id, {"project_id": project_id})
        return {"project_id": project_id}
    except Exception as exc:  # noqa: BLE001
        store.fail(job_id, str(exc))
        raise


@celery_app.task(name="multi_image_to_3d.generate", bind=True)
def generate_multi_image_to_3d(self, job_id: str, project_id: str,
                                image_names: list[str],
                                garment_type: str = "tshirt",
                                engine_id: str = "hunyuan-mv",
                                quality: str = "balanced",
                                advanced: dict | None = None,
                                precision: str | None = None,
                                device_mode: str | None = None) -> dict:
    store = JobStore()
    settings = get_settings()
    try:
        store.set_state(job_id, "STARTED")
        params = resolve_engine_params(engine_id, quality, advanced)
        store.set_progress(job_id, "shape", 30)
        image_paths = [str(Path(settings.uploads_dir) / name) for name in image_names]
        mesh_file = Path(settings.projects_dir) / "default" / project_id / "mesh.glb"
        store.set_progress(job_id, "paint", 75)
        _get(engine_id).generate(image_paths, garment_type, params, mesh_file)
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
    loaded = [eid for eid, e in _ENGINES.items() if getattr(e, "is_loaded", lambda: False)()]
    reserved = allocated = 0
    try:
        import torch
        if torch.cuda.is_available():
            reserved = int(torch.cuda.memory_reserved() / 1024 / 1024)
            allocated = int(torch.cuda.memory_allocated() / 1024 / 1024)
    except Exception:  # noqa: BLE001
        pass
    return {"gpu": gpu, "loaded": loaded, "reserved_mb": reserved, "allocated_mb": allocated}


@celery_app.task(name="engine.release")
def engine_release(mode: str = "cache") -> dict:
    unloaded = []
    if mode == "model":
        for eid, e in list(_ENGINES.items()):
            try:
                e.unload()
                unloaded.append(eid)
            except Exception:  # noqa: BLE001
                pass
        _ENGINES.clear()
    try:
        import torch
        torch.cuda.empty_cache()
    except Exception:  # noqa: BLE001
        pass
    return {"mode": mode, "unloaded": unloaded}
