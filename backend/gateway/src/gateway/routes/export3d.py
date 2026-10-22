"""FBX/OBJ dışa-aktarma (Blender köprüsü) — Task E (2026-07-06 seti).

`POST /projects/{id}/export3d {format:'fbx'|'obj'}`: proje mesh'ini (kanonik
`mesh.glb`) DCC dostu bir formata çevirir ve `{url, size_bytes}` döner.

- `obj`: trimesh doğrudan dışa aktarır; sonuç bir ZIP olur (`.obj` + varsa `.mtl`
  ve doku PNG'leri birlikte paketlenir — OBJ dokusu ayrı dosyalar olduğundan tek
  indirmede eksiksiz gelsin diye). Bağımlılık yok (trimesh gateway venv'inde var).
- `fbx`: Blender başsız (`-b -P blender_export.py -- in.glb out.fbx`) alt-süreç
  ile GLB içe → FBX dışa. Blender binary yoksa 422 ('blender kurulu değil').

Binary yolu: `BLENDER_BIN` env, yoksa PATH, yoksa `<ENGINES_DIR>/blender/blender` (engine.sh install clothsim).

Çıktı `PROJECTS_DIR/default/<id>/export.fbx` (fbx) veya `export.obj.zip` (obj)
olarak saklanır; indirme için aynı authed router üzerinde
`GET /projects/{id}/export3d.{fmt}` servis eder (FileResponse — print.stl deseni).
İndirme linki Authorization header ekleyemediğinden frontend dosyayı authed
`fetch` ile blob olarak çeker (bu router `require_token` ile korunur; main.py
yalnız authed router'ı kaydeder).

Eşzamanlılık: trimesh/Blender işi CPU-yoğun. print-prep/retopo desenindeki gibi
ağır işi sınırlı bir havuza (max 2) alırız (Starlette senkron route'u dış havuzda
koşar; `.result()` ile iç havuzun bitmesini bekleriz → en fazla 2 eşzamanlı).
"""
from __future__ import annotations

import os
import subprocess
import tempfile
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Literal

import trimesh
from common.config import engines_dir, get_settings
from common.paths import resolve_mesh_path
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from gateway.auth import require_token
from gateway.db import get_db
from gateway.models.orm import Project

router = APIRouter(prefix="/projects", dependencies=[require_token()])

_USER = "default"

# Blender taşınabilir binary — env override edilebilir; testte monkeypatch.
_DEFAULT_BLENDER = str(engines_dir() / "blender" / "blender")

# Blender-tarafı FBX betiği (bu modülün bir üst dizininde: gateway/blender_export.py).
_BLENDER_SCRIPT = Path(__file__).resolve().parent.parent / "blender_export.py"

# Ağır trimesh/Blender işini sınırla (max 2 eşzamanlı) — print-prep deseni.
_EXPORT_POOL = ThreadPoolExecutor(max_workers=2, thread_name_prefix="export3d")

# Blender uzun sürebilir (yoğun mesh + doku gömme); güvenli üst sınır.
_TIMEOUT_S = 600

_FORMATS = ("fbx", "obj")


def _blender_bin() -> str:
    """Blender CLI yolu (env override edilebilir; testte monkeypatch)."""
    return os.getenv("BLENDER_BIN", _DEFAULT_BLENDER)


def _require_project(db: Session, project_id: str) -> Project:
    proj = db.get(Project, project_id)
    if proj is None or proj.user_id != _USER:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Proje bulunamadı")
    return proj


def _mesh_path(db: Session, project_id: str) -> Path:
    """DB'de kayıtlı mesh yolunu çöz; yoksa sözleşme konumuna düş (print-prep deseni)."""
    proj = db.get(Project, project_id)
    if proj is not None and proj.mesh_path:
        return resolve_mesh_path(proj.mesh_path)
    return Path(get_settings().projects_dir) / _USER / project_id / "mesh.glb"


