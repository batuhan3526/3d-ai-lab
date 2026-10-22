"""Tripo3D API v3 (docs: developers.tripo3d.com, v2 kapatılıyor). Bearer anahtar.
Görsel önce /v3/files'a yüklenir (v3 base64 kabul etmez) → file_token."""
from __future__ import annotations

from pathlib import Path

from cloud_worker.http import CloudError, client, download, json_of, poll

BASE = "https://openapi.tripo3d.com/v3"
MODEL = "v3.1-20260211"
NAME = "Tripo3D"
_FAIL = {"failed", "cancelled", "banned", "expired"}
_RUN = {"queued", "running"}


def _headers(key: str) -> dict:
    return {"Authorization": f"Bearer {key}"}


def _data(resp_json: dict) -> dict:
    if resp_json.get("code", 0) != 0:
        raise CloudError(f"{NAME} hata {resp_json.get('code')}: {resp_json.get('message', '')} "
                         f"{resp_json.get('suggestion', '')}".strip())
    return resp_json.get("data") or {}


def _opts(params: dict) -> dict:
    hi = params.get("detail") == "high"
    o = {"model": MODEL, "texture": bool(params.get("texture", True)),
         "pbr": bool(params.get("texture", True)),
         "texture_quality": "detailed" if hi else "standard",
         "geometry_quality": "detailed" if hi else "standard"}
    if params.get("seed"):
        o["model_seed"] = int(params["seed"])
        o["texture_seed"] = int(params["seed"])
    return o


def _run(key: str, path: str, body: dict, tick) -> tuple[bytes, str]:
    with client(_headers(key)) as c:
        task_id = _data(json_of(c.post(f"{BASE}{path}", json=body), NAME)).get("task_id")
        if not task_id:
            raise CloudError(f"{NAME}: task_id dönmedi")

        def fetch() -> dict:
            return _data(json_of(c.get(f"{BASE}/tasks/{task_id}"), NAME))

        def failed(d: dict) -> str | None:
            st = d.get("status")
            if st in _FAIL or (st not in _RUN and st != "success"):
                return f"durum={st}"
            return None

        done = poll(fetch, lambda d: d.get("status") == "success", failed, provider=NAME,
                    interval=2.0, timeout=600, on_tick=lambda d: tick and tick(d.get("progress")))
    url = (done.get("output") or {}).get("model_url")
    if not url:
        raise CloudError(f"{NAME}: model_url yok")
    # Bağlantı ~5 dk geçerli → hemen indir.
    return download(url, NAME), "glb"


def text_to_3d(prompt: str, params: dict, key: str, tick=None, *, variant: str = "") -> tuple[bytes, str]:
    return _run(key, "/generation/text-to-model", {"prompt": prompt[:1024], **_opts(params)}, tick)


def image_to_3d(image: Path, params: dict, key: str, tick=None, *, variant: str = "") -> tuple[bytes, str]:
    mime = "image/jpeg" if image.suffix.lower() in (".jpg", ".jpeg") else "image/png"
    with client(_headers(key)) as c:
        up = _data(json_of(c.post(f"{BASE}/files", files={"file": (image.name, image.read_bytes(), mime)}), NAME))
    token = up.get("file_token")
    if not token:
        raise CloudError(f"{NAME}: görsel yüklenemedi (file_token yok)")
    return _run(key, "/generation/image-to-model", {"input": token, **_opts(params)}, tick)
