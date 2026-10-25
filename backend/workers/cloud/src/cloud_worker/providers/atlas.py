"""Atlas Cloud (atlascloud.ai/docs/predictions) — ByteDance Seed3D 2.0. Bearer anahtar, tek genel
gönderim ucu (model alanı seçer) + tahmin sorgusu. Seed3D çıktısı içinde tek 3D dosya olan bir ZIP."""
from __future__ import annotations

import io
import zipfile
from pathlib import Path

from cloud_worker.http import CloudError, client, data_uri, download, json_of, poll

BASE = "https://api.atlascloud.ai/api/v1/model"
M_SEED3D = "bytedance/seed3d-v2.0/image-to-3d"
NAME = "Atlas Cloud"


def _glb_from(blob: bytes) -> bytes:
    if blob[:4] == b"glTF":
        return blob
    try:
        with zipfile.ZipFile(io.BytesIO(blob)) as z:
            name = next((n for n in z.namelist() if n.lower().endswith(".glb")), None)
            if name:
                return z.read(name)
    except zipfile.BadZipFile:
        pass
    raise CloudError(f"{NAME}: çıktıda GLB yok")


def image_to_3d(image: Path, params: dict, key: str, tick=None, *, variant: str = "") -> tuple[bytes, str]:
    body = {"model": M_SEED3D, "image": data_uri(image), "file_format": "glb",
            "subdivision_level": params.get("detail", "medium")}
    with client({"Authorization": f"Bearer {key}"}) as c:
        sub = json_of(c.post(f"{BASE}/generateImage", json=body), NAME)
        pid = (sub.get("data") or {}).get("id") or sub.get("id")
        if not pid:
            raise CloudError(f"{NAME}: tahmin kimliği dönmedi")

        def fetch() -> dict:
            j = json_of(c.get(f"{BASE}/prediction/{pid}"), NAME)
            return j.get("data") or j

        def failed(d: dict) -> str | None:
            st = d.get("status")
            if st == "failed":
                return str(d.get("error") or st)
            return None if st in ("created", "processing", "completed", "succeeded") else f"durum={st}"

        done = poll(fetch, lambda d: d.get("status") in ("completed", "succeeded"), failed, provider=NAME,
                    interval=5.0, timeout=1200, on_tick=lambda d: tick and tick(50.0))
    outs = done.get("outputs") or []
    if not outs:
        raise CloudError(f"{NAME}: çıktı yok")
    return _glb_from(download(outs[0], NAME)), "glb"


def text_to_3d(prompt: str, params: dict, key: str, tick=None, *, variant: str = "") -> tuple[bytes, str]:
    raise CloudError(f"{NAME}: Seed3D yalnız görsel→3D")
