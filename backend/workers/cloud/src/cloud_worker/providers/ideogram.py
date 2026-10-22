"""Ideogram v2 — şeffaf PNG uç noktası (ideogram-3-transparent, JSON, senkron).
`Api-Key` başlığı. data[0].url, is_image_safe=false ise boş gelir."""
from __future__ import annotations

from cloud_worker.http import CloudError, client, download, json_of

URL = "https://api.ideogram.ai/v2/image/generate/ideogram-3-transparent"
NAME = "Ideogram"
_SPEED = {"low": "turbo", "medium": "default", "high": "quality"}


def text_to_image(prompt: str, params: dict, key: str, *, seed: int = 42, tick=None, variant: str = "") -> bytes:
    body = {"prompt": prompt, "aspect_ratio": "1x1",
            "rendering_speed": _SPEED.get(params.get("detail", "medium"), "default"),
            "seed": int(seed), "magic_prompt": "off"}
    if tick:
        tick(20)
    with client({"Api-Key": key}, timeout=180) as c:
        res = json_of(c.post(URL, json=body), NAME)
    data = res.get("data") or []
    if not data:
        raise CloudError(f"{NAME}: görsel dönmedi")
    if not data[0].get("url"):
        raise CloudError(f"{NAME}: görsel güvenlik filtresine takıldı (is_image_safe=false)")
    return download(data[0]["url"], NAME)
