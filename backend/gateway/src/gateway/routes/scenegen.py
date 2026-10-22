"""POST /scenegen — GaussianGPT ile koşulsuz 3DGS sahne chunk üretimi.

Yeni proje oluşturur; çıktılar <proje>/gaussian_scene/ altına (.gif önizleme +
.pt/.ply). family "gaussiangpt" -> queue gaussiangpt-gpuN; task scene.generate.
Lisans MIT (ticari OK).
"""
from __future__ import annotations

import uuid

from common.engines.registry import default_gpu, get_spec, visible_gpu_set
from common.jobs import JobStore
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from gateway.auth import require_token
from gateway.db import get_db
from gateway.models.orm import Project
from gateway.models.schemas import GenerateOut

router = APIRouter(prefix="/scenegen", dependencies=[require_token()])

_ENGINE = "gaussiangpt-scene"


class SceneGenIn(BaseModel):
    num_samples: int = 1
    temperature: float = 1.0
    top_k: int | None = None
    top_p: float | None = None
    seed: int | None = None
    gpu: int | None = None


@router.post("", response_model=GenerateOut, status_code=status.HTTP_201_CREATED)
def scenegen(payload: SceneGenIn, db: Session = Depends(get_db)) -> GenerateOut:
    allowed = visible_gpu_set()
    gpu = default_gpu() if payload.gpu is None else payload.gpu
    if gpu not in allowed:
        raise HTTPException(422, f"gpu {sorted(allowed)} içinde olmalı")
    spec = get_spec(_ENGINE)
    if not spec.available:
        raise HTTPException(422, f"{spec.label} şu an kullanılamıyor")
    if not 1 <= payload.num_samples <= 8:
        raise HTTPException(422, "num_samples 1..8 olmalı")

    proj = Project(
        user_id="default",
        name=f"sahne-{uuid.uuid4().hex[:8]}",
        garment_type="aksesuar",
        template_id="gaussian-scene",
        customizations={"color": "#cccccc", "decals": []},
        engine_id=_ENGINE,
    )
    db.add(proj)
    db.commit()
    db.refresh(proj)

    job_id = uuid.uuid4().hex
    JobStore().create(job_id, {"kind": "scenegen", "project_id": proj.id})
    from common.celery_app import celery_app
    celery_app.send_task("scene.generate", kwargs={
        "job_id": job_id,
        "project_id": proj.id,
        "num_samples": payload.num_samples,
        "temperature": payload.temperature,
        "top_k": payload.top_k,
        "top_p": payload.top_p,
        "seed": payload.seed,
    }, queue=f"gaussiangpt-gpu{gpu}")
    return GenerateOut(job_id=job_id, project_id=proj.id)
