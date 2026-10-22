"""POST /face4d — video/foto yükle, FaceAnything ile 4D yüz rekonstrüksiyonu üret.

Çıktılar mevcut/yeni projenin altına yazılır (<proje>/face4d/). family
"faceanything" -> queue faceanything-gpuN; task face4d.generate.
⚠ Lisans CC BY-NC 4.0 (registry commercial_use=False) — dahili kullanım.
"""
from __future__ import annotations

import uuid
from pathlib import Path

from common.config import get_settings
from common.engines.registry import default_gpu, get_spec, visible_gpu_set
from common.jobs import JobStore
from fastapi import (APIRouter, Depends, File, Form, HTTPException, UploadFile,
                     status)
from sqlalchemy.orm import Session

from gateway.auth import require_token
from gateway.db import get_db
from gateway.models.orm import Project
from gateway.models.schemas import GenerateOut

router = APIRouter(prefix="/face4d", dependencies=[require_token()])

_ENGINE = "faceanything-4d"
_ALLOWED_SUFFIXES = {".mp4", ".mov", ".avi", ".mkv", ".webm",
                     ".jpg", ".jpeg", ".png", ".webp"}


@router.post("", response_model=GenerateOut, status_code=status.HTTP_201_CREATED)
def face4d(
    file: UploadFile = File(...),
    project_id: str | None = Form(None),
    process_res: int = Form(504),
    process_mode: str = Form("all-at-once"),
    max_frames: int = Form(0),
    gpu: int | None = Form(None),
    db: Session = Depends(get_db),
) -> GenerateOut:
    allowed = visible_gpu_set()
    gpu = default_gpu() if gpu is None else gpu
    if gpu not in allowed:
        raise HTTPException(422, f"gpu {sorted(allowed)} içinde olmalı")
    spec = get_spec(_ENGINE)
    if not spec.available:
        raise HTTPException(422, f"{spec.label} şu an kullanılamıyor")
    if process_mode not in ("all-at-once", "one-by-one"):
        raise HTTPException(422, "process_mode all-at-once|one-by-one olmalı")

    suffix = Path(file.filename or "input.mp4").suffix.lower()
    if suffix not in _ALLOWED_SUFFIXES:
        raise HTTPException(422, f"desteklenmeyen dosya türü: {suffix}")

    settings = get_settings()
    uploads = Path(settings.uploads_dir)
    uploads.mkdir(parents=True, exist_ok=True)
    up_name = f"face4d_{uuid.uuid4().hex}{suffix}"
    (uploads / up_name).write_bytes(file.file.read())

    if project_id:
        proj = db.get(Project, project_id)
        if proj is None:
            raise HTTPException(404, "Tasarım bulunamadı")
    else:
        proj = Project(
            user_id="default",
            name=f"yuz4d-{up_name[7:15]}",
            garment_type="aksesuar",
            template_id="face4d",
            customizations={"color": "#cccccc", "decals": []},
            engine_id=_ENGINE,
        )
        db.add(proj)
        db.commit()
        db.refresh(proj)

    job_id = uuid.uuid4().hex
    JobStore().create(job_id, {"kind": "face4d", "project_id": proj.id})
    from common.celery_app import celery_app
    celery_app.send_task("face4d.generate", kwargs={
        "job_id": job_id,
        "project_id": proj.id,
        "input_path": str(uploads / up_name),
        "process_mode": process_mode,
        "process_res": process_res,
        "max_frames": max_frames or None,
    }, queue=f"faceanything-gpu{gpu}")
    return GenerateOut(job_id=job_id, project_id=proj.id)
