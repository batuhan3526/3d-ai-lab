"""POST /projects/{id}/upscale-texture — Real-ESRGAN doku netleştirme (upscale).

BEST-EFFORT: kaynak projenin mesh dokusunu (baseColorTexture) Real-ESRGAN ile
büyütüp keskinleştirir ve sonucu YENİ VARYANT olarak kaydeder — varyasyon galerisi
deseni (Variation satırı + lazy reconcile GET /variations okurken). Worker sonuç
yolunu `decal_path` altında döndürür ki mevcut reconcile onu result_path'e yazsın
(variations.py'ye dokunmadan). Kaynak mesh/DB DEĞİŞMEZ.

FLUX worker'ının GPU'sunda çalışır: kuyruk `flux-gpu{gpu}` (default_gpu() ile tek-GPU
sözleşmesi; istek `gpu` verirse görünür kümeden doğrulanır). spandrel/ESRGAN ağırlığı
yoksa worker task FAILURE(error="esrgan-missing") verir; kurulum README/LICENSES'te.
"""
from __future__ import annotations

import uuid

from common.engines.registry import default_gpu, visible_gpu_set
from common.jobs import JobStore
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from gateway.auth import require_token
from gateway.db import get_db
from gateway.models.orm import Project, Variation

router = APIRouter(prefix="/projects", dependencies=[require_token()])


class UpscaleIn(BaseModel):
    """scale = doku çözünürlük çarpanı (2 veya 4). Default 4 = native ESRGAN x4
    çıktısı (resize yok) → gözle görülür netleşme. None → default_gpu (tek-GPU)."""
    scale: int = 4
    gpu: int | None = None


class UpscaleOut(BaseModel):
    job_id: str
    variation_id: str
    group_id: str
    project_id: str


def _job_store() -> JobStore:
    return JobStore()


@router.post("/{project_id}/upscale-texture", response_model=UpscaleOut,
             status_code=status.HTTP_201_CREATED)
def upscale_texture(project_id: str, payload: UpscaleIn,
                    db: Session = Depends(get_db)) -> UpscaleOut:
    proj = db.get(Project, project_id)
    if proj is None:
        raise HTTPException(404, "Tasarım bulunamadı")
    if payload.scale not in (2, 4):
        raise HTTPException(422, "scale 2 veya 4 olmalı")
    # Tek-GPU sözleşmesi: istek gpu vermezse default_gpu(); her durumda görünür
    # GPU kümesine göre doğrula. Tek-GPU host'ta küme {0}'a çöker.
    allowed = visible_gpu_set()
    gpu = default_gpu() if payload.gpu is None else payload.gpu
    if gpu not in allowed:
        raise HTTPException(422, f"gpu {sorted(allowed)} içinde olmalı")

    group_id = uuid.uuid4().hex
    job_id = uuid.uuid4().hex
    # Varyasyon deseni: SUBMITTED satır; sonuç GET /variations okurken uzlaşır.
    # seed alanı non-nullable → upscale'de anlamsız, ölçek çarpanını sakla.
    var = Variation(
        group_id=group_id, project_id=proj.id, kind="upscale", seed=payload.scale,
        prompt=None, job_id=job_id, status="SUBMITTED",
    )
    db.add(var)
    db.flush()  # var.id
    _job_store().create(job_id, {"kind": "upscale", "project_id": proj.id,
                                 "variation_id": var.id, "group_id": group_id})
    from common.celery_app import celery_app
    celery_app.send_task("texture.upscale", kwargs={
        "job_id": job_id,
        "project_id": proj.id,
        "scale": payload.scale,
    }, queue=f"flux-gpu{gpu}")
    db.commit()
    return UpscaleOut(job_id=job_id, variation_id=var.id, group_id=group_id,
                      project_id=proj.id)
