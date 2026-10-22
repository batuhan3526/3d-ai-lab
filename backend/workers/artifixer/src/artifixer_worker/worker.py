"""ArtiFixer worker — Celery task'ları (3D tarama artefakt düzeltme).

Task'lar:
  scanfix.prepare  — COLMAP sahnesi → 3DGRUT + split.json (<proje>/artifixer/scene)
  scanfix.generate — hazırlanmış sahne → düzeltilmiş kareler (<proje>/artifixer/out)

Queue: artifixer-gpu{N} (N = DEFAULT_GPU; tek GPU'da 0).
3090 notu: 14B model CPU-offload ile koşar (run_inference_offload) — yavaş ama çalışır.
Sözleşme deseni: videomdm_worker/worker.py aynası. Lisans: Apache-2.0 (ticari OK).
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
        from artifixer_worker.engine import ArtiFixerEngine  # noqa: PLC0415
        _engine = ArtiFixerEngine()
    return _engine


@celery_app.task(name="scanfix.prepare", bind=True)
def prepare_scene(
    self,
    job_id: str,
    project_id: str,
    colmap_dir: str,
    selected_images_file: str | None = None,
    trajectory_path: str | None = None,
) -> dict:
    """COLMAP sahnesini ArtiFixer girdisine hazırla (3DGRUT 10k iter — uzun, GPU).

    Aşamalar: loading(10) → reconstruct(30) → done(95) → SUCCESS.
    Döner: {"project_id", "scene_root", "split_path"}
    """
    store = JobStore()
    settings = get_settings()
    try:
        store.set_state(job_id, "STARTED")
        store.set_progress(job_id, "loading", 10)
        eng = _get_engine()

        scene_root = Path(settings.projects_dir) / "default" / project_id / "artifixer" / "scene"
        store.set_progress(job_id, "reconstruct", 30)
        split = eng.prepare(
            colmap_dir=Path(colmap_dir),
            output_root=scene_root,
            selected_images_file=Path(selected_images_file) if selected_images_file else None,
            trajectory_path=Path(trajectory_path) if trajectory_path else None,
        )
        store.set_progress(job_id, "done", 95)
        result = {"project_id": project_id, "scene_root": str(scene_root),
                  "split_path": str(split)}
        store.succeed(job_id, result)
        return result
    except Exception as exc:  # noqa: BLE001
        store.fail(job_id, str(exc))
        raise


@celery_app.task(name="scanfix.generate", bind=True)
def fix_scene(
    self,
    job_id: str,
    project_id: str,
    split_path: str | None = None,
    render_trajectory: str = "all_frames",
    num_inference_steps: int = 4,
) -> dict:
    """Hazırlanmış sahneyi ArtiFixer'dan geçir (14B, CPU-offload'lu — yavaş).

    split_path verilmezse <proje>/artifixer/scene/split.json kullanılır.
    Aşamalar: loading(10) → diffusion(30) → done(95) → SUCCESS.
    Döner: {"project_id", "out_dir", "pred_frames": N}
    """
    store = JobStore()
    settings = get_settings()
    try:
        store.set_state(job_id, "STARTED")
        store.set_progress(job_id, "loading", 10)
        eng = _get_engine()

        proj_dir = Path(settings.projects_dir) / "default" / project_id / "artifixer"
        split = Path(split_path) if split_path else proj_dir / "scene" / "split.json"
        if not split.exists():
            raise FileNotFoundError(f"split.json yok (önce scanfix.prepare koştur): {split}")

        out_dir = proj_dir / "out"
        store.set_progress(job_id, "diffusion", 30)
        eng.fix(split_path=split, save_dir=out_dir,
                render_trajectory=render_trajectory,
                num_inference_steps=num_inference_steps)
        store.set_progress(job_id, "done", 95)

        pred_frames = len(list(out_dir.rglob("pred/*.png")))
        result = {"project_id": project_id, "out_dir": str(out_dir),
                  "pred_frames": pred_frames}
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
        "loaded": ["artifixer-fix"] if rep["loaded"] else [],
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
            unloaded.append("artifixer-fix")
        except Exception:  # noqa: BLE001
            pass
        _engine = None
    try:
        import torch  # noqa: PLC0415
        torch.cuda.empty_cache()
    except Exception:  # noqa: BLE001
        pass
    return {"mode": mode, "unloaded": unloaded}
