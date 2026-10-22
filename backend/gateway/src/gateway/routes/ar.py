"""AR varlığı (USDZ) yükleme + servis — Task E2.

Frontend three.js `USDZExporter` ile sahne mesh'ini USDZ'e çevirir ve buraya
yükler. Modal iOS Quick Look (`<a rel="ar" href=usdz>`) için `usdz_url`'i,
Android Scene Viewer intent'i için `glb_url`'i kullanır; QR ise LAN host linkini.

GET public: iOS Quick Look ve Android Scene Viewer isteğe Authorization header
EKLEYEMEZ (mesh/thumbnail public servis deseni). USDZ, UUID proje id ile
adreslenir ve uygulama zaten LAN/Tailscale arkasındadır.
"""
from __future__ import annotations

import html
from pathlib import Path

from common.config import get_settings
from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, status
from fastapi.responses import FileResponse, HTMLResponse
from sqlalchemy.orm import Session

from gateway.auth import require_token
from gateway.db import get_db
from gateway.models.orm import Project

# Yazma (yükleme) korumalı; okuma (usdz servis) public — thumbnail/mesh deseni.
router = APIRouter(prefix="/projects", dependencies=[require_token()])
public_router = APIRouter(prefix="/projects")

_USER = "default"


def _ar_path(project_id: str) -> Path:
    """USDZ varlığının kanonik yolu — proje klasöründe mesh.glb'nin yanında."""
    return Path(get_settings().projects_dir) / _USER / project_id / "ar.usdz"


def _require_project(db: Session, project_id: str) -> Project:
    proj = db.get(Project, project_id)
    if proj is None or proj.user_id != _USER:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Proje bulunamadı")
    return proj


@router.post("/{project_id}/ar-asset")
def upload_ar_asset(project_id: str, file: UploadFile,
                    db: Session = Depends(get_db)) -> dict:
    """Client'ın ürettiği USDZ ikilisini proje klasörüne kaydeder.

    Döner: iOS Quick Look için `usdz_url` (public GET) + Android Scene Viewer
    intent'inin işaret edeceği `glb_url` (mevcut public mesh servisi).
    """
    _require_project(db, project_id)
    path = _ar_path(project_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(file.file.read())
    return {
        "usdz_url": f"/projects/{project_id}/ar.usdz",
        "glb_url": f"/projects/{project_id}/mesh",
    }


@public_router.get("/{project_id}/ar.usdz")
def get_ar_asset(project_id: str, db: Session = Depends(get_db)) -> FileResponse:
    _require_project(db, project_id)
    path = _ar_path(project_id)
    if not path.exists():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "AR varlığı yok")
    return FileResponse(path, media_type="model/vnd.usd+zip",
                        filename=f"{project_id}.usdz")


def _scene_viewer_intent(glb_url: str) -> str:
    """Android Scene Viewer intent — GLB linki gömülü, ARCore ile açar.

    QR'ı doğrudan .usdz'e yönlendirmek Android'de açılamayan bir dosya indirir;
    Android'in GLB'yi Scene Viewer üzerinden alması gerekir (R4).
    """
    return (
        f"intent://arvr.google.com/scene-viewer/1.0?file={glb_url}"
        f"&mode=ar_preferred#Intent;scheme=https;package=com.google.ar.core;"
        f"action=android.intent.action.VIEW;"
        f"S.browser_fallback_url={glb_url};end"
    )


@public_router.get("/{project_id}/ar", response_class=HTMLResponse)
def ar_landing(project_id: str, request: Request,
               db: Session = Depends(get_db)) -> HTMLResponse:
    """UA-yönlendirmeli AR açılış sayfası (tokensız, QR hedefi) — R4.

    QR bu sayfayı kodlar. Telefon tarayınca User-Agent'e göre yönlendirir:
      * iPhone/iPad → Safari .usdz'i doğrudan AR Quick Look ile açar.
      * Android → Scene Viewer intent'i (GLB) — ARCore ile AR başlar.
      * Masaüstü/diğer → her iki bağlantıyı da içeren basit sayfa.

    Mutlak URL'ler isteğin Host başlığından kurulur ki aynı LAN'daki telefon
    erişebilsin (mesh/usdz zaten public servis).
    """
    _require_project(db, project_id)
    ua = request.headers.get("user-agent", "").lower()
    # Vite proxy (:3000 → :9000, /api strip) arkasında Host=localhost:9000 görünür;
    # telefonun GERÇEK adresi X-Forwarded-Host'ta (vite xfwd: true). Proxy'den
    # geçildiyse asset URL'leri de /api önekiyle kurulmalı ki telefon aynı yoldan erişsin.
    fwd_host = request.headers.get("x-forwarded-host", "")
    if fwd_host:
        scheme = request.headers.get("x-forwarded-proto", "") or request.url.scheme
        base = f"{scheme}://{fwd_host}/api"
    else:
        scheme = request.url.scheme
        base = f"{scheme}://{request.headers.get('host', '')}"
    usdz_url = f"{base}/projects/{project_id}/ar.usdz"
    glb_url = f"{base}/projects/{project_id}/mesh"

    is_ios = "iphone" in ua or "ipad" in ua or "ipod" in ua
    # iPadOS Safari masaüstü UA verir; "macintosh"+dokunma ile ayırt edilemez
    # ama iPhone/iPad çoğunlukla yukarıdaki ile yakalanır.
    is_android = "android" in ua

    if is_ios:
        safe = html.escape(usdz_url, quote=True)
        body = (
            f'<meta http-equiv="refresh" content="0; url={safe}">'
            f'<script>location.href={_js_str(usdz_url)};</script>'
            f'<p>AR açılıyor… <a rel="ar" href="{safe}">'
            f'<img src="{safe}" alt="AR" style="display:none">Aç</a></p>'
        )
    elif is_android:
        intent = _scene_viewer_intent(glb_url)
        safe = html.escape(intent, quote=True)
        body = (
            f'<script>location.href={_js_str(intent)};</script>'
            f'<p>AR açılıyor… <a href="{safe}">Aç</a></p>'
            f'<p style="font-size:12px;color:#888">Açılmazsa '
            f'"Google Play Services for AR (ARCore)" kurulu olmalı.</p>'
        )
    else:
        su = html.escape(usdz_url, quote=True)
        sg = html.escape(glb_url, quote=True)
        body = (
            f'<p>Telefonunuzla AR olarak görmek için QR kodu tarayın.</p>'
            f'<p><a href="{su}">iOS (Quick Look .usdz)</a></p>'
            f'<p><a href="{sg}">Android (GLB / Scene Viewer)</a></p>'
        )

    page = (
        '<!doctype html><html lang="tr"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        '<title>AR</title></head><body style="font-family:sans-serif;'
        'text-align:center;padding:2rem">' + body + '</body></html>'
    )
    return HTMLResponse(page)


def _js_str(value: str) -> str:
    """Güvenli JS string literali — `location.href=<bu>` için."""
    escaped = (
        value.replace("\\", "\\\\").replace('"', '\\"')
        .replace("<", "\\u003c").replace(">", "\\u003e")
        .replace("\n", "").replace("\r", "")
    )
    return f'"{escaped}"'
