"""POST /generate/text — Project + job oluştur, seçilen GPU queue'suna enqueue.

Çeviri ARTIK BURADA YAPILMAZ; worker (GPU yanında) prompt_enhance açıksa
çevirir + tek-nesne kalıbına sokar. Bkz. M-A tasarım Bölüm 5.
"""
from __future__ import annotations

import json
import random
import re
import shutil
import uuid
from pathlib import Path

from common.config import get_settings
from common.engines.registry import (engine_family, get_spec, queue_for, spec_available,
                                     resolve_engine_params, visible_gpu_set)
from common.jobs import JobStore
from common.safety import SafetyBlocked, enforce
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from gateway.auth import require_token
from gateway.db import get_db
from gateway.models.orm import Project, Variation
from gateway.models.schemas import (BatchIn, BatchJobOut, BatchOut,
                                     GARMENT_TYPES, GenerateOut, GenerateTextIn,
                                     MotifBakeIn, MotifIn, RetextureIn, TileIn)

router = APIRouter(prefix="/generate", dependencies=[require_token()])
# Foto ön-kırpma (C1): POST korumalı; sonuç PNG'sini <img src> ile göstermek için
# GET token'sız (thumbnail/decal servisiyle tutarlı). UUID adres + regex path-traversal koruması.
preprocess_router = APIRouter(prefix="/preprocess", dependencies=[require_token()])
preprocess_public_router = APIRouter(prefix="/preprocess")

_MATTE_NAME_RE = re.compile(r"matte_[A-Za-z0-9]+\.png")

_USER = "default"


def _job_store() -> JobStore:
    return JobStore()


def _resolve_gpu(gpu: int | None) -> int:
    """Tek-GPU sözleşmesi: istek gpu vermezse settings.default_gpu; her durumda
    görünür GPU kümesine göre doğrula. Tek-GPU host'ta küme {0}'a çöker."""
    allowed = visible_gpu_set()
    if gpu is None:
        gpu = get_settings().default_gpu
    if gpu not in allowed:
        raise HTTPException(422, f"gpu {sorted(allowed)} içinde olmalı")
    return gpu


def _require_available(engine_id: str):
    """engine_id kayıtlı + kullanılabilir mi? Değilse 422 (gated/NC/placeholder)."""
    try:
        spec = get_spec(engine_id)
    except KeyError:
        raise HTTPException(422, f"Bilinmeyen motor: {engine_id}") from None
    if not spec_available(spec):
        if spec.requires_key and spec.available:
            raise HTTPException(422, f"{spec.label} için API anahtarı ayarlı değil "
                                     f"({spec.requires_key} — .env'e ekleyip servisleri yeniden başlatın)")
        raise HTTPException(422, f"{spec.label} şu an kullanılamıyor "
                                 "(lisans/gated erişim veya henüz yayınlanmadı)")
    return spec


def _dress_link(proj: Project, mid: str | None) -> tuple[str | None, object | None]:
    """Üretimle birlikte giydirme istendiyse → (giydirme iş kimliği, Celery link)."""
    if mid is None:
        return None, None
    from gateway import dressing
    return dressing.dress_after(_job_store(), proj.id, proj.garment_type, mid)


def _motif_route(engine_id: str, gpu: int) -> tuple[str, dict]:
    """Motif motoru → (kuyruk, ek kwargs). Yerel FLUX worker'ın imzası değişmesin diye
    engine_id yalnız bulut motorlarına gönderilir."""
    spec = _require_available(engine_id)
    if "motif" not in spec.capabilities:
        raise HTTPException(422, f"{spec.label} motif üretemez")
    extra = {"engine_id": engine_id} if spec.requires_key else {}
    return queue_for(engine_id, gpu), extra


