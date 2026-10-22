"""Stability AI v2beta (resmi OpenAPI). Bearer anahtar. SENKRON: yanıt gövdesi dosyanın
kendisi (GLB / PNG). İstekler multipart; görselsiz çağrıda prompt dosya-adsız parça."""
from __future__ import annotations

from pathlib import Path

from cloud_worker.http import CloudError, check, client

BASE = "https://api.stability.ai/v2beta"
NAME = "Stability AI"


def image_to_3d(image: Path, params: dict, key: str, tick=None, *, variant: str = "") -> tuple[bytes, str]:
    tex = {"low": "512", "medium": "1024", "high": "2048"}.get(params.get("detail", "medium"), "1024")
    mime = "image/jpeg" if image.suffix.lower() in (".jpg", ".jpeg") else "image/png"
    if tick:
        tick(20)
    with client({"Authorization": f"Bearer {key}"}, timeout=300) as c:
        r = check(c.post(f"{BASE}/3d/stable-fast-3d",
                         files={"image": (image.name, image.read_bytes(), mime)},
                         data={"texture_resolution": tex, "remesh": "none"}), NAME)
    if r.content[:4] != b"glTF":
        raise CloudError(f"{NAME}: GLB yerine {r.headers.get('content-type')} döndü")
    return r.content, "glb"


def text_to_3d(prompt: str, params: dict, key: str, tick=None, *, variant: str = "") -> tuple[bytes, str]:
    raise CloudError(f"{NAME}: metin→3D yok (yalnız görsel→3D)")


def text_to_image(prompt: str, params: dict, key: str, *, seed: int = 42, tick=None, variant: str = "") -> bytes:
    endpoint = "ultra" if params.get("detail") == "high" else "core"
    with client({"Authorization": f"Bearer {key}", "Accept": "image/*"}, timeout=180) as c:
        r = check(c.post(f"{BASE}/stable-image/generate/{endpoint}",
                         files=[("prompt", (None, prompt.encode()))],
                         data={"aspect_ratio": "1:1", "output_format": "png", "seed": str(int(seed))}), NAME)
    if not r.headers.get("content-type", "").startswith("image/"):
        raise CloudError(f"{NAME}: görsel yerine {r.headers.get('content-type')} döndü")
    return r.content
