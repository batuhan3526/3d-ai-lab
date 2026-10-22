"""text_to_3d Celery worker.

M1: gerçek model YOK. Aşamalar progress ile simüle edilir; placeholder olarak
garment_type'ın ilk template GLB'si projenin mesh.glb'sine kopyalanır. M2'de
Hunyuan3D-Shape, M3'te Paint bu task'ın içine girer (GPU 0 lock ile).
"""
from __future__ import annotations

import shutil
import time
from pathlib import Path

from common.celery_app import celery_app
from common.config import get_settings
from common.jobs import JobStore

_stage_delay = 0.6  # M1 simülasyon; M2'de gerçek inference süresi


def _job_store() -> JobStore:
    return JobStore()


def _first_template_glb(garment_type: str) -> Path:
    tdir = Path(get_settings().templates_dir) / garment_type
    glbs = sorted(tdir.glob("*.glb"))
    if not glbs:
        raise FileNotFoundError(f"{garment_type} için template GLB yok")
    return glbs[0]


def _set_mesh_path(project_id: str, mesh_path: str) -> None:
    from gateway.db import get_sessionmaker
    from gateway.models.orm import Project
    with get_sessionmaker()() as s:
        proj = s.get(Project, project_id)
        if proj:
            proj.mesh_path = mesh_path
            s.commit()


@celery_app.task(name="text_to_3d.generate", bind=True)
def generate_text_to_3d(self, job_id: str, project_id: str,
                        prompt: str = "", garment_type: str = "tshirt",
                        engine_id: str = "trellis-text", quality: str = "balanced",
                        advanced: dict | None = None, prompt_enhance: bool = True,
                        prompt_en: str | None = None) -> dict:
    text = prompt or prompt_en or ""
    _ = (text, engine_id, quality, advanced, prompt_enhance)
    store = _job_store()
    try:
        store.set_state(job_id, "STARTED")
        for stage, pct in (("shape", 30), ("paint", 70), ("pack", 95)):
            store.set_progress(job_id, stage, pct)
            time.sleep(_stage_delay)
        settings = get_settings()
        out_dir = Path(settings.projects_dir) / "default" / project_id
        out_dir.mkdir(parents=True, exist_ok=True)
        mesh_path = out_dir / "mesh.glb"
        shutil.copyfile(_first_template_glb(garment_type), mesh_path)
        _set_mesh_path(project_id, str(mesh_path))
        store.succeed(job_id, {"project_id": project_id})
        return {"project_id": project_id}
    except Exception as exc:  # noqa: BLE001
        store.fail(job_id, str(exc))
        raise
