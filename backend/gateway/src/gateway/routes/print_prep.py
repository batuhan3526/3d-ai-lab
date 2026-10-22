"""3D baskı hazırlama (print-prep) — Task E3.

`POST /projects/{id}/print-prep`: proje mesh'ini trimesh ile baskıya hazırlar —
delikleri doldurur (`fill_holes`), watertight (su-geçirmez) durumunu ölçer,
istenirse hedef yüksekliğe ölçekler ve bir STL yazar. Rapor döner:
`{watertight_before, watertight_after, holes_filled, dims_mm, volume_cm3, stl_url}`.

Eşzamanlılık: trimesh yükleme + onarım CPU-yoğun ve bellek-yoğun. `/mesh`
viewer-kopya üretiminin arka-plan iş parçacığı deseninde olduğu gibi, ağır işi
sınırlı bir havuza (max 2) alırız ki çok sayıda eşzamanlı istek makineyi
boğmasın. Route senkron `def` olduğu için Starlette onu zaten dış iş-parçacığı
havuzunda çalıştırır; burada `.result()` ile havuzun bitmesini bekleriz, böylece
aynı anda en fazla 2 mesh onarımı koşar.

STL servis: GET public (mesh/thumbnail deseni) — indirme linki Authorization
header ekleyemez; dosya UUID proje id ile adreslenir, uygulama LAN arkasındadır.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import trimesh
from common.config import get_settings
from common.paths import resolve_mesh_path
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

# Ağır trimesh işini sınırla (max 2 eşzamanlı onarım). Modül-ömürlü havuz;
# /mesh viewer-kopya iş-parçacığı sınırlama deseniyle aynı amaç.
_PREP_POOL = ThreadPoolExecutor(max_workers=2, thread_name_prefix="print-prep")


def _require_project(db: Session, project_id: str) -> Project:
    proj = db.get(Project, project_id)
    if proj is None or proj.user_id != _USER:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Proje bulunamadı")
    return proj


def _mesh_path(db: Session, project_id: str) -> Path:
    """DB'de kayıtlı mesh yolunu çöz; yoksa sözleşme konumuna düş."""
    proj = db.get(Project, project_id)
    if proj is not None and proj.mesh_path:
        return resolve_mesh_path(proj.mesh_path)
    return Path(get_settings().projects_dir) / _USER / project_id / "mesh.glb"


def _stl_path(project_id: str) -> Path:
    return Path(get_settings().projects_dir) / _USER / project_id / "print.stl"


def _count_boundary_loops(mesh: trimesh.Trimesh) -> int:
    """Açık kenar (yalnız bir yüze ait) döngülerinin sayısı = delik sayısı.

    Sınır kenarlarının uç noktalarını union-find ile birleştirir; bağlı bileşen
    sayısı delik sayısına eşittir (bir dörtgen/üçgen delik = tek döngü).
    """
    edges = mesh.edges_sorted
    if len(edges) == 0:
        return 0
    # Aynı kenarı sıralı olarak grupla; yalnız BİR kez görünen kenar = sınır.
    order = np.lexsort(edges.T[::-1])
    ordered = edges[order]
    # Ardışık eşitlik maskesi ile grup uzunluklarını bul.
    same = np.all(ordered[1:] == ordered[:-1], axis=1)
    # Grup sınırları: same False olan yerler yeni grup başlatır.
    group_ids = np.concatenate([[0], np.cumsum(~same)])
    counts = np.bincount(group_ids)
    boundary_mask = counts[group_ids] == 1
    boundary = ordered[boundary_mask]
    if len(boundary) == 0:
        return 0

    parent: dict[int, int] = {}

    def find(x: int) -> int:
        parent.setdefault(x, x)
        root = x
        while parent[root] != root:
            root = parent[root]
        while parent[x] != root:
            parent[x], x = root, parent[x]
        return root

    for a, b in boundary:
        ra, rb = find(int(a)), find(int(b))
        if ra != rb:
            parent[ra] = rb
    return len({find(int(a)) for a, _ in boundary})


class PrintPrepRequest(BaseModel):
    target_height_mm: float | None = None


def _prepare(src: Path, out: Path, target_height_mm: float | None) -> dict:
    """CPU-yoğun trimesh boru hattı (havuzda koşar).

    Ölçek: `target_height_mm` verilirse mesh, en uzun ekseni değil Y (yükseklik)
    ekseni o değere gelecek şekilde ÜNİFORM ölçeklenir. Verilmezse ham birimler
    milimetre kabul edilir (STL birimsizdir; dilimleyiciler mm varsayar).
    """
    mesh = trimesh.load(str(src), force="mesh")
    if not isinstance(mesh, trimesh.Trimesh):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Mesh yüklenemedi")

    watertight_before = bool(mesh.is_watertight)
    loops_before = _count_boundary_loops(mesh)

    # Delikleri doldur (mutasyon); trimesh üçgen/dörtgen delikleri kapatır.
    mesh.fill_holes()
    mesh.remove_unreferenced_vertices()

    watertight_after = bool(mesh.is_watertight)
    loops_after = _count_boundary_loops(mesh)
    holes_filled = max(0, loops_before - loops_after)

    # Ölçekleme (üniform), Y ekseni = yükseklik.
    extents = mesh.extents  # [x, y, z] mesh birimi
    if target_height_mm is not None and target_height_mm > 0 and extents[1] > 0:
        factor = float(target_height_mm) / float(extents[1])
        mesh.apply_scale(factor)

    dims = mesh.extents  # ölçek sonrası, mm kabul edilir
    dims_mm = [round(float(dims[0]), 4), round(float(dims[1]), 4), round(float(dims[2]), 4)]
    # Hacim mm^3 → cm^3 (/1000). Watertight değilse trimesh yaklaşık/negatif
    # verebilir; mutlak değer alıp cm^3'e çeviririz.
    volume_cm3 = round(abs(float(mesh.volume)) / 1000.0, 4)

    out.parent.mkdir(parents=True, exist_ok=True)
    mesh.export(str(out))

    return {
        "watertight_before": watertight_before,
        "watertight_after": watertight_after,
        "holes_filled": int(holes_filled),
        "dims_mm": dims_mm,
        "volume_cm3": volume_cm3,
    }


@router.post("/{project_id}/print-prep")
def print_prep(project_id: str, payload: PrintPrepRequest | None = None,
               db: Session = Depends(get_db)) -> dict:
    _require_project(db, project_id)
    src = _mesh_path(db, project_id)
    if not src.exists():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Mesh yok")
    out = _stl_path(project_id)
    target = payload.target_height_mm if payload is not None else None
    # Ağır işi sınırlı havuza al (max 2 eşzamanlı); sonucu bekle.
    report = _PREP_POOL.submit(_prepare, src, out, target).result()
    report["stl_url"] = f"/projects/{project_id}/print.stl"
    return report


@public_router.get("/{project_id}/print.stl")
def get_print_stl(project_id: str, db: Session = Depends(get_db)) -> FileResponse:
    _require_project(db, project_id)
    path = _stl_path(project_id)
    if not path.exists():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Baskı STL'i yok")
    return FileResponse(path, media_type="model/stl", filename=f"{project_id}.stl")
