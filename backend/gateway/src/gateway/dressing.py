"""Mankene giydirme hattı — giydir ucu ve üretim uçlarının ortak kodu.

Akış: (ölçü verildiyse) ölçülerden manken bul/üret → `clothsim.fit` işi (otomatik hiza
+ kol pozu + oturtma + terzi ölçü tablosu). Üretimle birlikte istenirse iş, üretim görevi
BAŞARIYLA bitince Celery `link` ile kendiliğinden başlar (ayrı iş kimliğiyle izlenir) ve
sonucu projeye otomatik uygular.
"""
from __future__ import annotations

import json
import uuid
from typing import Any

from common.jobs import JobStore
from fastapi import HTTPException

DRESSABLE = {"tshirt", "shirt", "pants", "skirt"}
DEFAULT_MANNEQUIN = {"female": "female-a", "male": "male-a"}
_BODY_KEYS = ("gender", "height_cm", "chest_cm", "waist_cm", "hip_cm")


def parse_dress(raw: Any) -> dict | None:
    """İstekteki `dress` seçeneği: {"mannequin_id"?, "body"?: {gender, height_cm, chest_cm,
    waist_cm, hip_cm}} ya da JSON metni (multipart formlar). Boş → None."""
    if raw in (None, "", {}):
        return None
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except ValueError:
            raise HTTPException(422, "dress geçerli JSON değil") from None
    if not isinstance(raw, dict):
        raise HTTPException(422, "dress bir nesne olmalı")
    return raw


def _same_body(a: dict, b: dict) -> bool:
    try:
        return a.get("gender") == b.get("gender") and all(
            abs(float(a[k]) - float(b[k])) < 0.05 for k in _BODY_KEYS[1:])
    except (KeyError, TypeError, ValueError):
        return False


def resolve_mannequin(opt: dict | None) -> str:
    """Seçeneğe göre manken kimliği: ölçü verildiyse aynı ölçüdeki özel mankeni kullan,
    yoksa ölçülerden üret; manken kimliği verildiyse o; hiçbiri yoksa kadın taban manken."""
    from gateway.routes.mannequins import (_mannequins_dir, create_custom_mannequin,
                                           read_custom_manifest)
    opt = opt or {}
    body = opt.get("body")
    if body:
        for e in read_custom_manifest():
            if _same_body(e.get("body") or {}, body):
                return e["id"]
        entry = create_custom_mannequin(dict(body))   # doğrular, morflar, manifeste yazar
        return entry["id"]
    mid = opt.get("mannequin_id")
    if mid:
        if not (_mannequins_dir() / f"{mid}.glb").is_file():
            raise HTTPException(422, f"Manken bulunamadı: {mid}")
        return str(mid)
    return DEFAULT_MANNEQUIN["female"]


def require_dressable(garment_type: str) -> None:
    if garment_type not in DRESSABLE:
        raise HTTPException(422, "Mankene giydirme yalnız üst/alt giyimde (tişört, gömlek/üst, "
                                 "pantolon, etek) destekleniyor.")


def fit_kwargs(job_id: str, project_id: str, mannequin_id: str, garment_type: str, *,
               transform: dict | None = None, margin: float = 0.012, auto_apply: bool = False) -> dict:
    return {"job_id": job_id, "project_id": project_id, "mannequin_id": mannequin_id,
            "transform": transform, "margin": margin, "garment_type": garment_type,
            "auto_apply": auto_apply}


def prepare(garment_type: str, raw: Any) -> str | None:
    """Üretim isteğindeki giydirme seçeneğini PROJE OLUŞTURULMADAN doğrula + mankeni çöz
    (hatalı seçenek boş proje bırakmasın). Döner: manken kimliği ya da None (giydirme yok)."""
    opt = parse_dress(raw)
    if opt is None:
        return None
    require_dressable(garment_type)
    return resolve_mannequin(opt)


def dress_after(store: JobStore, project_id: str, garment_type: str, mid: str):
    """Üretimden SONRA giydirme: (iş kimliği, Celery link imzası). Üretim görevi başarıyla
    dönerse worker bu imzayı clothsim-cpu kuyruğuna yollar; sonuç projeye uygulanır."""
    from common.celery_app import celery_app
    job_id = uuid.uuid4().hex
    store.create(job_id, {"kind": "dress", "project_id": project_id, "mannequin_id": mid})
    sig = celery_app.signature("clothsim.fit", kwargs=fit_kwargs(
        job_id, project_id, mid, garment_type, auto_apply=True), queue="clothsim-cpu", immutable=True)
    return job_id, sig
