"""Dikiş kalıbı (sewing pattern) — Task BATCH-G.

`POST /projects/{id}/sewing-pattern {height_cm}`: proje mesh'ini xatlas ile açar,
gerçek ölçekli chart poligonları + dikiş payı üretir, SVG (1:1) ve A4-karo PDF yazar.
Döner: `{svg_url, pdf_url, charts, note:"deneysel"}`.

Eşzamanlılık: xatlas parametrize + trimesh yükleme CPU-yoğun. E3 print-prep
desenindeki gibi ağır işi sınırlı bir havuza (max 2) alırız ki eşzamanlı istekler
makineyi boğmasın (Starlette senkron route'u dış havuzda koşar; `.result()` ile
bu iç havuzun bitmesini bekleriz → en fazla 2 eşzamanlı açım).

SVG/PDF servis: GET public (mesh/thumbnail/print.stl deseni) — indirme linki
Authorization header ekleyemez; dosya UUID proje id ile adreslenir, uygulama LAN
arkasındadır.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import trimesh
from common.config import get_settings
from common.paths import resolve_mesh_path
from common.sewing import charts_to_svg, svg_to_pdf_tiles, unfold_to_charts
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from gateway.auth import require_token
from gateway.db import get_db
from gateway.models.orm import Project

router = APIRouter(prefix="/projects", dependencies=[require_token()])
public_router = APIRouter(prefix="/projects")

_USER = "default"

# Ağır xatlas/trimesh işini sınırla (max 2 eşzamanlı açım) — print-prep deseni.
_UNFOLD_POOL = ThreadPoolExecutor(max_workers=2, thread_name_prefix="sewing")


def _require_project(db: Session, project_id: str) -> Project:
    proj = db.get(Project, project_id)
    if proj is None or proj.user_id != _USER:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Proje bulunamadı")
    return proj


def _mesh_path(db: Session, project_id: str) -> Path:
    proj = db.get(Project, project_id)
    if proj is not None and proj.mesh_path:
        return resolve_mesh_path(proj.mesh_path)
    return Path(get_settings().projects_dir) / _USER / project_id / "mesh.glb"


def _svg_path(project_id: str) -> Path:
    return Path(get_settings().projects_dir) / _USER / project_id / "sewing-pattern.svg"


def _pdf_path(project_id: str) -> Path:
    return Path(get_settings().projects_dir) / _USER / project_id / "sewing-pattern.pdf"


class SewingRequest(BaseModel):
    height_cm: float = 100.0


def _build(src: Path, out_svg: Path, out_pdf: Path,
           height_cm: float) -> tuple[list[dict], dict]:
    """CPU-yoğun açım boru hattı (havuzda koşar).

    Ölçek: mesh Y (yükseklik) ekseni kullanıcının verdiği `height_cm` değerine
    karşılık gelecek şekilde birim→mm çarpanı türetilir. Y boyu 0 ise (dejenere)
    1 birim = 1 mm varsayılır. Döner: (charts, stats) — stats yüz sayılarını taşır.
    """
    mesh = trimesh.load(str(src), force="mesh")
    if not isinstance(mesh, trimesh.Trimesh) or len(mesh.faces) == 0:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Mesh yüklenemedi")
    y_extent = float(mesh.extents[1])
    target_mm = float(height_cm) * 10.0
    scale_mm_per_unit = (target_mm / y_extent) if y_extent > 1e-9 else 1.0

    stats: dict = {}
    charts = unfold_to_charts(str(src), scale_mm_per_unit, stats)
    charts_to_svg(charts, str(out_svg))
    svg_to_pdf_tiles(str(out_svg), str(out_pdf))
    return charts, stats


@router.post("/{project_id}/sewing-pattern")
def sewing_pattern(project_id: str, payload: SewingRequest | None = None,
                   db: Session = Depends(get_db)) -> dict:
    _require_project(db, project_id)
    src = _mesh_path(db, project_id)
    if not src.exists():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Mesh yok")
    height_cm = payload.height_cm if payload is not None else 100.0
    out_svg = _svg_path(project_id)
    out_pdf = _pdf_path(project_id)
    charts, stats = _UNFOLD_POOL.submit(_build, src, out_svg, out_pdf, height_cm).result()
    return {
        "svg_url": f"/projects/{project_id}/sewing-pattern.svg",
        "pdf_url": f"/projects/{project_id}/sewing-pattern.pdf",
        "charts": charts,
        "faces_in": stats.get("faces_in"),
        "faces_used": stats.get("faces_used"),
        "components_total": stats.get("components_total"),
        "components_dropped": stats.get("components_dropped"),
        "charts_total": stats.get("charts_total"),
        "charts_drawn": stats.get("charts_drawn"),
        "charts_dropped": stats.get("charts_dropped"),
        "note": "deneysel",
    }


@public_router.get("/{project_id}/sewing-pattern.svg")
def get_sewing_svg(project_id: str, db: Session = Depends(get_db)) -> FileResponse:
    _require_project(db, project_id)
    path = _svg_path(project_id)
    if not path.exists():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Dikiş kalıbı SVG'i yok")
    return FileResponse(path, media_type="image/svg+xml",
                        filename=f"{project_id}-sewing.svg")


@public_router.get("/{project_id}/sewing-pattern.pdf")
def get_sewing_pdf(project_id: str, db: Session = Depends(get_db)) -> FileResponse:
    _require_project(db, project_id)
    path = _pdf_path(project_id)
    if not path.exists():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Dikiş kalıbı PDF'i yok")
    return FileResponse(path, media_type="application/pdf",
                        filename=f"{project_id}-sewing.pdf")