def _enqueue(*, gpu: int, job_id: str, project_id: str, prompt: str,
             garment_type: str, engine_id: str, quality: str,
             advanced: dict | None, prompt_enhance: bool,
             precision: str | None = None, device_mode: str | None = None,
             link=None) -> None:
    from common.celery_app import celery_app

    celery_app.send_task(
        "text_to_3d.generate",
        kwargs={
            "job_id": job_id,
            "project_id": project_id,
            "prompt": prompt,
            "garment_type": garment_type,
            "engine_id": engine_id,
            "quality": quality,
            "advanced": advanced,
            "prompt_enhance": prompt_enhance,
            "precision": precision,
            "device_mode": device_mode,
        },
        queue=queue_for(engine_id, gpu),
        **({"link": link} if link is not None else {}),
    )


@router.post("/text", response_model=GenerateOut, status_code=status.HTTP_201_CREATED)
def generate_text(payload: GenerateTextIn, db: Session = Depends(get_db)) -> GenerateOut:
    from gateway import dressing
    dress_mid = dressing.prepare(payload.garment_type, payload.dress)
    proj = Project(
        user_id=_USER,
        name=payload.prompt[:60],
        garment_type=payload.garment_type,
        template_id="generated",
        customizations={"color": "#cccccc", "decals": []},
        engine_id=payload.engine_id,
    )
    db.add(proj)
    db.commit()
    db.refresh(proj)
    job_id = uuid.uuid4().hex
    _job_store().create(job_id, {"kind": "text", "project_id": proj.id})
    dress_job, link = _dress_link(proj, dress_mid)
    _enqueue(link=link,
        gpu=payload.gpu,
        job_id=job_id,
        project_id=proj.id,
        prompt=payload.prompt,
        garment_type=payload.garment_type,
        engine_id=payload.engine_id,
        quality=payload.quality,
        advanced=payload.advanced,
        prompt_enhance=payload.prompt_enhance,
        precision=payload.precision,
        device_mode=payload.device_mode,
    )
    return GenerateOut(job_id=job_id, project_id=proj.id, dress_job_id=dress_job)


@router.post("/image", response_model=GenerateOut, status_code=status.HTTP_201_CREATED)
def generate_image(
    file: UploadFile = File(...),
    garment_type: str = Form(...),
    gpu: int | None = Form(None),
    quality: str = Form("balanced"),
    advanced: str | None = Form(None),
    engine_id: str = Form("trellis-image"),
    precision: str | None = Form(None),
    device_mode: str | None = Form(None),
    dress: str | None = Form(None),
    db: Session = Depends(get_db),
) -> GenerateOut:
    if garment_type not in GARMENT_TYPES:
        raise HTTPException(422, f"Bilinmeyen tür: {garment_type}")
    from gateway import dressing
    dress_mid = dressing.prepare(garment_type, dress)
    gpu = _resolve_gpu(gpu)
    _require_available(engine_id)
    try:
        adv = json.loads(advanced) if advanced else None
    except (ValueError, TypeError):
        raise HTTPException(422, "advanced geçerli JSON değil") from None
    try:
        resolve_engine_params(engine_id, quality, adv)
    except ValueError as e:
        raise HTTPException(422, str(e)) from None

    settings = get_settings()
    uploads = Path(settings.uploads_dir)
    uploads.mkdir(parents=True, exist_ok=True)
    img_id = uuid.uuid4().hex
    suffix = Path(file.filename or "img.png").suffix or ".png"
    img_name = f"{img_id}{suffix}"
    (uploads / img_name).write_bytes(file.file.read())
    # Opsiyonel NSFW taraması (SAFETY_FILTER=off → sıfır ek yük).
    try:
        enforce(uploads / img_name, context="upload")
    except SafetyBlocked as e:
        (uploads / img_name).unlink(missing_ok=True)
        raise HTTPException(422, "İçerik güvenlik filtresine takıldı") from e

    proj = Project(
        user_id=_USER,
        name=f"foto-{img_id[:8]}",
        garment_type=garment_type,
        template_id="generated-image",
        customizations={"color": "#cccccc", "decals": []},
        engine_id=engine_id,
    )
    db.add(proj)
    db.commit()
    db.refresh(proj)
    job_id = uuid.uuid4().hex
    _job_store().create(job_id, {"kind": "image", "project_id": proj.id})
    dress_job, link = _dress_link(proj, dress_mid)
    from common.celery_app import celery_app
    family = engine_family(engine_id)
    # DOKULU mod (trellis2) ayrı conda-env worker'da (torch2.6) ayrı kuyrukta çalışır;
    # poisson .venv worker'ı (torch2.12) trellis2 import edemez, bu yüzden ayrılır.
    if family == "worldtracing" and resolve_engine_params(engine_id, quality, adv).get("mode") == "trellis2":
        family = "worldtracing2"
    celery_app.send_task("image_to_3d.generate", kwargs={
        "job_id": job_id, "project_id": proj.id, "image_name": img_name,
        "garment_type": garment_type, "engine_id": engine_id,
        "quality": quality, "advanced": adv,
        "precision": precision, "device_mode": device_mode,
    }, queue=f"{family}-gpu{gpu}" if family == "worldtracing2" else queue_for(engine_id, gpu),
        **({"link": link} if link is not None else {}))
    return GenerateOut(job_id=job_id, project_id=proj.id, dress_job_id=dress_job)


