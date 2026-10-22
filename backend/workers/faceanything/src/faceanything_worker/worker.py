"""FaceAnything worker — Celery task'ları (4D yüz rekonstrüksiyonu).

Task:
  face4d.generate — video/foto girdisinden 4D yüz rekonstrüksiyonu
                    (videolar + ply + kamera) → <proje>/face4d/

Queue: faceanything-gpu{N} (N = DEFAULT_GPU; tek GPU'da 0).
Sözleşme deseni: videomdm_worker/worker.py aynası.
⚠ CC BY-NC 4.0 — ticari kullanım yasak; registry commercial_use=False.
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
        from faceanything_worker.engine import FaceAnythingEngine  # noqa: PLC0415
        _engine = FaceAnythingEngine()
    return _engine


@celery_app.task(name="face4d.generate", bind=True)
def generate_face4d(
    self,
    job_id: str,
    project_id: str,
    input_path: str,
    outputs: str = "pointcloud,canonical,grandtour,ply",
    process_mode: str = "all-at-once",
    process_res: int = 504,
    max_frames: int | None = None,
) -> dict:
    """Girdi (video/foto/klasör) → 4D yüz çıktıları.

    Aşamalar: loading(10) → inference(30) → done(95) → SUCCESS.
    Döner: {"project_id", "face4d_dir", "videos": [...], "ply_count": N}
    """
    store = JobStore()
    settings = get_settings()
    try:
        store.set_state(job_id, "STARTED")
        store.set_progress(job_id, "loading", 10)
        eng = _get_engine()

        out_dir = Path(settings.projects_dir) / "default" / project_id / "face4d"
        store.set_progress(job_id, "inference", 30)
        eng.generate(
            input_path=Path(input_path),
            out_dir=out_dir,
            outputs=outputs,
            process_mode=process_mode,
            process_res=process_res,
            max_frames=max_frames,
        )
        store.set_progress(job_id, "done", 95)

        videos = sorted(str(p) for p in (out_dir / "videos").glob("*.mp4"))
        ply_count = len(list((out_dir / "ply").rglob("*.ply")))
        result = {
            "project_id": project_id,
            "face4d_dir": str(out_dir),
            "videos": videos,
            "ply_count": ply_count,
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
        "loaded": ["faceanything-4d"] if rep["loaded"] else [],
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
            unloaded.append("faceanything-4d")
        except Exception:  # noqa: BLE001
            pass
        _engine = None
    try:
        import torch  # noqa: PLC0415
        torch.cuda.empty_cache()
    except Exception:  # noqa: BLE001
        pass
    return {"mode": mode, "unloaded": unloaded}
