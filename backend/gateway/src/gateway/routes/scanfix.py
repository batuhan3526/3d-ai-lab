"""POST /scanfix/prepare + /scanfix — ArtiFixer tarama iyileştirme hattı.

prepare: sunucudaki COLMAP sahne dizini → 3DGRUT rekonstrüksiyon + split.json
         (<proje>/artifixer/scene). GPU ister, uzun (10k iter).
fix:     hazırlanmış sahne → düzeltilmiş kareler (<proje>/artifixer/out).
         3090'da 14B model CPU-offload'la koşar (yavaş).

family "artifixer" -> queue artifixer-gpuN. Lisans Apache-2.0 (ticari OK).
"""
from __future__ import annotations

import uuid
from pathlib import Path

from common.engines.registry import default_gpu, get_spec, visible_gpu_set
from common.jobs import JobStore
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from gateway.auth import require_token
from gateway.db import get_db
from gateway.models.orm import Project
from gateway.models.schemas import GenerateOut

router = APIRouter(prefix="/scanfix", dependencies=[require_token()])

_ENGINE = "artifixer-fix"


def _check_gpu_and_engine(gpu: int | None) -> int:
    allowed = visible_gpu_set()
    gpu = default_gpu() if gpu is None else gpu
    if gpu not in allowed:
        raise HTTPException(422, f"gpu {sorted(allowed)} içinde olmalı")
    spec = get_spec(_ENGINE)
    if not spec.available:
        raise HTTPException(422, f"{spec.label} şu an kullanılamıyor")
    return gpu


class ScanPrepareIn(BaseModel):
    # Sunucu dosya sistemindeki COLMAP sahnesi (images/ + sparse/0/). v1: yol ile.
    colmap_dir: str
    project_id: str | None = None
    selected_images_file: str | None = None
    trajectory_path: str | None = None
    gpu: int | None = None


class ScanFixIn(BaseModel):
    project_id: str
    split_path: str | None = None  # None → <proje>/artifixer/scene/split.json
    render_trajectory: str = "all_frames"
    num_inference_steps: int = 4
    gpu: int | None = None


def _get_or_create_project(db: Session, project_id: str | None, name: str) -> Project:
    if project_id:
        proj = db.get(Project, project_id)
        if proj is None:
            raise HTTPException(404, "Tasarım bulunamadı")
        return proj
    proj = Project(
        user_id="default",
        name=name,
        garment_type="aksesuar",
        template_id="scanfix",
        customizations={"color": "#cccccc", "decals": []},
        engine_id=_ENGINE,
    )
    db.add(proj)
    db.commit()
    db.refresh(proj)
    return proj


@router.post("/prepare", response_model=GenerateOut, status_code=status.HTTP_201_CREATED)
def scanfix_prepare(payload: ScanPrepareIn, db: Session = Depends(get_db)) -> GenerateOut:
    gpu = _check_gpu_and_engine(payload.gpu)
    colmap = Path(payload.colmap_dir)
    if not (colmap / "sparse").exists() or not (colmap / "images").exists():
        raise HTTPException(422, f"COLMAP sahnesi değil (images/ + sparse/ gerekli): {colmap}")

    proj = _get_or_create_project(db, payload.project_id, f"tarama-{uuid.uuid4().hex[:8]}")
    job_id = uuid.uuid4().hex
    JobStore().create(job_id, {"kind": "scanfix_prepare", "project_id": proj.id})
    from common.celery_app import celery_app
    celery_app.send_task("scanfix.prepare", kwargs={
        "job_id": job_id,
        "project_id": proj.id,
        "colmap_dir": str(colmap),
        "selected_images_file": payload.selected_images_file,
        "trajectory_path": payload.trajectory_path,
    }, queue=f"artifixer-gpu{gpu}")
    return GenerateOut(job_id=job_id, project_id=proj.id)


@router.post("", response_model=GenerateOut, status_code=status.HTTP_201_CREATED)
def scanfix(payload: ScanFixIn, db: Session = Depends(get_db)) -> GenerateOut:
    gpu = _check_gpu_and_engine(payload.gpu)
    if payload.render_trajectory not in ("val_frames", "all_frames", "trajectory"):
        raise HTTPException(422, "render_trajectory val_frames|all_frames|trajectory olmalı")
    proj = db.get(Project, payload.project_id)
    if proj is None:
        raise HTTPException(404, "Tasarım bulunamadı")

    job_id = uuid.uuid4().hex
    JobStore().create(job_id, {"kind": "scanfix", "project_id": proj.id})
    from common.celery_app import celery_app
    celery_app.send_task("scanfix.generate", kwargs={
        "job_id": job_id,
        "project_id": proj.id,
        "split_path": payload.split_path,
        "render_trajectory": payload.render_trajectory,
        "num_inference_steps": payload.num_inference_steps,
    }, queue=f"artifixer-gpu{gpu}")
    return GenerateOut(job_id=job_id, project_id=proj.id)