@router.post("/multi-image", response_model=GenerateOut, status_code=status.HTTP_201_CREATED)
def generate_multi_image(
    files: list[UploadFile] = File(...),
    garment_type: str = Form(...),
    gpu: int | None = Form(None),
    quality: str = Form("balanced"),
    advanced: str | None = Form(None),
    engine_id: str = Form("trellis-image"),
    precision: str | None = Form(None),
    device_mode: str | None = Form(None),
    dress: str | None = Form(None),
    db: Session = Depends(get_db),
) -> GenerateOut:
    if not files:
        raise HTTPException(422, "En az bir görsel gerekli")
    if garment_type not in GARMENT_TYPES:
        raise HTTPException(422, f"Bilinmeyen tür: {garment_type}")
    from gateway import dressing
    dress_mid = dressing.prepare(garment_type, dress)
    gpu = _resolve_gpu(gpu)
    try:
        adv = json.loads(advanced) if advanced else None
    except (ValueError, TypeError):
        raise HTTPException(422, "advanced geçerli JSON değil") from None
    # SESSİZ FALLBACK YOK: motor çoklu-foto desteklemiyorsa açık hata ver.
    # (Önceden engine_id yok sayılıp her şey trellis-image'a gidiyordu.)
    spec = _require_available(engine_id)
    if "multi-image-to-3d" not in spec.capabilities:
        raise HTTPException(
            422, f"{spec.label} çoklu fotoğraf desteklemiyor — tek fotoğraf yükleyin "
                 "veya çoklu-foto için TRELLIS Foto→3D seçin.")
    try:
        resolve_engine_params(engine_id, quality, adv)
    except ValueError as e:
        raise HTTPException(422, str(e)) from None

    settings = get_settings()
    uploads = Path(settings.uploads_dir)
    uploads.mkdir(parents=True, exist_ok=True)
    base = uuid.uuid4().hex
    names = []
    for i, f in enumerate(files):
        suffix = Path(f.filename or f"img{i}.png").suffix or ".png"
        name = f"{base}_{i}{suffix}"
        (uploads / name).write_bytes(f.file.read())
        # Opsiyonel NSFW taraması (SAFETY_FILTER=off → sıfır ek yük).
        try:
            enforce(uploads / name, context="upload")
        except SafetyBlocked as e:
            (uploads / name).unlink(missing_ok=True)
            raise HTTPException(422, "İçerik güvenlik filtresine takıldı") from e
        names.append(name)

    proj = Project(
        user_id=_USER,
        name=f"multifoto-{base[:8]}",
        garment_type=garment_type,
        template_id="generated-multi-image",
        customizations={"color": "#cccccc", "decals": []},
        engine_id=engine_id,
    )
    db.add(proj)
    db.commit()
    db.refresh(proj)
    job_id = uuid.uuid4().hex
    _job_store().create(job_id, {"kind": "multi-image", "project_id": proj.id})
    dress_job, link = _dress_link(proj, dress_mid)
    from common.celery_app import celery_app
    celery_app.send_task("multi_image_to_3d.generate", kwargs={
        "job_id": job_id, "project_id": proj.id, "image_names": names,
        "garment_type": garment_type, "engine_id": engine_id,
        "quality": quality, "advanced": adv,
        "precision": precision, "device_mode": device_mode,
    }, queue=queue_for(engine_id, gpu), **({"link": link} if link is not None else {}))
    return GenerateOut(job_id=job_id, project_id=proj.id, dress_job_id=dress_job)


