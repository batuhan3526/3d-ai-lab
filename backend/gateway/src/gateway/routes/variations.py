"""Varyasyon galerisi kalıcılığı: listele / depolama özeti / favori / sil.

Worker'lar Variation tablosuna dokunmaz; bu route okurken job state'inden
SUCCESS/FAILURE + result_path + size_bytes'ı tembel uzlaştırır (lazy reconcile).
"""
from __future__ import annotations

import json

import shutil
import time
from pathlib import Path

from common.config import get_settings
from common.jobs import JobStore
from common.paths import to_stored_mesh_path
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from gateway.auth import require_token
from gateway.db import get_db
from gateway.models.orm import Favorite, Project, Variation
from gateway.models.schemas import StorageGroupOut, StorageOut, VariationOut

router = APIRouter(prefix="/variations", dependencies=[require_token()])


def _job_store() -> JobStore:
    return JobStore()


def _abs_path(project_id: str, rel: str) -> Path:
    return Path(get_settings().projects_dir) / "default" / project_id / rel


def _reconcile(db: Session, v: Variation, store: JobStore) -> None:
    """SUBMITTED varyasyonun job'ı bittiyse DB'ye sonucu yaz."""
    if v.status in ("SUCCESS", "FAILURE") or not v.job_id:
        return
    job = store.get(v.job_id)
    if not job:
        return
    st = job.get("state")
    if st == "SUCCESS":
        rel = job.get("decal_path")
        v.status = "SUCCESS"
        if rel:
            v.result_path = rel
            v.thumbnail_path = rel
            fp = _abs_path(v.project_id, rel)
            v.size_bytes = fp.stat().st_size if fp.exists() else 0
        db.add(v)
    elif st == "FAILURE":
        v.status = "FAILURE"
        db.add(v)


def _fav_ids(db: Session) -> set[str]:
    return set(db.scalars(select(Favorite.variation_id)).all())


def _to_out(v: Variation, fav: set[str]) -> VariationOut:
    out = VariationOut.model_validate(v)
    out.favorite = v.id in fav
    return out


@router.get("", response_model=list[VariationOut])
def list_variations(group_id: str | None = None, favorite: bool = False,
                    db: Session = Depends(get_db)) -> list[VariationOut]:
    store = _job_store()
    q = select(Variation)
    if group_id:
        q = q.where(Variation.group_id == group_id)
    rows = list(db.scalars(q.order_by(Variation.created_at)))
    for v in rows:
        _reconcile(db, v, store)
    db.commit()
    fav = _fav_ids(db)
    if favorite:
        rows = [v for v in rows if v.id in fav]
    return [_to_out(v, fav) for v in rows]


@router.get("/storage", response_model=StorageOut)
def storage(db: Session = Depends(get_db)) -> StorageOut:
    store = _job_store()
    rows = list(db.scalars(select(Variation).order_by(Variation.created_at)))
    for v in rows:
        _reconcile(db, v, store)
    db.commit()
    fav = _fav_ids(db)
    groups: dict[str, list[Variation]] = {}
    for v in rows:
        groups.setdefault(v.group_id, []).append(v)
    out_groups: list[StorageGroupOut] = []
    total = 0
    for gid, vs in groups.items():
        gbytes = sum(v.size_bytes or 0 for v in vs)
        total += gbytes
        out_groups.append(StorageGroupOut(
            group_id=gid, kind=vs[0].kind, prompt=vs[0].prompt, count=len(vs),
            bytes=gbytes, created_at=vs[0].created_at,
            variations=[_to_out(v, fav) for v in vs],
        ))
    out_groups.sort(key=lambda g: g.created_at, reverse=True)
    return StorageOut(total_bytes=total, count=len(rows), groups=out_groups)


