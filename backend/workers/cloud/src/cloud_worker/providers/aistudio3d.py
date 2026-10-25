"""3D AI Studio API (3daistudio.com/Platform/API/Documentation). Bearer anahtar; tek hesapla
Hunyuan 3D Pro ve TRELLIS.2. Görsel JSON'da data URI. Varsayılan sınır dakikada 3 istek →
yavaş sorgulanır. Durum PENDING/IN_PROGRESS/FINISHED/FAILED, sonuç results[0].asset (GLB)."""
from __future__ import annotations

from pathlib import Path

from cloud_worker.http import CloudError, client, data_uri, download, json_of, poll

BASE = "https://api.3daistudio.com/v1"
NAME = "3D AI Studio"


def _run(key: str, path: str, body: dict, tick) -> tuple[bytes, str]:
    with client({"Authorization": f"Bearer {key}"}) as c:
        task = json_of(c.post(f"{BASE}{path}", json=body), NAME).get("task_id")
        if not task:
            raise CloudError(f"{NAME}: task_id dönmedi")

        def failed(d: dict) -> str | None:
            st = d.get("status")
            if st == "FAILED":
                return d.get("failure_reason") or st
            return None if st in ("PENDING", "IN_PROGRESS", "FINISHED") else f"durum={st}"

        done = poll(lambda: json_of(c.get(f"{BASE}/generation-request/{task}/status/"), NAME),
                    lambda d: d.get("status") == "FINISHED", failed, provider=NAME, interval=25.0,
                    timeout=1800, on_tick=lambda d: tick and tick(d.get("progress")))
    res = next((r for r in done.get("results") or [] if r.get("asset_type") == "3D_MODEL" and r.get("asset")), None)
    if not res:
        raise CloudError(f"{NAME}: sonuçta GLB yok")
    return download(res["asset"], NAME), "glb"


def _hunyuan(params: dict) -> dict:
    tex = bool(params.get("texture", True))
    return {"model": "3.1", "generate_type": "Normal" if tex else "Geometry",
            "enable_pbr": tex and params.get("detail") == "high",
            "face_count": {"low": 100_000, "medium": 500_000, "high": 1_000_000}[params.get("detail", "medium")]}


def text_to_3d(prompt: str, params: dict, key: str, tick=None, *, variant: str = "") -> tuple[bytes, str]:
    if variant != "hunyuan3d":
        raise CloudError(f"{NAME}: {variant} metin→3D desteklemiyor")
    return _run(key, "/3d-models/tencent/generate/pro/", {"prompt": prompt[:1024], **_hunyuan(params)}, tick)


def image_to_3d(image: Path, params: dict, key: str, tick=None, *, variant: str = "") -> tuple[bytes, str]:
    if variant == "hunyuan3d":
        return _run(key, "/3d-models/tencent/generate/pro/", {"image": data_uri(image), **_hunyuan(params)}, tick)
    if variant == "trellis2":
        detail = params.get("detail", "medium")
        body = {"image": data_uri(image), "resolution": {"low": "512", "medium": "1024", "high": "1536"}[detail],
                "textures": bool(params.get("texture", True)), "texture_size": 4096 if detail == "high" else 2048}
        if params.get("seed"):
            body["seed"] = int(params["seed"])
        return _run(key, "/3d-models/trellis2/generate/", body, tick)
    raise CloudError(f"{NAME}: bilinmeyen 3D modeli {variant}")