@router.post("/retexture", response_model=GenerateOut, status_code=status.HTTP_201_CREATED)
def retexture(payload: RetextureIn, db: Session = Depends(get_db)) -> GenerateOut:
    src = db.get(Project, payload.source_project_id)
    if src is None:
        raise HTTPException(404, "Kaynak tasarım bulunamadı")
    proj = Project(
        user_id=_USER,
        name=f"retexture: {payload.prompt[:40]}",
        garment_type=src.garment_type,
        template_id="retextured",
        customizations={"color": "#cccccc", "decals": []},
    )
    db.add(proj)
    db.commit()
    db.refresh(proj)
    job_id = uuid.uuid4().hex
    _job_store().create(job_id, {"kind": "retexture", "project_id": proj.id})
    from common.celery_app import celery_app
    celery_app.send_task("texture_edit.generate", kwargs={
        "job_id": job_id,
        "project_id": proj.id,
        "source_project_id": payload.source_project_id,
        "prompt": payload.prompt,
        "prompt_enhance": payload.prompt_enhance,
    }, queue=f"intex-gpu{payload.gpu}")
    return GenerateOut(job_id=job_id, project_id=proj.id)


@router.post("/retexture-image", response_model=GenerateOut, status_code=status.HTTP_201_CREATED)
def retexture_image(
    source_project_id: str = Form(...),
    file: UploadFile | None = File(None),
    engine_id: str = Form("ultratex-retexture"),
    gpu: int | None = Form(None),
    quality: str = Form("balanced"),
    advanced: str | None = Form(None),
    db: Session = Depends(get_db),
) -> GenerateOut:
    """Görselden doku (UltraTex): kaynak projenin mesh'i referans görsele göre yeniden
    dokulanır, şekil değişmez. Görsel yüklenmezse kaynak projenin konsept görseli kullanılır.
    Yeni proje kaynağın manken/ölçü ayarlarını devralır (geometri aynı → giydirme geçerli)."""
    src = db.get(Project, source_project_id)
    if src is None:
        raise HTTPException(404, "Kaynak tasarım bulunamadı")
    spec = _require_available(engine_id)
    if "image-retexture" not in spec.capabilities:
        raise HTTPException(422, f"{spec.label} görselden doku üretemez")
    gpu = _resolve_gpu(gpu)
    try:
        adv = json.loads(advanced) if advanced else None
        resolve_engine_params(engine_id, quality, adv)
    except (ValueError, TypeError) as e:
        raise HTTPException(422, str(e)) from None
    settings = get_settings()
    img_name = None
    if file is not None:
        uploads = Path(settings.uploads_dir)
        uploads.mkdir(parents=True, exist_ok=True)
        img_name = f"{uuid.uuid4().hex}{Path(file.filename or 'ref.png').suffix or '.png'}"
        (uploads / img_name).write_bytes(file.file.read())
        try:
            enforce(uploads / img_name, context="upload")
        except SafetyBlocked as e:
            (uploads / img_name).unlink(missing_ok=True)
            raise HTTPException(422, "İçerik güvenlik filtresine takıldı") from e
    elif not (Path(settings.projects_dir) / _USER / src.id / "ref_image.png").exists():
        raise HTTPException(422, "Referans görsel yükleyin (kaynak projede konsept görsel yok).")
    proj = Project(
        user_id=_USER,
        name=f"doku: {src.name}"[:60],
        garment_type=src.garment_type,
        template_id="retextured",
        customizations=dict(src.customizations or {}),
        engine_id=engine_id,
    )
    db.add(proj)
    db.commit()
    db.refresh(proj)
    # pozlu manken dosyası kaynak projenin klasöründe → yeni projeye de kopyala
    posed = ((proj.customizations or {}).get("mannequin") or {}).get("posed")
    if posed:
        base = Path(settings.projects_dir) / _USER
        s_var, d_var = base / src.id / "variations" / posed, base / proj.id / "variations" / posed
        if s_var.exists():
            d_var.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(s_var, d_var)
    job_id = uuid.uuid4().hex
    _job_store().create(job_id, {"kind": "retexture", "project_id": proj.id})
    from common.celery_app import celery_app
    celery_app.send_task("texture_image.generate", kwargs={
        "job_id": job_id, "project_id": proj.id, "source_project_id": src.id,
        "image_name": img_name, "engine_id": engine_id, "quality": quality, "advanced": adv,
    }, queue=queue_for(engine_id, gpu))
    return GenerateOut(job_id=job_id, project_id=proj.id)


