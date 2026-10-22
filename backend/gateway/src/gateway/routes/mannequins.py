"""Ölçüden özel manken üretme (F3).

POST   /mannequins/custom        {gender, height_cm, chest_cm, waist_cm, hip_cm, label?}
       → ev-içi CC0 taban manken (female-a / male-a) ölçülere göre morflanır
         (common.body_morph), `templates_dir/mannequins/custom-<hex>.glb` yazılır,
         `mannequins/custom_manifest.json`'a eklenir.
       Döner: {id, label, file, url, pose, base, body, measured, custom: true}
DELETE /mannequins/custom/{id}   → yalnız `custom-*` mankenler silinir (taban mankenler korunur).

Listeleme ayrı route'ta: GET /templates/mannequins (templates.py) taban manifest +
custom_manifest'i birleşik döner. Drape/sew3d worker'ları manken'i
`templates_dir/mannequins/<id>.glb` yolundan bulur → custom GLB de aynı desende.

Çıktı GLB GERÇEK ÖLÇEKTE metredir (Y-yukarı, ayak tabanı y=0, ön yüz +Z); taban
GLB'ler birim boya normalize. Frontend manken'i kıyafete boyla oturttuğu için
ikisi de doğru görünür.

Hata mesajları Türkçe ve sade (son kullanıcı teknik değil). Gövde dict olarak
alınır ki pydantic'in İngilizce tip hataları yerine kendi Türkçe mesajlarımız dönsün.
"""
from __future__ import annotations

import json
import re
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from common.body_morph import (
    BASE_BY_GENDER,
    BODY_RANGES_CM,
    TOLERANCE,
    export_glb,
    morph_to_measurements,
    within_tolerance,
)
from common.config import get_settings
from fastapi import APIRouter, Body, HTTPException, status

from gateway.auth import require_token

router = APIRouter(prefix="/mannequins", dependencies=[require_token()])

CUSTOM_MANIFEST = "custom_manifest.json"
_ID_RE = re.compile(r"^custom-[0-9a-f]{6,32}$")

# Morf + ölçüm CPU-yoğun (~0.5-3 sn) → en fazla 2 eşzamanlı üretim (sewing deseni).
_MORPH_POOL = ThreadPoolExecutor(max_workers=2, thread_name_prefix="body-morph")
# custom_manifest.json okuma-değiştirme-yazma kilidi (eşzamanlı POST/DELETE).
_MANIFEST_LOCK = threading.Lock()

_FIELD_TR = {
    "height_cm": "Boy",
    "chest_cm": "Göğüs çevresi",
    "waist_cm": "Bel çevresi",
    "hip_cm": "Kalça çevresi",
}
_GENDER_TR = {"female": "Kadın", "male": "Erkek"}


def _mannequins_dir() -> Path:
    return Path(get_settings().templates_dir) / "mannequins"


def read_custom_manifest(mdir: Path | None = None) -> list[dict]:
    """custom_manifest.json içeriği; yoksa/bozuksa boş liste (kırılmaz)."""
    path = (mdir or _mannequins_dir()) / CUSTOM_MANIFEST
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return [e for e in data if isinstance(e, dict)] if isinstance(data, list) else []


def _write_custom_manifest(mdir: Path, entries: list[dict]) -> None:
    mdir.mkdir(parents=True, exist_ok=True)
    path = mdir / CUSTOM_MANIFEST
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(entries, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def _validate(payload: Any) -> dict:
    """5 alanlı ölçü setini doğrular; hata → Türkçe 422."""
    if not isinstance(payload, dict):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            "Ölçüler okunamadı. Cinsiyet, boy, göğüs, bel ve kalça girin.")
    gender = str(payload.get("gender") or "").strip().lower()
    if gender not in BASE_BY_GENDER:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            "Cinsiyet seçin: kadın (female) ya da erkek (male).")
    body: dict[str, Any] = {"gender": gender}
    for key, (lo, hi) in BODY_RANGES_CM.items():
        name = _FIELD_TR[key]
        raw = payload.get(key)
        if raw is None or raw == "":
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"{name} girilmedi.")
        try:
            val = float(str(raw).replace(",", "."))
        except (TypeError, ValueError):
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                                f"{name} bir sayı olmalı (cm).") from None
        if not (lo <= val <= hi):
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                f"{name} {lo:g}–{hi:g} cm arasında olmalı (girilen: {val:g}).",
            )
        body[key] = round(val, 1)
    label = payload.get("label")
    if label is not None:
        label = str(label).strip()[:80]
    if not label:
        label = (f"Özel manken ({_GENDER_TR[gender]}, {body['height_cm']:g} cm, "
                 f"{body['chest_cm']:g}/{body['waist_cm']:g}/{body['hip_cm']:g})")
    body["label"] = label
    return body


