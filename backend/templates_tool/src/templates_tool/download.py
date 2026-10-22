"""Poly Pizza CC0 model indirme overlay'i.

Prosedürel backbone'u (Task 1) gerçek CC0 GLB'lerle zenginleştirir.
POLY_PIZZA_API_KEY yoksa veya bir indirme başarısızsa o slot prosedürel kalır.

Çalıştır:
    cd backend/templates_tool
    uv run python -m templates_tool.download
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import httpx
from common.config import get_settings
from common.logging import get_logger

log = get_logger("templates.download")

_API = "https://api.poly.pizza/v1.2/search"
# Her garment türü için arama sorgusu (Poly Pizza CC0 etiketli sonuçlar)
_QUERIES = {
    "tshirt": "t-shirt",
    "shirt": "shirt",
    "pants": "pants",
    "skirt": "skirt",
    "hat": "hat",
    "boots": "boot",
}


@dataclass
class PolyModel:
    title: str
    download_url: str
    attribution: str = ""


def parse_search_results(payload: dict) -> list[PolyModel]:
    out: list[PolyModel] = []
    for r in payload.get("results", []):
        url = r.get("Download")
        if not url:
            continue
        out.append(PolyModel(
            title=r.get("Title", "Untitled"),
            download_url=url,
            attribution=r.get("Attribution", ""),
        ))
    return out


def search_cc0(query: str, api_key: str, limit: int) -> list[PolyModel]:
    headers = {"x-auth-token": api_key}
    params = {"Limit": limit, "Category": "Clothing"}
    with httpx.Client(timeout=20) as client:
        resp = client.get(f"{_API}/{query}", headers=headers, params=params)
        resp.raise_for_status()
        return parse_search_results(resp.json())


def _fetch_bytes(url: str) -> bytes:
    with httpx.Client(timeout=60, follow_redirects=True) as client:
        resp = client.get(url)
        resp.raise_for_status()
        return resp.content


def apply_downloads(templates_dir: Path, manifest_path: Path, api_key: str, per_type: int) -> int:
    """Manifest slotlarını mümkün olduğunca CC0 modellerle değiştir.

    Returns:
        Değiştirilen slot sayısı.
    """
    if not api_key:
        log.info("polypizza_skip", reason="no_api_key")
        return 0

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    changed = 0

    for garment in manifest["garments"]:
        gtype = garment["type"]
        query = _QUERIES.get(gtype, gtype)
        try:
            models = search_cc0(query, api_key=api_key, limit=per_type)
        except Exception as e:  # ağ/parse hatası -> bu tür prosedürel kalsın
            log.warning("polypizza_search_failed", garment=gtype, error=str(e))
            continue

        for slot, model in zip(garment["templates"], models, strict=False):
            try:
                data = _fetch_bytes(model.download_url)
            except Exception as e:
                log.warning("polypizza_fetch_failed", url=model.download_url, error=str(e))
                continue
            glb_rel = slot["glb"]  # örn. tshirt/tshirt-01.glb
            (templates_dir / glb_rel).write_bytes(data)
            slot["name"] = model.title or slot["name"]
            slot["license"] = f"CC0 — {model.attribution}".strip(" —")
            slot["source"] = "polypizza"
            changed += 1

    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    log.info("polypizza_done", changed=changed)
    return changed


def main() -> None:
    settings = get_settings()
    root = Path(settings.templates_dir)
    changed = apply_downloads(
        templates_dir=root,
        manifest_path=root / "manifest.json",
        api_key=settings.poly_pizza_api_key,
        per_type=5,
    )
    print(f"Poly Pizza overlay: {changed} slot güncellendi (kalan prosedürel).")


if __name__ == "__main__":
    main()