@router.post("/{variation_id}/apply")
def apply_variant(variation_id: str, db: Session = Depends(get_db)) -> dict:
    """3D varyantı (drape/upscale sonucu, .glb) projenin mesh.glb'sinin üzerine yaz.

    ÖNCE mevcut mesh.glb → mesh.glb.bak-<ts> yedeklenir (versiyon mekanizması
    yalnız customizations JSON'ı tutar, mesh binary'sini korumaz → dosya yedeği).
    Sonra viewer kopyaları (mesh_view*.glb) silinir ki görüntüleyici yeniden üretsin.
    """
    v = db.get(Variation, variation_id)
    if v is None:
        raise HTTPException(404, "Varyasyon bulunamadı")
    # SUBMITTED kaldıysa sonucu uzlaştır (galeri henüz okumadıysa).
    if v.status not in ("SUCCESS", "FAILURE") and v.job_id:
        _reconcile(db, v, _job_store())
        db.commit()
    if not v.result_path:
        raise HTTPException(409, "Varyant sonucu henüz hazır değil")
    src = _abs_path(v.project_id, v.result_path)
    if src.suffix.lower() != ".glb" or not src.exists():
        raise HTTPException(409, "Uygulanabilir GLB varyantı yok")

    proj_dir = Path(get_settings().projects_dir) / "default" / v.project_id
    proj_dir.mkdir(parents=True, exist_ok=True)
    mesh = proj_dir / "mesh.glb"
    if mesh.exists():
        shutil.copy2(mesh, proj_dir / f"mesh.glb.bak-{int(time.time())}")
    # GÜVENLİK SÜZGECİ: eski clothsim çıktılarında sahneye Blender zemin düzlemleri
    # sızmış olabilir (canlı vaka 2026-07-06: 4×20m dokusuz Plane beyaz düzlem olarak
    # göründü). Dokusuz + neredeyse-düz (min kenar < %1 maks kenar) geometrileri
    # uygularken ayıkla; süzgeç bir şey ayıklarsa temizlenmiş sahneyi yaz.
    stripped = 0
    try:
        import trimesh  # noqa: PLC0415

        scene = trimesh.load(str(src), force="scene")
        keep = {}
        for name, geom in scene.geometry.items():
            ext = sorted(geom.bounding_box.extents)
            flat = ext[0] < 0.01 * max(ext[-1], 1e-9)
            mat = getattr(geom.visual, "material", None)
            has_tex = getattr(mat, "baseColorTexture", None) is not None
            if flat and not has_tex:
                stripped += 1
                continue
            keep[name] = geom
        if stripped and keep:
            clean = trimesh.Scene(keep)
            clean.export(str(mesh))
        else:
            shutil.copy2(src, mesh)
    except Exception:  # noqa: BLE001 — süzgeç asla uygulamayı engellemesin
        shutil.copy2(src, mesh)
    # Viewer kopyalarını geçersiz kıl (mesh_view.glb / mesh_view_<faces>.glb) →
    # bir sonraki GET /mesh yeniden üretir.
    for view in proj_dir.glob("mesh_view*.glb"):
        try:
            view.unlink()
        except OSError:
            pass

    proj = db.get(Project, v.project_id)
    mannequin = None
    if proj is not None:
        proj.mesh_path = to_stored_mesh_path(mesh)
        # Giydirme (fit) varyantı: yan bilgi JSON'u varsa projenin manken ayarını da
        # güncelle (pozlu manken + otomatik hiza) → kıyafet ve manken birlikte değişir.
        side = src.with_suffix(".json")
        if side.exists():
            try:
                info = json.loads(side.read_text(encoding="utf-8"))
                cust = dict(proj.customizations or {})
                prev = dict(cust.get("mannequin") or {})
                mannequin = {"id": info["mannequin_id"], "visible": True,
                             "opacity": prev.get("opacity", 0.7), "transform": info["transform"],
                             "fitted": True, "posed": info.get("posed")}
                cust["mannequin"] = mannequin
                if info.get("measurements"):
                    cust["measurements"] = info["measurements"]
                proj.customizations = cust
            except (OSError, ValueError, KeyError):
                mannequin = None
        db.add(proj)
        db.commit()
    out = {"ok": True, "project_id": v.project_id}
    if mannequin is not None:
        out["mannequin"] = mannequin
    return out


@router.post("/{variation_id}/favorite")
def add_favorite(variation_id: str, db: Session = Depends(get_db)) -> dict:
    v = db.get(Variation, variation_id)
    if v is None:
        raise HTTPException(404, "Varyasyon bulunamadı")
    if not db.scalar(select(Favorite).where(Favorite.variation_id == variation_id)):
        db.add(Favorite(variation_id=variation_id))
        db.commit()
    return {"ok": True}


@router.delete("/{variation_id}/favorite")
def remove_favorite(variation_id: str, db: Session = Depends(get_db)) -> dict:
    fav = db.scalar(select(Favorite).where(Favorite.variation_id == variation_id))
    if fav:
        db.delete(fav)
        db.commit()
    return {"ok": True}


@router.delete("/group/{group_id}")
def delete_group(group_id: str, db: Session = Depends(get_db)) -> dict:
    rows = list(db.scalars(select(Variation).where(Variation.group_id == group_id)))
    for v in rows:
        _delete_one(db, v)
    db.commit()
    return {"deleted": len(rows)}


@router.delete("/{variation_id}")
def delete_variation(variation_id: str, db: Session = Depends(get_db)) -> dict:
    v = db.get(Variation, variation_id)
    if v is None:
        raise HTTPException(404, "Varyasyon bulunamadı")
    _delete_one(db, v)
    db.commit()
    return {"ok": True}


def _delete_one(db: Session, v: Variation) -> None:
    if v.result_path:
        fp = _abs_path(v.project_id, v.result_path)
        # Giydirme (fit) varyantının yan dosyaları: bilgi JSON'u + pozlu manken GLB'si.
        # Pozlu manken projenin ŞU AN kullandığı dosyaysa korunur (uygulanmış giydirme).
        side = fp.with_suffix(".json")
        extra = [side]
        if side.exists():
            try:
                posed = json.loads(side.read_text(encoding="utf-8")).get("posed")
            except (OSError, ValueError):
                posed = None
            proj = db.get(Project, v.project_id)
            in_use = ((proj.customizations or {}).get("mannequin") or {}).get("posed") if proj else None
            if posed and posed != in_use:
                extra.append(fp.parent / posed)
        for f in [fp, *extra]:
            if f.exists():
                try:
                    f.unlink()
                except OSError:
                    pass
    fav = db.scalar(select(Favorite).where(Favorite.variation_id == v.id))
    if fav:
        db.delete(fav)
    db.delete(v)