@router.post("/motif", response_model=GenerateOut, status_code=status.HTTP_201_CREATED)
def generate_motif(payload: MotifIn, db: Session = Depends(get_db)) -> GenerateOut:
    """İşaretli bölgeye motif: FLUX ile 2D motif üret + matte -> mevcut projenin
    decals/ dizinine şeffaf PNG. Yeni proje OLUŞTURMAZ; frontend sonucu decal
    olarak işaretli bölgenin merkez+normaline yerleştirir. job sonucu decal_path verir."""
    proj = db.get(Project, payload.project_id)
    if proj is None:
        raise HTTPException(404, "Tasarım bulunamadı")
    queue, extra = _motif_route(payload.engine_id, payload.gpu)
    job_id = uuid.uuid4().hex
    _job_store().create(job_id, {"kind": "motif", "project_id": proj.id})
    from common.celery_app import celery_app
    celery_app.send_task("motif.generate", kwargs={
        "job_id": job_id,
        "project_id": proj.id,
        "prompt": payload.prompt,
        "prompt_enhance": payload.prompt_enhance,
        "style": payload.style.model_dump() if payload.style else None,
        **extra,
    }, queue=queue)
    return GenerateOut(job_id=job_id, project_id=proj.id)


@router.post("/style-upload", status_code=status.HTTP_201_CREATED)
def style_upload(file: UploadFile = File(...)) -> dict:
    """Stil transferi kaynağı görseli yükle → uploads → image_name döner."""
    settings = get_settings()
    uploads = Path(settings.uploads_dir)
    uploads.mkdir(parents=True, exist_ok=True)
    suffix = Path(file.filename or "style.png").suffix or ".png"
    name = f"style_{uuid.uuid4().hex}{suffix}"
    (uploads / name).write_bytes(file.file.read())
    return {"image_name": name}


