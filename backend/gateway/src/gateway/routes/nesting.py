"""Kalıp parçalarını kumaşa yerleştirme (pastal planı) — F5.

`POST /patterns/{id}/nest {fabric_width_cm=150, gap_mm=5, allow_flip=true,
allow_rotate_180=true, grid_mm=5}`: `data/patterns/<id>/pieces.json`'u diskten
okur (F1 üretir), `common.nesting` ile yerleştirir, `nest.svg` + `nest.json` yazar.
Döner: `{svg_url, used_length_cm, efficiency_pct, placements, warnings, ...}`.
Parça kumaş eninden genişse 422 + Türkçe açıklama.

Eşzamanlılık: raster+FFT yerleşim CPU-yoğun (tipik kalıpta < 1 sn) → sewing.py
desenindeki gibi sınırlı havuzda (max 2) koşar.

`GET /patterns/{id}/nest.svg` public (sewing.py deseni — indirme linki
Authorization header taşıyamaz; uygulama LAN arkasındadır).
"""
from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from common.config import get_settings
from common.nesting import NestingError, nest_pattern_dir
from fastapi import APIRouter, HTTPException, status
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from gateway.auth import require_token

router = APIRouter(prefix="/patterns", dependencies=[require_token()])
public_router = APIRouter(prefix="/patterns")

# Kalıp id'si dizin adı olarak kullanılır → yol enjeksiyonuna karşı sıkı desen.
_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")

_NEST_POOL = ThreadPoolExecutor(max_workers=2, thread_name_prefix="nesting")


def _pattern_dir(pattern_id: str) -> Path:
    if not _ID_RE.match(pattern_id or ""):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Kalıp bulunamadı")
    return Path(get_settings().patterns_dir) / pattern_id


class NestRequest(BaseModel):
    fabric_width_cm: float = Field(150.0, gt=0, le=1000)
    gap_mm: float = Field(5.0, ge=0, le=100)
    allow_flip: bool = True
    allow_rotate_180: bool = True
    grid_mm: float = Field(5.0, ge=1, le=20)


@router.post("/{pattern_id}/nest")
def nest(pattern_id: str, payload: NestRequest | None = None) -> dict:
    d = _pattern_dir(pattern_id)
    if not (d / "pieces.json").exists():
        raise HTTPException(status.HTTP_404_NOT_FOUND,
                            "Kalıp bulunamadı. Önce bir kalıp oluşturun.")
    req = payload or NestRequest()
    try:
        result = _NEST_POOL.submit(
            nest_pattern_dir, d,
            fabric_width_cm=req.fabric_width_cm, gap_mm=req.gap_mm,
            allow_rotate_180=req.allow_rotate_180, allow_flip=req.allow_flip,
            grid_mm=req.grid_mm,
        ).result()
    except NestingError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    except (ValueError, KeyError, TypeError) as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            "Kalıp dosyası okunamadı ya da bozuk.") from exc
    return {
        "svg_url": f"/patterns/{pattern_id}/nest.svg",
        "json_url": f"/patterns/{pattern_id}/nest.json",
        **result,
    }


@public_router.get("/{pattern_id}/nest.svg")
def get_nest_svg(pattern_id: str) -> FileResponse:
    path = _pattern_dir(pattern_id) / "nest.svg"
    if not path.exists():
        raise HTTPException(status.HTTP_404_NOT_FOUND,
                            "Kumaş yerleşim planı henüz yok. Önce 'Kumaşa yerleştir' çalıştırın.")
    return FileResponse(path, media_type="image/svg+xml",
                        filename=f"{pattern_id}-kumas-plani.svg")


@public_router.get("/{pattern_id}/nest.json")
def get_nest_json(pattern_id: str) -> FileResponse:
    path = _pattern_dir(pattern_id) / "nest.json"
    if not path.exists():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Kumaş yerleşim planı henüz yok.")
    return FileResponse(path, media_type="application/json")
