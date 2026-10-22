"""Instant Meshes retopoloji — Task B (2026-07-06 'hemen uygulanabilir' seti).

`POST /projects/{id}/retopo {target_faces}`: proje mesh'ini Instant Meshes CLI ile
yeniden topolojilendirir (temiz quad/tri ağı, hedef yüz sayısına yakın) ve sonucu
YENİ VARYANT olarak kaydeder (varyasyon galerisi deseni — Variation satırı).

Boru hattı: mesh çöz → geçici OBJ yaz (trimesh) → Instant Meshes başsız CLI çalıştır
(`[BIN, in.obj, -o, out.obj, -f <faces>, -d]`) → out.obj yükle → PROJECTS_DIR altına
`variations/retopo_<uuid>.glb` olarak kaydet → Variation satırı ekle. Döner:
`{variation_id, faces_before, faces_after, glb_url}`.

Eşzamanlılık: trimesh yükleme + Instant Meshes CPU-yoğun. E3 print-prep desenindeki
gibi ağır işi sınırlı bir havuza (max 2) alırız ki eşzamanlı istekler makineyi
boğmasın (Starlette senkron route'u dış havuzda koşar; `.result()` ile bu iç havuzun
bitmesini bekleriz → en fazla 2 eşzamanlı retopoloji).

Instant Meshes binary'si yoksa 422 döner ('instant-meshes kurulu değil'); kurulum
kullanıcı onayına bağlı (indirme beklemede). Binary yolu `INSTANT_MESHES_BIN` env ile,
yoksa varsayılan `<ENGINES_DIR>/bin/Instant Meshes`.
"""
from __future__ import annotations

import os
import subprocess
import tempfile
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import trimesh
from common.config import engines_dir, get_settings
from common.paths import resolve_mesh_path
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from gateway.auth import require_token
from gateway.db import get_db
from gateway.models.orm import Project, Variation

router = APIRouter(prefix="/projects", dependencies=[require_token()])

_USER = "default"

# Instant Meshes binary — env override, yoksa sözleşme konumu (dosya adında boşluk
# var; liste-arg subprocess ile güvenli, shell yok).
_DEFAULT_BIN = str(engines_dir() / "bin" / "Instant Meshes")

# Ağır trimesh/Instant Meshes işini sınırla (max 2 eşzamanlı) — print-prep deseni.
_RETOPO_POOL = ThreadPoolExecutor(max_workers=2, thread_name_prefix="retopo")

# Instant Meshes uzun sürebilir (yoğun mesh); güvenli üst sınır.
_TIMEOUT_S = 600


def _instant_meshes_bin() -> str:
    """Instant Meshes CLI yolu (env override edilebilir; testte monkeypatch)."""
    return os.getenv("INSTANT_MESHES_BIN", _DEFAULT_BIN)


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


class RetopoRequest(BaseModel):
    target_faces: int = Field(default=8000, ge=100, le=500_000)


def _run(src: Path, out: Path, target_faces: int) -> dict:
    """CPU-yoğun retopoloji boru hattı (havuzda koşar).

    Mesh'i geçici OBJ'ye yazar, Instant Meshes ile yeniden ağlar, sonucu GLB olarak
    kaydeder. Instant Meshes çıktısı üretemezse 422 fırlatır (havuzdan `.result()`
    ile route'a propagate olur).
    """
    mesh = trimesh.load(str(src), force="mesh")
    if not isinstance(mesh, trimesh.Trimesh) or len(mesh.faces) == 0:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Mesh yüklenemedi")
    faces_before = int(len(mesh.faces))

    bin_path = _instant_meshes_bin()

    with tempfile.TemporaryDirectory(prefix="retopo-") as td:
        in_obj = Path(td) / "in.obj"
        out_obj = Path(td) / "out.obj"
        mesh.export(str(in_obj))

        # Instant Meshes başsız: söz dizimi "[options] <input>". -f "istenen" yüz
        # sayısı ama üçgenlenmiş çıktı ampirik olarak ~7× geliyor (500→3606,
        # 2000→14004, 20000→153912 — 2026-07-06 canlı ölçüm). Kullanıcının hedefine
        # yaklaşmak için 7'ye bölerek geçiyoruz; gerçek sonuç faces_after'da raporlanır.
        im_target = max(100, int(target_faces) // 7)
        cmd = [bin_path, "-o", str(out_obj),
               "-f", str(im_target), "-d", str(in_obj)]
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True,
                                  timeout=_TIMEOUT_S)
        except subprocess.TimeoutExpired:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                                "Instant Meshes zaman aşımına uğradı")

        if proc.returncode != 0 or not out_obj.exists():
            tail = (proc.stderr or proc.stdout or "")[-400:]
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                                f"Instant Meshes başarısız: {tail}")

        remeshed = trimesh.load(str(out_obj), force="mesh")
        if not isinstance(remeshed, trimesh.Trimesh) or len(remeshed.faces) == 0:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                                "Retopoloji çıktısı yüklenemedi")
        faces_after = int(len(remeshed.faces))

        out.parent.mkdir(parents=True, exist_ok=True)
        remeshed.export(str(out))

    return {"faces_before": faces_before, "faces_after": faces_after}


@router.post("/{project_id}/retopo")
def retopo(project_id: str, payload: RetopoRequest | None = None,
           db: Session = Depends(get_db)) -> dict:
    proj = _require_project(db, project_id)
    src = _mesh_path(db, project_id)
    if not src.exists():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Mesh yok")

    # Binary yoksa erken 422 (indirme kullanıcı onayına bağlı).
    if not Path(_instant_meshes_bin()).exists():
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            "instant-meshes kurulu değil")

    target_faces = payload.target_faces if payload is not None else 8000
    rel = f"variations/retopo_{uuid.uuid4().hex}.glb"
    out = Path(get_settings().projects_dir) / _USER / project_id / rel

    # Ağır işi sınırlı havuza al (max 2 eşzamanlı); sonucu bekle.
    report = _RETOPO_POOL.submit(_run, src, out, target_faces).result()

    # Varyasyon galerisi deseni (drape.py) — ama retopoloji SENKRON tamamlanır,
    # bu yüzden satırı doğrudan SUCCESS + result_path ile yazarız (job/worker yok).
    # seed non-nullable → hedef yüz sayısını sakla (drape frames'i sakladığı gibi).
    var = Variation(
        group_id=uuid.uuid4().hex, project_id=proj.id, kind="retopo",
        seed=int(target_faces), prompt=None, job_id=None, status="SUCCESS",
        result_path=rel, thumbnail_path=None,
        size_bytes=out.stat().st_size if out.exists() else 0,
    )
    db.add(var)
    db.commit()

    return {
        "variation_id": var.id,
        "faces_before": report["faces_before"],
        "faces_after": report["faces_after"],
        "glb_url": f"/projects/{proj.id}/{rel}",
    }