@router.post("/motif-bake", response_model=GenerateOut, status_code=status.HTTP_201_CREATED)
def generate_motif_bake(payload: MotifBakeIn, db: Session = Depends(get_db)) -> GenerateOut:
    """İşaretli bölgeye motif DOKU olarak (FLUX + projeksiyon-bake). retexture gibi
    YENİ proje üretir (texture dokuya pişer); frontend progress sayfasına gider."""
    src = db.get(Project, payload.source_project_id)
    if src is None:
        raise HTTPException(404, "Kaynak tasarım bulunamadı")
    queue, extra = _motif_route(payload.engine_id, payload.gpu)
    proj = Project(
        user_id=_USER,
        name=f"doku-motif: {payload.prompt[:32]}",
        garment_type=src.garment_type,
        template_id="motif-baked",
        customizations={"color": "#ffffff", "decals": []},
    )
    db.add(proj)
    db.commit()
    db.refresh(proj)
    job_id = uuid.uuid4().hex
    _job_store().create(job_id, {"kind": "motif-bake", "project_id": proj.id})
    from common.celery_app import celery_app
    celery_app.send_task("motif.bake", kwargs={
        "job_id": job_id,
        "project_id": proj.id,
        "source_project_id": payload.source_project_id,
        "prompt": payload.prompt,
        "center": payload.center,
        "normal": payload.normal,
        "scale": payload.scale,
        "prompt_enhance": payload.prompt_enhance,
        "style": payload.style.model_dump() if payload.style else None,
        # BATCH-F: opsiyonel PBR kanalları (yoksa None → worker bugünkü davranış).
        "channels": payload.channels.model_dump() if payload.channels else None,
        **extra,
    }, queue=queue)
    return GenerateOut(job_id=job_id, project_id=proj.id)


@router.post("/retexture-region", response_model=GenerateOut, status_code=status.HTTP_201_CREATED)
def retexture_region(
    mask: UploadFile = File(...),
    source_project_id: str = Form(...),
    prompt: str = Form(...),
    gpu: int | None = Form(None),
    prompt_enhance: bool = Form(True),
    db: Session = Depends(get_db),
) -> GenerateOut:
    """F5 v2: SADECE işaretli UV bölgesini yeniden dokula. mask = UV-uzayı PNG
    (beyaz=yeniden boya, siyah=koru); frontend 3D fırçadan üretir. Geri kalan doku korunur."""
    gpu = _resolve_gpu(gpu)
    if not prompt.strip():
        raise HTTPException(422, "prompt boş olamaz")
    src = db.get(Project, source_project_id)
    if src is None:
        raise HTTPException(404, "Kaynak tasarım bulunamadı")

    settings = get_settings()
    uploads = Path(settings.uploads_dir)
    uploads.mkdir(parents=True, exist_ok=True)
    mask_name = f"mask_{uuid.uuid4().hex}.png"
    (uploads / mask_name).write_bytes(mask.file.read())

    proj = Project(
        user_id=_USER,
        name=f"bölge-retexture: {prompt[:32]}",
        garment_type=src.garment_type,
        template_id="retextured-region",
        customizations={"color": "#cccccc", "decals": []},
    )
    db.add(proj)
    db.commit()
    db.refresh(proj)
    job_id = uuid.uuid4().hex
    _job_store().create(job_id, {"kind": "retexture-region", "project_id": proj.id})
    from common.celery_app import celery_app
    celery_app.send_task("texture_edit.generate", kwargs={
        "job_id": job_id,
        "project_id": proj.id,
        "source_project_id": source_project_id,
        "prompt": prompt,
        "prompt_enhance": prompt_enhance,
        "mask_name": mask_name,
    }, queue=f"intex-gpu{gpu}")
    return GenerateOut(job_id=job_id, project_id=proj.id)


