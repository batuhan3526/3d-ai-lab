"""POST /projects/{id}/drape — offline kumaş simülasyonu (Blender headless).

BEST-EFFORT: kaynak projenin mesh'ini manken üstüne fizik-tabanlı düşürür
(Blender cloth sim, N frame) ve sonucu YENİ VARYANT olarak kaydeder — varyasyon
galerisi deseni (Variation satırı + lazy reconcile GET /variations okurken).
Worker sonuç yolunu `decal_path` altında döndürür ki mevcut reconcile onu
result_path'e yazsın (variations.py'ye dokunmadan).

Blender binary yoksa worker task FAILURE(error="blender-missing") verir; kurulum
README'de (apt install blender). Kuyruk: `clothsim-cpu` (GPU YOK — tek-GPU
sözleşmesi ETKİLENMEZ).
"""
from __future__ import annotations

import uuid
from pathlib import Path

from common.fabrics import fabric_ids, get_fabric
from common.jobs import JobStore
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from gateway.auth import require_token
from gateway.db import get_db
from gateway.models.orm import Project, Variation

router = APIRouter(prefix="/projects", dependencies=[require_token()])


class DrapeIn(BaseModel):
    """mannequin_id opsiyonel (verilmezse worker basit yer-düzlemi collider kullanır);
    frames = simülasyon kare sayısı (yüksek = daha oturmuş kumaş, daha yavaş);
    fabric_id opsiyonel kumaş hazır ayarı (GET /fabrics; verilmezse eski denim)."""
    mannequin_id: str | None = None
    frames: int = 40
    fabric_id: str | None = None


class DrapeOut(BaseModel):
    job_id: str
    variation_id: str
    group_id: str
    project_id: str


def _job_store() -> JobStore:
    return JobStore()


@router.post("/{project_id}/drape", response_model=DrapeOut,
             status_code=status.HTTP_201_CREATED)
def drape(project_id: str, payload: DrapeIn,
          db: Session = Depends(get_db)) -> DrapeOut:
    proj = db.get(Project, project_id)
    if proj is None:
        raise HTTPException(404, "Tasarım bulunamadı")
    if payload.frames < 2 or payload.frames > 240:
        raise HTTPException(422, "frames 2..240 aralığında olmalı")
    if payload.fabric_id and get_fabric(payload.fabric_id) is None:
        raise HTTPException(422, f"Bilinmeyen kumaş: '{payload.fabric_id}'. "
                                 f"Şunlardan birini seçin: {', '.join(fabric_ids())}")

    group_id = uuid.uuid4().hex
    job_id = uuid.uuid4().hex
    # Varyasyon deseni: SUBMITTED satır; sonuç GET /variations okurken uzlaşır.
    # seed alanı non-nullable → drape'te anlamsız, frame sayısını sakla.
    var = Variation(
        group_id=group_id, project_id=proj.id, kind="drape", seed=payload.frames,
        prompt=None, job_id=job_id, status="SUBMITTED",
    )
    db.add(var)
    db.flush()  # var.id
    _job_store().create(job_id, {"kind": "drape", "project_id": proj.id,
                                 "variation_id": var.id, "group_id": group_id})
    from common.celery_app import celery_app
    celery_app.send_task("clothsim.drape", kwargs={
        "job_id": job_id,
        "project_id": proj.id,
        "mannequin_id": payload.mannequin_id,
        "frames": payload.frames,
        "fabric_id": payload.fabric_id or None,
    }, queue="clothsim-cpu")
    db.commit()
    return DrapeOut(job_id=job_id, variation_id=var.id, group_id=group_id,
                    project_id=proj.id)


class FitIn(BaseModel):
    """Mankene giydir.
    - mannequin_id: kullanılacak manken (verilmezse projenin kayıtlı mankeni, o da yoksa
      kadın taban manken). body: {gender, height_cm, chest_cm, waist_cm, hip_cm} verilirse
      bu ölçülerde manken bulunur/üretilir (terzi ölçüsü).
    - transform: verilirse o hiza (elle ince ayar); verilmezse kıyafetten OTOMATİK.
    - auto_apply: sonuç onay beklemeden projeye uygulanır (mesh yedeklenir).
    - margin: kumaşın beden yüzeyinden minimum uzaklığı (kıyafet birimi)."""
    margin: float = 0.012
    mannequin_id: str | None = None
    body: dict | None = None
    transform: dict | None = None
    auto_apply: bool = False


@router.post("/{project_id}/fit", response_model=DrapeOut,
             status_code=status.HTTP_201_CREATED)
def fit(project_id: str, payload: FitIn | None = None,
        db: Session = Depends(get_db)) -> DrapeOut:
    """Mankene giydir: otomatik hiza + kol pozu + oturtma + terzi ölçü tablosu. Sonuç
    varyant (galeri / "Projeye uygula"); auto_apply ile doğrudan projeye uygulanır."""
    from gateway import dressing
    proj = db.get(Project, project_id)
    if proj is None:
        raise HTTPException(404, "Tasarım bulunamadı")
    body = payload or FitIn()
    dressing.require_dressable(proj.garment_type)
    if not (0.0 <= body.margin <= 0.1):
        raise HTTPException(422, "margin 0..0.1 aralığında olmalı")
    saved = dict((proj.customizations or {}).get("mannequin") or {})
    mid = dressing.resolve_mannequin(
        {"body": body.body} if body.body else {"mannequin_id": body.mannequin_id or saved.get("id")})
    group_id = uuid.uuid4().hex
    job_id = uuid.uuid4().hex
    var = Variation(group_id=group_id, project_id=proj.id, kind="fit", seed=0,
                    prompt=None, job_id=job_id, status="SUBMITTED")
    db.add(var)
    db.flush()
    _job_store().create(job_id, {"kind": "fit", "project_id": proj.id,
                                 "variation_id": var.id, "group_id": group_id})
    from common.celery_app import celery_app
    celery_app.send_task("clothsim.fit", kwargs=dressing.fit_kwargs(
        job_id, proj.id, mid, proj.garment_type, transform=body.transform, margin=body.margin,
        auto_apply=body.auto_apply), queue="clothsim-cpu")
    db.commit()
    return DrapeOut(job_id=job_id, variation_id=var.id, group_id=group_id, project_id=proj.id)


@router.get("/{project_id}/measurements")
def measurements(project_id: str, db: Session = Depends(get_db)) -> dict:
    """Son giydirmenin terzi ölçü tablosu (cm): kıyafet, beden ve bolluk payı."""
    proj = db.get(Project, project_id)
    if proj is None:
        raise HTTPException(404, "Tasarım bulunamadı")
    m = (proj.customizations or {}).get("measurements")
    if not m:
        from common.config import get_settings
        f = Path(get_settings().projects_dir) / "default" / project_id / "measurements.json"
        if f.exists():
            import json
            m = json.loads(f.read_text(encoding="utf-8"))
    if not m:
        raise HTTPException(404, "Ölçü tablosu yok — önce mankene giydirin.")
    return m
