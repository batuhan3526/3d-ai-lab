"""Neural4D OpenAPI v1 (DreamTech, Direct3D-S2; docs.neural4d.com). Bearer anahtar, ücretli abonelik
şart (yoksa 403 subscription_required). Yerel görsel /files'a yüklenir (base64 yok) → file_id.
Sorgu: /tasks/task-info?id= → status queued/processing/succeeded/failed, GLB output.models[0].model_urls.glb."""
from __future__ import annotations

from pathlib import Path

from cloud_worker.http import CloudError, client, download, json_of, poll

BASE = "https://api.neural4d.com/openapi/v1"
MODEL = "dreamtech/neural4d-2.5"
NAME = "Neural4D"


def _headers(key: str) -> dict:
    return {"Authorization": f"Bearer {key}"}


def _opts(params: dict) -> dict:
    tex = bool(params.get("texture", True))
    q = {"low": "standard", "medium": "standard", "high": "high"}[params.get("detail", "medium")]
    poly = {"low": 100_000, "medium": 500_000, "high": 1_000_000}[params.get("detail", "medium")]
    return {"model": MODEL, "with_texture": tex, "with_pbr": tex and params.get("detail") == "high",
            "mesh_quality": q, "topology": "triangle", "target_polycount": poly, "n": 1}


def _run(c, body: dict, tick) -> tuple[bytes, str]:
    task = json_of(c.post(f"{BASE}/3dmodels/generations", json=body), NAME).get("id")
    if not task:
        raise CloudError(f"{NAME}: görev kimliği dönmedi")

    def failed(d: dict) -> str | None:
        st = d.get("status")
        if st == "failed":
            return (d.get("error") or {}).get("message") or st
        return None if st in ("queued", "processing", "succeeded") else f"durum={st}"

    done = poll(lambda: json_of(c.get(f"{BASE}/tasks/task-info", params={"id": task}), NAME),
                lambda d: d.get("status") == "succeeded", failed, provider=NAME, interval=5.0, timeout=1200,
                on_tick=lambda d: tick and tick(50.0 if d.get("status") == "processing" else 10.0))
    models = (done.get("output") or {}).get("models") or []
    url = ((models[0] if models else {}).get("model_urls") or {}).get("glb")
    if not url:
        raise CloudError(f"{NAME}: sonuçta GLB yok")
    return download(url, NAME), "glb"


def text_to_3d(prompt: str, params: dict, key: str, tick=None, *, variant: str = "") -> tuple[bytes, str]:
    with client(_headers(key)) as c:
        return _run(c, {"prompt": prompt[:500], **_opts(params)}, tick)


def image_to_3d(image: Path, params: dict, key: str, tick=None, *, variant: str = "") -> tuple[bytes, str]:
    mime = "image/jpeg" if image.suffix.lower() in (".jpg", ".jpeg") else "image/png"
    with client(_headers(key)) as c:
        fid = json_of(c.post(f"{BASE}/files", files={"file": (image.name, image.read_bytes(), mime)}), NAME).get("id")
        if not fid:
            raise CloudError(f"{NAME}: görsel yüklenemedi")
        return _run(c, {"input_references": [{"type": "image", "file_id": fid}], **_opts(params)}, tick)