@router.post("/tile", response_model=GenerateOut, status_code=status.HTTP_201_CREATED)
def generate_tile(payload: TileIn, db: Session = Depends(get_db)) -> GenerateOut:
    """Motifi N×N döşeyip kumaşın UV texture'ına pişir (tam-UV). retexture gibi YENİ
    proje; tile.bake task'ı flux-gpu kuyruğuna (saf PIL+trimesh, FLUX modeli yüklenmez)."""
    src = db.get(Project, payload.source_project_id)
    if src is None:
        raise HTTPException(404, "Kaynak tasarım bulunamadı")
    proj = Project(
        user_id=_USER,
        name=f"tiling: {payload.motif_rel.split('/')[-1][:24]}",
        garment_type=src.garment_type,
        template_id="tiled",
        customizations={"color": "#ffffff", "decals": []},
    )
    db.add(proj); db.commit(); db.refresh(proj)
    job_id = uuid.uuid4().hex
    _job_store().create(job_id, {"kind": "tile", "project_id": proj.id})
    from common.celery_app import celery_app
    celery_app.send_task("tile.bake", kwargs={
        "job_id": job_id,
        "project_id": proj.id,
        "source_project_id": payload.source_project_id,
        "motif_rel": payload.motif_rel,
        "repeat": payload.repeat,
        "bg_color": payload.bg_color,
    }, queue=f"flux-gpu{payload.gpu}")
    return GenerateOut(job_id=job_id, project_id=proj.id)


@router.post("/batch", response_model=BatchOut, status_code=status.HTTP_201_CREATED)
def generate_batch(payload: BatchIn, db: Session = Depends(get_db)) -> BatchOut:
    """Varyasyon galerisi: aynı istekten N motif/stil işini farklı seed ile kuyruğa
    at + her iş için Variation satırı yaz. Worker'lar değişmez; sonuçlar GET /variations
    okurken job state'inden tembel uzlaştırılır."""
    proj = db.get(Project, payload.project_id)
    if proj is None:
        raise HTTPException(404, "Tasarım bulunamadı")
    queue, extra = _motif_route(payload.engine_id, payload.gpu)
    group_id = uuid.uuid4().hex
    store = _job_store()
    from common.celery_app import celery_app
    jobs: list[BatchJobOut] = []
    for i in range(payload.count):
        seed = (payload.seed_base + i) if payload.seed_base is not None else random.randint(1, 2_000_000_000)
        job_id = uuid.uuid4().hex
        var = Variation(
            group_id=group_id, project_id=proj.id, kind=payload.kind, seed=seed,
            prompt=payload.prompt or None, job_id=job_id, status="SUBMITTED",
        )
        db.add(var)
        db.flush()  # var.id
        store.create(job_id, {"kind": payload.kind, "project_id": proj.id,
                              "variation_id": var.id, "group_id": group_id})
        celery_app.send_task("motif.generate", kwargs={
            "job_id": job_id,
            "project_id": proj.id,
            "prompt": payload.prompt,
            "prompt_enhance": payload.prompt_enhance,
            "style": payload.style.model_dump() if payload.style else None,
            "seed": seed,
            **extra,
        }, queue=queue)
        jobs.append(BatchJobOut(job_id=job_id, variation_id=var.id, seed=seed))
    db.commit()
    return BatchOut(group_id=group_id, jobs=jobs)


class RefineIn(BaseModel):
    """MeshFlow ile mevcut tasarımın mesh'ini temiz topolojiyle yeniden üret.
    Non-destructive: kaynak korunur, sonuç YENİ projeye yazılır (retexture gibi)."""
    source_project_id: str
    engine_id: str = "meshflow-refine"   # veya "meshflow-guided"
    quality: str = "balanced"
    advanced: dict | None = None
    ref_image_name: str | None = None    # yalnız meshflow-guided için
    gpu: int | None = None               # None → settings.default_gpu (tek-GPU sözleşmesi)


