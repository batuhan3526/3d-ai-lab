"""Recraft (OpenAI-uyumlu, senkron). Bearer anahtar. Raster model + PNG (vektör modeller
SVG döner; hattımız PNG ister). b64_json istenir → URL indirmeye gerek yok."""
from __future__ import annotations

import base64

from cloud_worker.http import CloudError, client, download, json_of

URL = "https://external.api.recraft.ai/v1/images/generations"
NAME = "Recraft"


def text_to_image(prompt: str, params: dict, key: str, *, seed: int = 42, tick=None, variant: str = "") -> bytes:
    body = {"prompt": prompt[:1000], "model": "recraftv3", "style": "digital_illustration",
            "size": "1024x1024", "n": 1, "image_format": "png", "response_format": "b64_json",
            "random_seed": int(seed)}
    if tick:
        tick(20)
    with client({"Authorization": f"Bearer {key}"}, timeout=180) as c:
        res = json_of(c.post(URL, json=body), NAME)
    data = (res.get("data") or [{}])[0]
    if data.get("b64_json"):
        return base64.b64decode(data["b64_json"])
    if data.get("url"):
        return download(data["url"], NAME)
    raise CloudError(f"{NAME}: görsel dönmedi")
