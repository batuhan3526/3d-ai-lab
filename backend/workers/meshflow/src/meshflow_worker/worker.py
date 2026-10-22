"""MeshFlow worker — `mesh_refine.generate` Celery task.

Listens on queue `meshflow-gpuN`. Routes to MeshFlowRefineEngine or
MeshFlowGuidedEngine based on engine_id. Also exposes engine.status and
engine.release tasks (scoped to this queue, no cross-worker conflicts).
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

_refine_engine = None
_guided_engine = None


def _refine():
    global _refine_engine
    if _refine_engine is None:
        from meshflow_worker.engine_refine import MeshFlowRefineEngine
        _refine_engine = MeshFlowRefineEngine()
    return _refine_engine


def _guided():
    global _guided_engine
    if _guided_engine is None:
        from meshflow_worker.engine_guided import MeshFlowGuidedEngine
        _guided_engine = MeshFlowGuidedEngine()
    return _guided_engine


@celery_app.task(name="mesh_refine.generate", bind=True)
def mesh_refine(
    self,
    job_id: str,
    project_id: str,
    engine_id: str = "meshflow-refine",
    quality: str = "balanced",
    advanced: dict | None = None,
    ref_image_name: str | None = None,
) -> dict:
    """
    Refine (or guided-refine) an existing project mesh.

    The project's current mesh.glb is read, processed, and written back
    (in-place overwrite). db mesh_path is updated after success.

    engine_id="meshflow-refine"  → MeshFlowRefineEngine (no image needed)
    engine_id="meshflow-guided"  → MeshFlowGuidedEngine (ref_image_name optional)
    """
    store = JobStore()
    settings = get_settings()
    try:
        store.set_state(job_id, "STARTED")
        params = resolve_engine_params(engine_id, quality, advanced)

        proj_dir = Path(settings.projects_dir) / "default" / project_id
        mesh_in = proj_dir / "mesh.glb"
        if not mesh_in.exists():
            raise FileNotFoundError(f"Source mesh not found: {mesh_in}")

        store.set_progress(job_id, "shape", 40)

        out = proj_dir / "mesh.glb"  # in-place refine

        if engine_id == "meshflow-guided":
            eng = _guided()
            img_path = (
                str(Path(settings.uploads_dir) / ref_image_name)
                if ref_image_name
                else None
            )
            eng.generate(str(mesh_in), img_path, params, out)
        else:
            _refine().generate(str(mesh_in), "", params, out)

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
    loaded_names = []
    rep = {"loaded": False, "reserved_mb": 0, "allocated_mb": 0}
    if _refine_engine is not None:
        r = _refine_engine.mem_report()
        if r["loaded"]:
            loaded_names.append("meshflow-refine")
            rep = r
    if _guided_engine is not None:
        r = _guided_engine.mem_report()
        if r["loaded"]:
            loaded_names.append("meshflow-guided")
            rep = r
    return {
        "gpu": gpu,
        "loaded": loaded_names,
        "reserved_mb": rep["reserved_mb"],
        "allocated_mb": rep["allocated_mb"],
    }


@celery_app.task(name="engine.release")
def engine_release(mode: str = "cache") -> dict:
    global _refine_engine, _guided_engine
    unloaded = []
    if mode == "model":
        for name, eng, var in [
            ("meshflow-refine", _refine_engine, "_refine_engine"),
            ("meshflow-guided", _guided_engine, "_guided_engine"),
        ]:
            if eng is not None:
                try:
                    eng.unload()
                    unloaded.append(name)
                except Exception:  # noqa: BLE001
                    pass
        _refine_engine = None
        _guided_engine = None
    try:
        import torch
        torch.cuda.empty_cache()
    except Exception:  # noqa: BLE001
        pass
    return {"mode": mode, "unloaded": unloaded}
