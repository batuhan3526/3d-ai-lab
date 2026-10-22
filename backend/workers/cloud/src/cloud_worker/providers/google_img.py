"""Google Gemini görsel üretimi (Nano Banana ailesi) — :generateContent, x-goog-api-key.
Imagen 4 Gemini API'de kapatıldı; uygulanmadı. Görsel parts[].inlineData'da base64."""
from __future__ import annotations

import base64

from cloud_worker.http import CloudError, client, json_of

BASE = "https://generativelanguage.googleapis.com/v1beta/models"
NAME = "Google Gemini"
_MODEL = {"nanobanana": "gemini-3.1-flash-image", "nanobananapro": "gemini-3-pro-image"}


def text_to_image(prompt: str, params: dict, key: str, *, seed: int = 42, tick=None, variant: str = "") -> bytes:
    model = _MODEL.get(variant, _MODEL["nanobanana"])
    size = "2K" if params.get("detail") == "high" else "1K"
    body = {"contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"responseModalities": ["TEXT", "IMAGE"],
                                 "imageConfig": {"aspectRatio": "1:1", "imageSize": size}}}
    if tick:
        tick(20)
    with client({"x-goog-api-key": key}, timeout=180) as c:
        res = json_of(c.post(f"{BASE}/{model}:generateContent", json=body), NAME)
    cands = res.get("candidates") or []
    for part in ((cands[0].get("content") or {}).get("parts") or []) if cands else []:
        inline = part.get("inlineData") or part.get("inline_data")
        if inline and inline.get("data"):
            return base64.b64decode(inline["data"])
    reason = (cands[0].get("finishReason") if cands else None) or \
        (res.get("promptFeedback") or {}).get("blockReason") or "görsel yok"
    raise CloudError(f"{NAME}: görsel dönmedi ({reason})")
