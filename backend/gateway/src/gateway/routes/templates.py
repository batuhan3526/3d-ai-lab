"""Şablon galerisi — public katalog, auth yok.

GET /templates             -> manifest.json içeriği (kıyafet şablonları)
GET /templates/mannequins  -> mannequins/manifest.json içeriği (statik manken base-mesh'leri)
Statik GLB/PNG dosyaları main.py'de StaticFiles ile /template-assets altında servis edilir
(mankenler `/template-assets/mannequins/<file>` altında).
"""
import json

from common.config import get_settings
from fastapi import APIRouter, HTTPException, status

router = APIRouter()

# Manken manifest satırı için beklenen anahtarlar (frontend Mannequin.tsx ile eş).
_MANNEQUIN_KEYS = {"id", "label", "file", "pose", "license", "source_url"}
_MANNEQUIN_POSES = {"T", "A"}


@router.get("/templates")
async def list_templates() -> dict:
    """Tüm kıyafet türleri ve şablonların manifest'i."""
    manifest_path = get_settings().templates_dir / "manifest.json"
    if not manifest_path.exists():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Şablonlar henüz üretilmedi (generate.py çalıştırın).",
        )
    return json.loads(manifest_path.read_text(encoding="utf-8"))


@router.get("/templates/mannequins")
async def list_mannequins() -> list:
    """Statik manken base-mesh manifest'i.

    Şema: `[{id, label, file, pose:"T"|"A", license:"CC0", source_url, available}]`.
    Manifest yoksa boş liste döner (kırılmaz) — panel "manken indirilmemiş →
    download_models.sh" uyarısını gösterir. GLB dosyaları
    `/template-assets/mannequins/<file>` altında servis edilir; manifest listede
    kalsa bile GLB indirilmemiş/üretilmemiş olabilir (graceful degrade).

    `available` her istekte CANLI hesaplanır (önbelleksiz): GLB dosyası
    `templates_dir/<file>` altında diskte varsa `True`, yoksa `False`. Frontend
    `available===false` mankenleri devre dışı gösterir; ev-içi GLB üretimi bitip
    dosya diske düşünce bir sonraki istekte otomatik `True` olur ve buton açılır.
    """
    templates_dir = get_settings().templates_dir
    manifest_path = templates_dir / "mannequins" / "manifest.json"
    data: list = []
    if manifest_path.exists():
        loaded = json.loads(manifest_path.read_text(encoding="utf-8"))
        # Bozuk/eski format (liste değil) → taban listesi boş (kırılmaz).
        if isinstance(loaded, list):
            data = loaded
    # F3: ölçüden üretilmiş özel mankenler (mannequins/custom_manifest.json) sona
    # eklenir, "custom": true bayraklı (frontend silme butonu bunu kullanır).
    from gateway.routes.mannequins import read_custom_manifest
    for entry in read_custom_manifest(templates_dir / "mannequins"):
        data.append({**entry, "custom": True})
    for entry in data:
        if isinstance(entry, dict):
            rel = entry.get("file")
            entry["available"] = bool(rel) and (templates_dir / rel).is_file()
    return data
