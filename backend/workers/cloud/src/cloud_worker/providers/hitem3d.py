"""Hitem3D (Hi3D, Math Magic; docs.hi3d.ai). İki adım kimlik: `client_id:client_secret` Basic ile
/auth/token → accessToken (Bearer). Görsel multipart yüklenir; format=2 → GLB (varsayılan OBJ).
Sorgu: data.state created/queueing/processing/success/failed, sonuç data.url (1 saat geçerli)."""
from __future__ import annotations

import base64
from pathlib import Path

from cloud_worker.http import CloudError, client, download, json_of, poll

BASE = "https://api.hitem3d.ai/open-api/v1"
MODEL = "hi3dv3.0"
NAME = "Hitem3D"
_RUN = {"created", "queueing", "processing"}


def _data(j: dict) -> dict:
    if j.get("code") != 200:
        raise CloudError(f"{NAME} hata {j.get('code')}: {j.get('msg') or j.get('message') or ''}".strip())
    return j.get("data") or {}


def token(key: str) -> str:
    if ":" not in key:
        raise CloudError(f"{NAME}: anahtar 'CLIENT_ID:CLIENT_SECRET' biçiminde olmalı (HITEM3D_API_KEY)")
    basic = base64.b64encode(key.encode()).decode()
    with client({"Authorization": f"Basic {basic}", "Content-Type": "application/json"}) as c:
        tok = _data(json_of(c.post(f"{BASE}/auth/token"), NAME)).get("accessToken")
    if not tok:
        raise CloudError(f"{NAME}: erişim belirteci alınamadı")
    return tok


def image_to_3d(image: Path, params: dict, key: str, tick=None, *, variant: str = "") -> tuple[bytes, str]:
    tex = bool(params.get("texture", True))
    hi = params.get("detail") == "high"
    form = {"request_type": "3" if tex else "1", "model": MODEL,
            "resolution": "2048master" if hi else "2048quality",
            "face": str({"low": 500_000, "medium": 1_000_000, "high": 2_000_000}[params.get("detail", "medium")]),
            "format": "2", "pbr": "1" if tex else "0"}
    mime = "image/jpeg" if image.suffix.lower() in (".jpg", ".jpeg") else "image/png"
    with client({"Authorization": f"Bearer {token(key)}"}) as c:
        task = _data(json_of(c.post(f"{BASE}/submit-task", data=form,
                                    files={"images": (image.name, image.read_bytes(), mime)}), NAME)).get("task_id")
        if not task:
            raise CloudError(f"{NAME}: task_id dönmedi")

        def failed(d: dict) -> str | None:
            st = d.get("state")
            return None if st in _RUN or st == "success" else f"durum={st}"

        done = poll(lambda: _data(json_of(c.get(f"{BASE}/query-task", params={"task_id": task}), NAME)),
                    lambda d: d.get("state") == "success", failed, provider=NAME, interval=6.0, timeout=3600,
                    on_tick=lambda d: tick and tick(50.0 if d.get("state") == "processing" else 10.0))
    if not done.get("url"):
        raise CloudError(f"{NAME}: model bağlantısı yok")
    return download(done["url"], NAME), "glb"


def text_to_3d(prompt: str, params: dict, key: str, tick=None, *, variant: str = "") -> tuple[bytes, str]:
    raise CloudError(f"{NAME}: yalnız görsel→3D destekleniyor")