@preprocess_router.post("/matte", status_code=status.HTTP_201_CREATED)
def preprocess_matte(
    file: UploadFile = File(...),
    gpu: int | None = Form(None),
) -> dict:
    """C1 foto ön-kırpma: yüklenen fotoğrafı UPLOADS_DIR'e yaz + flux worker'a
    `image.matte` işi kuyrukla (BiRefNet ile arka planı sil → şeffaf RGBA PNG).
    Sonuç `matte_<uuid>.png` olarak UPLOADS_DIR'e yazılır; out_url ile serve edilir.
    Job SUCCESS olunca frontend out_url'i önizler ve 'kırpılmışı kullan' seçebilir."""
    gpu = _resolve_gpu(gpu)
    settings = get_settings()
    uploads = Path(settings.uploads_dir)
    uploads.mkdir(parents=True, exist_ok=True)
    uid = uuid.uuid4().hex
    suffix = Path(file.filename or "img.png").suffix or ".png"
    src_name = f"matte_src_{uid}{suffix}"
    src_path = uploads / src_name
    src_path.write_bytes(file.file.read())
    # Opsiyonel NSFW taraması (SAFETY_FILTER=off → sıfır ek yük).
    try:
        enforce(src_path, context="upload")
    except SafetyBlocked as e:
        src_path.unlink(missing_ok=True)
        raise HTTPException(422, "İçerik güvenlik filtresine takıldı") from e
    out_name = f"matte_{uid}.png"
    out_path = uploads / out_name
    job_id = uuid.uuid4().hex
    _job_store().create(job_id, {"kind": "matte"})
    from common.celery_app import celery_app
    celery_app.send_task("image.matte", kwargs={
        "job_id": job_id,
        "image_path": str(src_path),
        "out_path": str(out_path),
    }, queue=f"flux-gpu{gpu}")
    return {"job_id": job_id, "out_url": f"/preprocess/matte/{out_name}"}


@preprocess_public_router.get("/matte/{name}")
def get_matte(name: str) -> FileResponse:
    """Ön-kırpma sonucu PNG (token'sız: <img src> Authorization gönderemez).
    Yalnız `matte_<hex>.png` kalıbı (path-traversal koruması)."""
    if not _MATTE_NAME_RE.fullmatch(name):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Geçersiz ad")
    path = Path(get_settings().uploads_dir) / name
    if not path.exists():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Sonuç henüz yok")
    return FileResponse(path, media_type="image/png")


@router.post("/refine", response_model=GenerateOut, status_code=status.HTTP_201_CREATED)
def generate_refine(payload: RefineIn, db: Session = Depends(get_db)) -> GenerateOut:
    """MeshFlow remesh: kaynak projenin mesh.glb'sini temiz topolojiyle yeniden üretir.
    meshflow ailesi -> queue meshflow-gpuN; task mesh_refine.generate."""
    gpu = _resolve_gpu(payload.gpu)
    spec = _require_available(payload.engine_id)
    if engine_family(payload.engine_id) != "meshflow":
        raise HTTPException(422, f"{spec.label} refine motoru değil")
    try:
        resolve_engine_params(payload.engine_id, payload.quality, payload.advanced)
    except ValueError as e:
        raise HTTPException(422, str(e)) from None
    src = db.get(Project, payload.source_project_id)
    if src is None:
        raise HTTPException(404, "Kaynak tasarım bulunamadı")
    proj = Project(
        user_id=_USER,
        name=f"temiz: {(src.name or 'mesh')[:40]}",
        garment_type=src.garment_type,
        template_id="meshflow-refined",
        customizations={"color": "#cccccc", "decals": []},
        engine_id=payload.engine_id,
    )
    db.add(proj)
    db.commit()
    db.refresh(proj)
    job_id = uuid.uuid4().hex
    _job_store().create(job_id, {"kind": "refine", "project_id": proj.id})
    from common.celery_app import celery_app
    celery_app.send_task("mesh_refine.generate", kwargs={
        "job_id": job_id,
        "project_id": proj.id,
        "source_project_id": payload.source_project_id,
        "engine_id": payload.engine_id,
        "quality": payload.quality,
        "advanced": payload.advanced,
        "ref_image_name": payload.ref_image_name,
    }, queue=f"meshflow-gpu{gpu}")
    return GenerateOut(job_id=job_id, project_id=proj.id)