def _build(base_path: Path, out_path: Path, body: dict) -> dict:
    """Havuzda koşar: morf + ölçüm + GLB yazımı. Döner: morf raporu."""
    mesh, report = morph_to_measurements(
        base_path, body["height_cm"], body["chest_cm"], body["waist_cm"], body["hip_cm"])
    ok = within_tolerance(report["measured"], body)
    report["within_tolerance"] = ok
    if all(ok.values()):
        export_glb(mesh, out_path)
    return report


@router.post("/custom")
def create_custom_mannequin(payload: Any = Body(default=None)) -> dict:
    """Ölçülerden yeni manken üretir ve kaydeder."""
    body = _validate(payload)
    mdir = _mannequins_dir()
    base_id = BASE_BY_GENDER[body["gender"]]
    base_path = mdir / f"{base_id}.glb"
    if not base_path.is_file():
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE,
                            "Taban manken dosyası bulunamadı; önce mankenleri indirin.")
    mid = f"custom-{uuid.uuid4().hex[:12]}"
    out_path = mdir / f"{mid}.glb"
    try:
        report = _MORPH_POOL.submit(_build, base_path, out_path, body).result()
    except HTTPException:
        raise
    except Exception:  # noqa: BLE001 — kullanıcıya iç hata ayrıntısı gösterme
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR,
                            "Manken üretilemedi, lütfen tekrar deneyin.") from None
    if not all(report["within_tolerance"].values()):
        bad = [_FIELD_TR[k] for k, v in report["within_tolerance"].items() if not v]
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Bu ölçü birleşimi mankene uygulanamadı (" + ", ".join(bad).lower()
            + f" hedefe %{int(TOLERANCE * 100)} yakınlıkta tutturulamadı). "
            "Ölçüleri kontrol edin; çok uç oranlar desteklenmiyor.",
        )
    rel = f"mannequins/{mid}.glb"
    entry = {
        "id": mid,
        "label": body["label"],
        "file": rel,
        "pose": "A",
        "license": "CC0",
        "source_url": "https://github.com/microsoft/TRELLIS",
        "base": base_id,
        "units": "m",
        "body": {k: body[k] for k in ("gender", "height_cm", "chest_cm", "waist_cm", "hip_cm")},
        "measured": report["measured"],
        "levels": report.get("levels", {}),
        "custom": True,
    }
    with _MANIFEST_LOCK:
        entries = [e for e in read_custom_manifest(mdir) if e.get("id") != mid]
        entries.append(entry)
        _write_custom_manifest(mdir, entries)
    return {**entry, "url": f"/template-assets/{rel}", "available": True}


@router.delete("/custom/{mannequin_id}")
def delete_custom_mannequin(mannequin_id: str) -> dict:
    """Özel manken'i (GLB + manifest girdisi) siler; taban mankenlere dokunmaz."""
    if not _ID_RE.match(mannequin_id):
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            "Yalnız ölçüden üretilmiş (özel) mankenler silinebilir.")
    mdir = _mannequins_dir()
    with _MANIFEST_LOCK:
        entries = read_custom_manifest(mdir)
        keep = [e for e in entries if e.get("id") != mannequin_id]
        glb = mdir / f"{mannequin_id}.glb"
        if len(keep) == len(entries) and not glb.exists():
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Manken bulunamadı.")
        glb.unlink(missing_ok=True)
        if len(keep) != len(entries):
            _write_custom_manifest(mdir, keep)
    return {"deleted": mannequin_id}
