"""Meshy API (docs.meshy.ai). Bearer anahtar. Metin→3D iki aşama: preview (şekil) +
refine (doku). Görsel→3D tek istek; görsel data URI olarak gider (yükleme yok)."""
from __future__ import annotations

from pathlib import Path

from cloud_worker.http import CloudError, client, data_uri, download, json_of, poll

BASE = "https://api.meshy.ai"
NAME = "Meshy"
_POLY = {"low": 10_000, "medium": 30_000, "high": 100_000}


def _headers(key: str) -> dict:
    return {"Authorization": f"Bearer {key}"}


def _wait(c, url: str, tick, lo: float, hi: float) -> dict:
    def failed(d: dict) -> str | None:
        st = d.get("status")
        if st in ("FAILED", "CANCELED"):
            return (d.get("task_error") or {}).get("message") or st
        if st not in ("PENDING", "IN_PROGRESS", "SUCCEEDED"):
            return f"durum={st}"
        return None

    def on_tick(d: dict) -> None:
        if tick and d.get("progress") is not None:
            tick(lo + (hi - lo) * float(d["progress"]) / 100.0)

    return poll(lambda: json_of(c.get(url), NAME), lambda d: d.get("status") == "SUCCEEDED",
                failed, provider=NAME, interval=4.0, timeout=1200, on_tick=on_tick)


def _glb(task: dict) -> tuple[bytes, str]:
    url = (task.get("model_urls") or {}).get("glb")
    if not url:
        raise CloudError(f"{NAME}: GLB bağlantısı yok")
    return download(url, NAME), "glb"


def _create(c, path: str, body: dict) -> str:
    tid = json_of(c.post(f"{BASE}{path}", json=body), NAME).get("result")
    if not tid:
        raise CloudError(f"{NAME}: görev kimliği dönmedi")
    return tid


def text_to_3d(prompt: str, params: dict, key: str, tick=None, *, variant: str = "") -> tuple[bytes, str]:
    poly = _POLY.get(params.get("detail", "medium"), 30_000)
    with client(_headers(key)) as c:
        pid = _create(c, "/openapi/v2/text-to-3d", {
            "mode": "preview", "prompt": prompt[:800], "ai_model": "latest",
            "target_formats": ["glb"], "should_remesh": True, "topology": "triangle",
            "target_polycount": poly})
        task = _wait(c, f"{BASE}/openapi/v2/text-to-3d/{pid}", tick, 0, 50)
        if params.get("texture", True):
            rid = _create(c, "/openapi/v2/text-to-3d", {
                "mode": "refine", "preview_task_id": pid, "enable_pbr": True,
                "texture_prompt": prompt[:600]})
            task = _wait(c, f"{BASE}/openapi/v2/text-to-3d/{rid}", tick, 50, 100)
    return _glb(task)


def image_to_3d(image: Path, params: dict, key: str, tick=None, *, variant: str = "") -> tuple[bytes, str]:
    tex = bool(params.get("texture", True))
    with client(_headers(key)) as c:
        tid = _create(c, "/openapi/v1/image-to-3d", {
            "image_url": data_uri(image), "ai_model": "latest", "should_texture": tex,
            "enable_pbr": tex, "should_remesh": True,
            "target_polycount": _POLY.get(params.get("detail", "medium"), 30_000),
            "target_formats": ["glb"]})
        task = _wait(c, f"{BASE}/openapi/v1/image-to-3d/{tid}", tick, 0, 100)
    return _glb(task)
