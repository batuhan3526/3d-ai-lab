"""OpenAI Images (gpt-image-*). Bearer anahtar, SENKRON, yanıt hep base64.
Motif için şeffaf zemin istenir (background=transparent, png)."""
from __future__ import annotations

import base64

from cloud_worker.http import CloudError, client, json_of

URL = "https://api.openai.com/v1/images/generations"
NAME = "OpenAI"


def text_to_image(prompt: str, params: dict, key: str, *, seed: int = 42, tick=None, variant: str = "") -> bytes:
    detail = params.get("detail", "medium")
    body = {"model": "gpt-image-1-mini" if detail == "low" else "gpt-image-1",
            "prompt": prompt, "size": "1024x1024", "quality": detail,
            "background": "transparent", "output_format": "png", "n": 1}
    if tick:
        tick(20)
    with client({"Authorization": f"Bearer {key}"}, timeout=300) as c:  # 2 dk sürebilir
        res = json_of(c.post(URL, json=body), NAME)
    data = res.get("data") or []
    if not data or not data[0].get("b64_json"):
        raise CloudError(f"{NAME}: görsel dönmedi")
    return base64.b64decode(data[0]["b64_json"])
