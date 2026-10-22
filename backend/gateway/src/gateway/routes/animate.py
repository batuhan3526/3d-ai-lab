"""POST /animate — mevcut bir kıyafet tasarımını VideoMDM hareketiyle animasyonlu
manken üzerinde render edip animation.mp4 üretir.

Yeni proje OLUŞTURMAZ; animasyon mevcut projenin bir çıktısıdır (animation_path).
family "videomdm" -> queue videomdm-gpuN; task animate.generate.
"""
from __future__ import annotations

import uuid

from common.engines.registry import (default_gpu, get_spec,
                                     visible_gpu_set)
from common.jobs import JobStore
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from gateway.auth import require_token
from gateway.db import get_db
from gateway.models.orm import Project
from gateway.models.schemas import GenerateOut

router = APIRouter(prefix="/animate", dependencies=[require_token()])

# Bu route yalnız VideoMDM hareket motorunu kuyruğa atar (family "videomdm").
_ANIMATE_ENGINE = "videomdm-motion"


class AnimateIn(BaseModel):
    project_id: str
    text: str
    motion_length: float = 6.0
    # None → settings.default_gpu (tek-GPU sözleşmesi); görünür kümeden doğrulanır.
    gpu: int | None = None


@router.post("", response_model=GenerateOut, status_code=status.HTTP_201_CREATED)
def animate(payload: AnimateIn, db: Session = Depends(get_db)) -> GenerateOut:
    # Tek-GPU sözleşmesi: istek gpu vermezse default_gpu(); her durumda görünür
    # GPU kümesine göre doğrula. Tek-GPU host'ta küme {0}'a çöker.
    allowed = visible_gpu_set()
    gpu = default_gpu() if payload.gpu is None else payload.gpu
    if gpu not in allowed:
        raise HTTPException(422, f"gpu {sorted(allowed)} içinde olmalı")
    # Kullanılabilirlik kapısı: motor available=False ise 422 (gated/NC/placeholder).
    spec = get_spec(_ANIMATE_ENGINE)
    if not spec.available:
        raise HTTPException(422, f"{spec.label} şu an kullanılamıyor "
                                 "(lisans/gated erişim veya henüz yayınlanmadı)")
    if not payload.text.strip():
        raise HTTPException(422, "text boş olamaz")
    proj = db.get(Project, payload.project_id)
    if proj is None:
        raise HTTPException(404, "Tasarım bulunamadı")
    job_id = uuid.uuid4().hex
    JobStore().create(job_id, {"kind": "animate", "project_id": proj.id})
    from common.celery_app import celery_app
    celery_app.send_task("animate.generate", kwargs={
        "job_id": job_id,
        "project_id": proj.id,
        "text": payload.text,
        "motion_length": payload.motion_length,
    }, queue=f"videomdm-gpu{gpu}")
    return GenerateOut(job_id=job_id, project_id=proj.id)