def _out_path(project_id: str, fmt: str) -> Path:
    """Çıktı dosyası: obj → ZIP paketi, fbx → tek FBX."""
    name = "export.obj.zip" if fmt == "obj" else f"export.{fmt}"
    return Path(get_settings().projects_dir) / _USER / project_id / name


class Export3dRequest(BaseModel):
    format: Literal["fbx", "obj"]


def _export_obj(src: Path, out_zip: Path) -> None:
    """GLB'yi OBJ'ye çevir ve .obj + .mtl + doku(lar)ı tek ZIP'e paketle.

    trimesh OBJ dışa-aktarımı dokusuz mesh için yalnız `.obj`, dokuluda ek olarak
    `.mtl` ve PNG(ler) yazar; geçici dizindeki TÜM dosyaları zip'leriz ki OBJ
    dokusu (ayrı dosyalar) tek indirmede eksiksiz gelsin.
    """
    loaded = trimesh.load(str(src), force="scene")
    mesh = loaded.to_geometry() if isinstance(loaded, trimesh.Scene) else loaded
    if not isinstance(mesh, trimesh.Trimesh) or len(mesh.faces) == 0:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Mesh yüklenemedi")

    with tempfile.TemporaryDirectory(prefix="export-obj-") as td:
        mesh.export(str(Path(td) / "model.obj"))
        out_zip.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(out_zip, "w", zipfile.ZIP_DEFLATED) as zf:
            for f in sorted(Path(td).iterdir()):
                if f.is_file():
                    zf.write(str(f), f.name)


def _export_fbx(src: Path, out_fbx: Path, blender: str) -> None:
    """GLB → FBX Blender başsız alt-süreç. Hata → HTTPException(422)."""
    out_fbx.parent.mkdir(parents=True, exist_ok=True)
    cmd = [blender, "-b", "-P", str(_BLENDER_SCRIPT), "--", str(src), str(out_fbx)]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=_TIMEOUT_S)
    except subprocess.TimeoutExpired as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            "Blender zaman aşımına uğradı") from exc
    except OSError as exc:  # binary silinmiş/çalıştırılamıyor
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            "Blender çalıştırılamadı; FBX dışa-aktarma yapılamıyor.") from exc
    if proc.returncode != 0 or not out_fbx.exists():
        tail = (proc.stderr or proc.stdout or "")[-400:]
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            f"Blender FBX dışa-aktarma başarısız: {tail}")


@router.post("/{project_id}/export3d")
def export3d(project_id: str, payload: Export3dRequest,
             db: Session = Depends(get_db)) -> dict:
    _require_project(db, project_id)
    src = _mesh_path(db, project_id)
    if not src.exists():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Mesh yok")

    fmt = payload.format
    out = _out_path(project_id, fmt)

    if fmt == "obj":
        # Ağır işi sınırlı havuza al (max 2 eşzamanlı); sonucu bekle.
        _EXPORT_POOL.submit(_export_obj, src, out).result()
    else:  # fbx
        blender = _blender_bin()
        # Binary yoksa erken 422 (indirme kullanıcı onayına bağlı).
        if not Path(blender).exists():
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                                "blender kurulu değil")
        _EXPORT_POOL.submit(_export_fbx, src, out, blender).result()

    return {
        "url": f"/projects/{project_id}/export3d.{fmt}",
        "size_bytes": out.stat().st_size,
    }


@router.get("/{project_id}/export3d.{fmt}")
def download_export(project_id: str, fmt: str,
                    db: Session = Depends(get_db)) -> FileResponse:
    """Üretilmiş export dosyasını servis et (authed; frontend blob ile çeker)."""
    _require_project(db, project_id)
    fmt = fmt.lower()
    if fmt not in _FORMATS:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            f"Desteklenmeyen format: {fmt} ({list(_FORMATS)})")
    out = _out_path(project_id, fmt)
    if not out.exists():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Export dosyası yok")
    if fmt == "obj":
        return FileResponse(out, media_type="application/zip",
                            filename=f"{project_id}_obj.zip")
    return FileResponse(out, media_type="application/octet-stream",
                        filename=f"{project_id}.fbx")
