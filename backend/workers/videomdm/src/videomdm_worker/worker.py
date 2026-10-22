"""VideoMDM worker — Celery tasks for motion generation and garment animation.

Tasks:
  motion.generate  — text → SMPL joint-position motion (results.npy)
  animate.generate — text + project mesh.glb → animated mp4

Queue: videomdm-gpu{N}  (N = DEFAULT_GPU; 0 on a single-GPU machine)
GPU: CUDA_VISIBLE_DEVICES=1 set in the launcher / env before import.

Contract pattern mirrors hi3dgen_worker/worker.py.
"""
from __future__ import annotations

import os
import sqlite3
from pathlib import Path

# GPU selection from GPU_ID env (default 0; a 2-GPU owner sets GPU_ID=1).
os.environ.setdefault("CUDA_VISIBLE_DEVICES", os.getenv("GPU_ID", "0"))
os.environ.setdefault("PYOPENGL_PLATFORM", "egl")

from common.celery_app import celery_app  # noqa: E402
from common.config import get_settings  # noqa: E402
from common.jobs import JobStore  # noqa: E402

_motion_gen = None


def _get_motion_gen():
    global _motion_gen
    if _motion_gen is None:
        from videomdm_worker.motion import MotionGenerator  # noqa: PLC0415
        _motion_gen = MotionGenerator()
    return _motion_gen


def _set_animation_path(database_url: str, project_id: str, animation_path: str) -> None:
    """Write animation_path to the projects table.

    Mirrors common.db_write.set_mesh_path's WAL + busy_timeout safety (that shared
    helper only covers the mesh_path column, so the animation_path write keeps the
    same pragmas here to stay safe against the concurrent multi-worker writers).
    """
    prefix = "sqlite:///"
    db = database_url[len(prefix):] if database_url.startswith(prefix) else database_url
    conn = sqlite3.connect(db, timeout=5.0)
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=5000")
        conn.execute(
            "UPDATE projects SET animation_path=? WHERE id=?",
            (animation_path, project_id),
        )
        conn.commit()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Task: motion.generate
# ---------------------------------------------------------------------------

@celery_app.task(name="motion.generate", bind=True)
def generate_motion(
    self,
    job_id: str,
    project_id: str,
    text: str,
    motion_length: float = 6.0,
    guidance: float = 2.5,
    seed: int = 10,
) -> dict:
    """Generate SMPL motion from text prompt, save results.npy.

    Progress stages: loading(10) → sampling(80) → save(95) → SUCCESS.

    Returns:
        {"project_id": ..., "motion_path": "...results.npy"}
    """
    store = JobStore()
    settings = get_settings()

    try:
        store.set_state(job_id, "STARTED")
        store.set_progress(job_id, "loading", 10)

        gen = _get_motion_gen()

        out_npy = (
            Path(settings.projects_dir)
            / "default"
            / project_id
            / "motion"
            / "results.npy"
        )

        store.set_progress(job_id, "sampling", 30)
        gen.generate(
            text=text,
            out_npy=out_npy,
            motion_length=motion_length,
            guidance=guidance,
            seed=seed,
        )
        store.set_progress(job_id, "done", 95)

        store.succeed(job_id, {"project_id": project_id, "motion_path": str(out_npy)})
        return {"project_id": project_id, "motion_path": str(out_npy)}

    except Exception as exc:  # noqa: BLE001
        store.fail(job_id, str(exc))
        raise


# ---------------------------------------------------------------------------
# Task: animate.generate
# ---------------------------------------------------------------------------

@celery_app.task(name="animate.generate", bind=True)
def generate_animation(
    self,
    job_id: str,
    project_id: str,
    text: str,
    motion_length: float = 6.0,
    guidance: float = 2.5,
    seed: int = 10,
) -> dict:
    """Full pipeline: text → motion → dress garment → render → animation.mp4.

    Progress stages:
      motion(30) → dress(60) → render(90) → SUCCESS

    Returns:
        {"project_id": ..., "animation_path": "...animation.mp4"}
    """
    store = JobStore()
    settings = get_settings()

    try:
        store.set_state(job_id, "STARTED")

        project_dir = Path(settings.projects_dir) / "default" / project_id
        motion_npy = project_dir / "motion" / "results.npy"
        mesh_glb = project_dir / "mesh.glb"
        animation_mp4 = project_dir / "animation.mp4"

        # --- Stage 1: motion generation (0→30) ---
        store.set_progress(job_id, "motion", 10)
        gen = _get_motion_gen()
        gen.generate(
            text=text,
            out_npy=motion_npy,
            motion_length=motion_length,
            guidance=guidance,
            seed=seed,
        )
        store.set_progress(job_id, "motion", 30)

        # --- Stage 2: dressing (30→60) ---
        store.set_progress(job_id, "dress", 40)
        # Lazy import — dressing only needs numpy/scipy, no GPU
        import numpy as np  # noqa: PLC0415
        from videomdm_worker.dressing import apply_lbs, transfer_skin_weights  # noqa: PLC0415

        # results.npy is produced locally by this process — pickle is safe here.
        results = np.load(str(motion_npy), allow_pickle=True).item()
        # motion: (1, njoints, 3, nframes)
        # For v1: garment skinning is a best-effort stub until full SMPL
        # per-frame transforms are wired in from smplx forward pass.
        # TODO: replace with real SMPL A-matrices from Rotation2xyz output.
        store.set_progress(job_id, "dress", 60)

        # --- Stage 3: render (60→90) ---
        store.set_progress(job_id, "render", 65)
        from videomdm_worker.render import render_motion_mp4  # noqa: PLC0415

        render_motion_mp4(
            motion_npy=motion_npy,
            garment_glb=mesh_glb if mesh_glb.exists() else None,
            out_mp4=animation_mp4,
        )
        store.set_progress(job_id, "render", 90)

        # --- Persist path ---
        _set_animation_path(settings.database_url, project_id, str(animation_mp4))
        store.succeed(job_id, {"project_id": project_id, "animation_path": str(animation_mp4)})
        return {"project_id": project_id, "animation_path": str(animation_mp4)}

    except Exception as exc:  # noqa: BLE001
        store.fail(job_id, str(exc))
        raise


# ---------------------------------------------------------------------------
# Engine management tasks (mirror hi3dgen_worker pattern)
# ---------------------------------------------------------------------------

@celery_app.task(name="engine.status")
def engine_status() -> dict:
    gpu = os.environ.get("CUDA_VISIBLE_DEVICES", "")
    rep = _motion_gen.mem_report() if _motion_gen else {
        "loaded": False, "reserved_mb": 0, "allocated_mb": 0
    }
    return {
        "gpu": gpu,
        "loaded": ["videomdm-motion"] if rep["loaded"] else [],
        "reserved_mb": rep["reserved_mb"],
        "allocated_mb": rep["allocated_mb"],
    }


@celery_app.task(name="engine.release")
def engine_release(mode: str = "cache") -> dict:
    global _motion_gen
    unloaded: list[str] = []

    if mode == "model" and _motion_gen is not None:
        try:
            _motion_gen.unload()
            unloaded.append("videomdm-motion")
        except Exception:  # noqa: BLE001
            pass
        _motion_gen = None

    try:
        import torch  # noqa: PLC0415
        torch.cuda.empty_cache()
    except Exception:  # noqa: BLE001
        pass

    return {"mode": mode, "unloaded": unloaded}
