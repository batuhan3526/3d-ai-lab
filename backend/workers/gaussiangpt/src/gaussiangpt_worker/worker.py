"""GaussianGPT worker — Celery task'ları (otoregresif 3DGS sahne üretimi).

Task:
  scene.generate — koşulsuz sahne chunk üretimi → <proje>/gaussian_scene/
                   (orbit .gif önizleme + .pt payload + .ply dönüşümü)

Queue: gaussiangpt-gpu{N} (N = DEFAULT_GPU; tek GPU'da 0).
Sözleşme deseni: videomdm_worker/worker.py aynası. Lisans: MIT.
"""
from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("CUDA_VISIBLE_DEVICES", os.getenv("GPU_ID", "0"))

from common.celery_app import celery_app  # noqa: E402
from common.config import get_settings  # noqa: E402
from common.jobs import JobStore  # noqa: E402

_engine = None


def _get_engine():
    global _engine
    if _engine is None:
        from gaussiangpt_worker.engine import GaussianGPTEngine  # noqa: PLC0415
        _engine = GaussianGPTEngine()
    return _engine


@celery_app.task(name="scene.generate", bind=True)
def generate_scene(
    self,
    job_id: str,
    project_id: str,
    num_samples: int = 1,
    temperature: float = 1.0,
    top_k: int | None = None,
    top_p: float | None = None,
    seed: int | None = None,
) -> dict:
    """Koşulsuz 3DGS sahne chunk üretimi.

    Aşamalar: loading(10) → sampling(30) → done(95) → SUCCESS.
    Döner: {"project_id", "scene_dir", "plys": [...], "gifs": [...]}
    """
    store = JobStore()
    settings = get_settings()
    try:
        store.set_state(job_id, "STARTED")
        store.set_progress(job_id, "loading", 10)
        eng = _get_engine()

        out_dir = Path(settings.projects_dir) / "default" / project_id / "gaussian_scene"
        store.set_progress(job_id, "sampling", 30)
        eng.generate(
            out_dir=out_dir,
            num_samples=num_samples,
            temperature=temperature,
            top_k=top_k,
            top_p=top_p,
            seed=seed,
        )
        store.set_progress(job_id, "done", 95)

        result = {
            "project_id": project_id,
            "scene_dir": str(out_dir),
            "plys": sorted(str(p) for p in out_dir.rglob("*.ply")),
            "gifs": sorted(str(p) for p in out_dir.rglob("*.gif")),
        }
        store.succeed(job_id, result)
        return result
    except Exception as exc:  # noqa: BLE001
        store.fail(job_id, str(exc))
        raise


@celery_app.task(name="engine.status")
def engine_status() -> dict:
    gpu = os.environ.get("CUDA_VISIBLE_DEVICES", "")
    rep = _engine.mem_report() if _engine else {"loaded": False, "reserved_mb": 0, "allocated_mb": 0}
    return {
        "gpu": gpu,
        "loaded": ["gaussiangpt-scene"] if rep["loaded"] else [],
        "reserved_mb": rep["reserved_mb"],
        "allocated_mb": rep["allocated_mb"],
    }


@celery_app.task(name="engine.release")
def engine_release(mode: str = "cache") -> dict:
    global _engine
    unloaded: list[str] = []
    if mode == "model" and _engine is not None:
        try:
            _engine.unload()
            unloaded.append("gaussiangpt-scene")
        except Exception:  # noqa: BLE001
            pass
        _engine = None
    try:
        import torch  # noqa: PLC0415
        torch.cuda.empty_cache()
    except Exception:  # noqa: BLE001
        pass
    return {"mode": mode, "unloaded": unloaded}
