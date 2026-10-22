"""POST /patterns/{id}/sew3d — 2D kalıbı 3D'de mankene dik (F2).

F1'in ürettiği kalıp parçaları (data/patterns/<id>/pieces.json) Blender kumaş
simülasyonunda (dikiş yayları) seçilen mankenin üstüne dikilir; sonuç YENİ BİR PROJE
olarak kaydedilir → Dashboard'da görünür, Designer'da açılır (generate deseni:
Project satırı + job + kuyruk; worker mesh.glb + thumbnail.png yazar, mesh_path'i
DB'ye işler; mesh_view.glb'yi gateway ilk açılışta lazy üretir).

Kuyruk: `clothsim-cpu` (GPU YOK — tek-GPU sözleşmesi ETKİLENMEZ).
"""
from __future__ import annotations

import json
import re
import uuid
from pathlib import Path

from common.config import get_settings
from common.fabrics import fabric_ids, get_fabric
from common.jobs import JobStore
from common.patterns import PatternError, pattern_path, public_catalog, read_meta
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from gateway.auth import require_token
from gateway.db import get_db
from gateway.models.orm import Project

router = APIRouter(prefix="/patterns", dependencies=[require_token()])

_USER = "default"
_MANNEQUIN_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
FRAMES_MIN, FRAMES_MAX = 10, 240

# Tasarım → proje kıyafet türü (Dashboard/Designer garment_type; GARMENT_TYPES içinden).
_GARMENT_BY_DESIGN = {
    "teagan": "tshirt", "aaron": "tshirt", "sven": "shirt", "hugo": "shirt", "simon": "shirt",
    "bella": "shirt", "penelope": "skirt", "sandy": "skirt", "titan": "pants", "lily": "pants",
    "waralee": "pants",
}
_GARMENT_BY_CATEGORY = {"ust": "tshirt", "alt": "pants"}


class Sew3dIn(BaseModel):
    """mannequin_id zorunlu (GET /templates/mannequins; ölçüden üretilen custom-* dahil);
    fabric_id (GET /fabrics) varsayılan pamuk; frames = simülasyon kare sayısı."""
    mannequin_id: str
    fabric_id: str = "cotton"
    frames: int = 120


class Sew3dOut(BaseModel):
    job_id: str
    project_id: str


def _job_store() -> JobStore:
    return JobStore()


def _sew3d_designs_tr() -> str:
    names = [d["label_tr"] for d in public_catalog() if d.get("sew3d")]
    return ", ".join(names) if names else "-"


@router.post("/{pattern_id}/sew3d", response_model=Sew3dOut,
             status_code=status.HTTP_201_CREATED)
def sew3d(pattern_id: str, payload: Sew3dIn, db: Session = Depends(get_db)) -> Sew3dOut:
    try:
        meta = read_meta(pattern_id)
        pieces_file = pattern_path(pattern_id) / "pieces.json"
    except PatternError as exc:
        raise HTTPException(exc.status, str(exc)) from None
    if not pieces_file.is_file():
        raise HTTPException(404, "Kalıp dosyası eksik. Kalıbı yeniden oluşturun.")
    try:
        pieces = json.loads(pieces_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        raise HTTPException(404, "Kalıp dosyası okunamadı. Kalıbı yeniden oluşturun.") from None
    label = meta.get("label_tr") or meta.get("design") or "Kalıp"
    if not meta.get("sew3d") or not pieces.get("seams"):
        raise HTTPException(
            422, f"'{label}' kalıbı henüz 3D'de dikilemiyor. 3D dikiş şu an şu tasarımlarda var: "
                 f"{_sew3d_designs_tr()}.")

    mid = (payload.mannequin_id or "").strip()
    if not mid:
        raise HTTPException(422, "Bir manken seçin.")
    mann = Path(get_settings().templates_dir) / "mannequins" / f"{mid}.glb"
    if not _MANNEQUIN_RE.match(mid) or not mann.is_file():
        raise HTTPException(422, "Seçilen manken bulunamadı. Listeden bir manken seçin.")
    fabric = get_fabric(payload.fabric_id)
    if fabric is None:
        raise HTTPException(422, f"Bilinmeyen kumaş: '{payload.fabric_id}'. "
                                 f"Şunlardan birini seçin: {', '.join(fabric_ids())}")
    if not (FRAMES_MIN <= payload.frames <= FRAMES_MAX):
        raise HTTPException(422, f"Simülasyon kare sayısı {FRAMES_MIN} ile {FRAMES_MAX} "
                                 "arasında olmalı (önerilen 120).")

    design = meta.get("design") or pieces.get("design") or ""
    garment = _GARMENT_BY_DESIGN.get(design) or _GARMENT_BY_CATEGORY.get(meta.get("category"), "model")
    proj = Project(
        user_id=_USER,
        name=f"{label} (kalıptan)"[:200],
        garment_type=garment,
        template_id=f"pattern-{pattern_id}"[:64],
        customizations={
            "color": (fabric.get("pbr") or {}).get("base_color", "#cccccc"),
            "decals": [],
            # Designer kumaş görünümü (frontend FABRIC_MATERIAL_PREFIX sözleşmesi).
            "material": f"fabric:{fabric['id']}",
            "sew3d": {"pattern_id": pattern_id, "design": design,
                      "mannequin_id": mid, "fabric_id": fabric["id"], "frames": payload.frames},
        },
        engine_id="sew3d",
    )
    db.add(proj)
    db.commit()
    db.refresh(proj)

    job_id = uuid.uuid4().hex
    _job_store().create(job_id, {"kind": "sew3d", "project_id": proj.id, "pattern_id": pattern_id})
    from common.celery_app import celery_app
    celery_app.send_task("clothsim.sew3d", kwargs={
        "job_id": job_id,
        "project_id": proj.id,
        "pattern_id": pattern_id,
        "mannequin_id": mid,
        "fabric_id": fabric["id"],
        "frames": payload.frames,
    }, queue="clothsim-cpu")
    return Sew3dOut(job_id=job_id, project_id=proj.id)
