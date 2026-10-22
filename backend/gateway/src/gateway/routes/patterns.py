"""Parametrik dikiş kalıbı (FreeSewing) — F1.

Uçlar (hepsi token'lı; dosya GET'leri `public_router` — indirme linki
Authorization header ekleyemez, sewing.py deseni):

    GET    /patterns/designs                 → küratörlü tasarım kataloğu (Türkçe ad, ölçüler, seçenekler, sew3d)
    POST   /patterns/measurements/estimate   → 5 basit ölçüden FreeSewing ölçü seti (mm)
    POST   /patterns/draft                   → kalıbı çiz, data/patterns/<id>/ altına yaz
    GET    /patterns                         → kayıtlı kalıplar (meta.json listesi, yeni→eski)
    GET    /patterns/{id}                    → tek kalıbın meta.json'u
    DELETE /patterns/{id}                    → kalıbı sil
    GET    /patterns/{id}/pattern.svg|pattern.pdf|pieces.json|freesewing.svg  (public)

Ağır iş (Node alt süreci + PDF karolama) sınırlı havuzda koşar (max 2 eşzamanlı) —
print-prep/sewing deseni; eşzamanlı istekler makineyi boğmaz.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from typing import Any

from common.body_measurements import MeasurementError, estimate_measurements
from common.patterns import (
    PatternError,
    delete_pattern,
    draft_pattern,
    list_patterns,
    pattern_path,
    public_catalog,
    read_meta,
)
from fastapi import APIRouter, HTTPException, status
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from gateway.auth import require_token

router = APIRouter(prefix="/patterns", dependencies=[require_token()])
public_router = APIRouter(prefix="/patterns")

_DRAFT_POOL = ThreadPoolExecutor(max_workers=2, thread_name_prefix="patterns")

_FILES = {
    "pattern.svg": "image/svg+xml",
    "pattern.pdf": "application/pdf",
    "pieces.json": "application/json",
    "freesewing.svg": "image/svg+xml",
}


class SimpleBody(BaseModel):
    """Arayüzün istediği 5 alan (cm)."""

    gender: str = Field(..., description="female | male")
    height_cm: float
    chest_cm: float
    waist_cm: float
    hip_cm: float


class DraftRequest(BaseModel):
    design: str
    body: SimpleBody | None = None
    measurements: dict[str, float] | None = None
    options: dict[str, str] | None = None
    fs_options: dict[str, Any] | None = None
    sa_mm: float = 10.0


def _http(exc: PatternError) -> HTTPException:
    return HTTPException(exc.status, str(exc))


def _urls(pid: str) -> dict:
    return {
        "svg_url": f"/patterns/{pid}/pattern.svg",
        "pdf_url": f"/patterns/{pid}/pattern.pdf",
        "pieces_url": f"/patterns/{pid}/pieces.json",
    }


def _summary(meta: dict) -> dict:
    pid = meta["pattern_id"]
    return {
        "pattern_id": pid,
        "design": meta.get("design"),
        "label_tr": meta.get("label_tr"),
        "sew3d": meta.get("sew3d", False),
        "created_at": meta.get("created_at"),
        **_urls(pid),
        "pieces": [{"name": p["name"], "label_tr": p["label_tr"], "quantity": p["quantity"]}
                   for p in meta.get("pieces", [])],
        "warnings": meta.get("warnings", []),
    }


@router.get("/designs")
def designs() -> list[dict]:
    return public_catalog()


@router.post("/measurements/estimate")
def estimate(payload: SimpleBody) -> dict:
    try:
        return {"measurements": estimate_measurements(payload.model_dump()), "units": "mm",
                "note": "Tahmini ölçüler — en doğru sonuç için kendi ölçülerinizi girebilirsiniz."}
    except MeasurementError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from None


@router.post("/draft")
def draft(payload: DraftRequest) -> dict:
    if payload.body is None and not payload.measurements:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Ölçü gerekli: cinsiyet, boy, göğüs, bel ve basen (body) girin.",
        )
    body = payload.body.model_dump() if payload.body is not None else None
    try:
        meta = _DRAFT_POOL.submit(
            draft_pattern, payload.design, payload.measurements, body, payload.options,
            payload.fs_options, payload.sa_mm,
        ).result()
    except PatternError as exc:
        raise _http(exc) from None
    return {**_summary(meta), "design": meta["design"]}


@router.get("")
def list_all() -> list[dict]:
    return [_summary(m) for m in list_patterns()]


@router.get("/{pattern_id}")
def get_one(pattern_id: str) -> dict:
    try:
        meta = read_meta(pattern_id)
    except PatternError as exc:
        raise _http(exc) from None
    return {**meta, **_urls(pattern_id)}


@router.delete("/{pattern_id}")
def delete_one(pattern_id: str) -> dict:
    try:
        delete_pattern(pattern_id)
    except PatternError as exc:
        raise _http(exc) from None
    return {"deleted": pattern_id}


def _file(pattern_id: str, name: str) -> FileResponse:
    try:
        path = pattern_path(pattern_id) / name
    except PatternError as exc:
        raise _http(exc) from None
    if not path.is_file():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Kalıp dosyası bulunamadı")
    return FileResponse(path, media_type=_FILES[name], filename=f"kalip-{pattern_id[:8]}-{name}")


@public_router.get("/{pattern_id}/pattern.svg")
def get_svg(pattern_id: str) -> FileResponse:
    return _file(pattern_id, "pattern.svg")


@public_router.get("/{pattern_id}/pattern.pdf")
def get_pdf(pattern_id: str) -> FileResponse:
    return _file(pattern_id, "pattern.pdf")


@public_router.get("/{pattern_id}/pieces.json")
def get_pieces(pattern_id: str) -> FileResponse:
    return _file(pattern_id, "pieces.json")


@public_router.get("/{pattern_id}/freesewing.svg")
def get_fs_svg(pattern_id: str) -> FileResponse:
    return _file(pattern_id, "freesewing.svg")
