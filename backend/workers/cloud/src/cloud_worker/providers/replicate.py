"""Replicate tahmin API'si (replicate.com/docs/reference/http). Bearer anahtar.
`Prefer: wait=60` ile çoğu iş tek istekte biter; bitmezse urls.get sorgulanır. Çıktı
dosyaları da yetki başlığı ister ve 1 saatte silinir → hemen indir. Girdi data URI
≤256 KB olmalı → görsel küçültülüp JPEG'e çevrilir."""
from __future__ import annotations

import base64
import io
from pathlib import Path

from cloud_worker.http import CloudError, client, download, json_of, poll

BASE = "https://api.replicate.com/v1"
NAME = "Replicate"
TRELLIS_VERSION = "firtoz/trellis:e8f6c45206993f297372f5436b90350817bd9b4a0d52d2a76df50c1c8afa2b3c"
TRELLIS2_VERSION = "fishwowater/trellis2:52e1ad6852599ea10ce8e257635a3c11485cba51c181ea5173e34d9b2955b226"
HUNYUAN_MODEL = "tencent/hunyuan-3d-3.1"     # resmi model → sürüm kimliği gerekmez
_MAX_URI = 250_000


def _headers(key: str, wait: bool = True) -> dict:
    h = {"Authorization": f"Bearer {key}"}
    if wait:
        h["Prefer"] = "wait=60"
    return h


def small_data_uri(image: Path) -> str:
    """Görseli ≤~250 KB JPEG data URI'ye indir (Replicate sınırı 256 KB)."""
    from PIL import Image
    img = Image.open(image).convert("RGB")
    side = 1024
    while True:
        im = img.copy()
        im.thumbnail((side, side))
        for q in (92, 85, 75):
            buf = io.BytesIO()
            im.save(buf, "JPEG", quality=q)
            uri = "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()
            if len(uri) <= _MAX_URI:
                return uri
        side = int(side * 0.75)
        if side < 256:
            raise CloudError(f"{NAME}: görsel 256 KB sınırına sığdırılamadı")


def run(path: str, body: dict, key: str, tick=None, timeout: float = 900) -> dict:
    with client(_headers(key), timeout=120) as c:
        pred = json_of(c.post(f"{BASE}{path}", json=body), NAME)
    if pred.get("status") not in ("succeeded",):
        get_url = (pred.get("urls") or {}).get("get") or f"{BASE}/predictions/{pred.get('id')}"
        with client(_headers(key, wait=False)) as c:
            def failed(d: dict) -> str | None:
                st = d.get("status")
                if st in ("failed", "canceled"):
                    return str(d.get("error") or st)
                if st not in ("starting", "processing", "succeeded"):
                    return f"durum={st}"
                return None
            pred = poll(lambda: json_of(c.get(get_url), NAME), lambda d: d.get("status") == "succeeded",
                        failed, provider=NAME, interval=3.0, timeout=timeout,
                        on_tick=lambda d: tick and tick(50.0 if d.get("status") == "processing" else 10.0))
    return pred


def _get(url: str, key: str) -> bytes:
    return download(url, NAME, headers={"Authorization": f"Bearer {key}"})


def _url_of(out) -> str | None:
    """Çıktı tek URL, liste ya da {model_file|mesh} sözlüğü olabilir."""
    if isinstance(out, list):
        out = out[0] if out else None
    if isinstance(out, dict):
        out = out.get("model_file") or out.get("mesh")
    return out if isinstance(out, str) and out else None


def _hunyuan(inp: dict, params: dict, key: str, tick) -> tuple[bytes, str]:
    tex = bool(params.get("texture", True))
    inp |= {"generate_type": "Normal" if tex else "Geometry",
            "enable_pbr": tex and params.get("detail") == "high",
            "face_count": {"low": 100_000, "medium": 500_000, "high": 1_000_000}[params.get("detail", "medium")]}
    url = _url_of(run(f"/models/{HUNYUAN_MODEL}/predictions", {"input": inp}, key, tick).get("output"))
    if not url:
        raise CloudError(f"{NAME}: Hunyuan3D çıktısı yok")
    return _get(url, key), "glb"


def image_to_3d(image: Path, params: dict, key: str, tick=None, *, variant: str = "") -> tuple[bytes, str]:
    seed = int(params.get("seed") or 0)
    detail = params.get("detail", "medium")
    if variant == "hunyuan3d":
        return _hunyuan({"image": small_data_uri(image)}, params, key, tick)
    if variant == "trellis2":
        inp = {"image": small_data_uri(image), "generate_model": True, "generate_video": False,
               "pipeline_type": {"low": "512", "medium": "1024_cascade", "high": "1536_cascade"}[detail],
               "texture_size": 2048 if detail == "low" else 4096,
               "seed": seed, "randomize_seed": seed == 0}
        version = TRELLIS2_VERSION
    else:
        inp = {"images": [small_data_uri(image)], "generate_model": True,
               "generate_color": bool(params.get("texture", True)),
               "texture_size": {"low": 512, "medium": 1024, "high": 2048}[detail],
               "seed": seed, "randomize_seed": seed == 0}
        version = TRELLIS_VERSION
    pred = run("/predictions", {"version": version, "input": inp}, key, tick)
    url = _url_of(pred.get("output"))
    if not url:
        raise CloudError(f"{NAME}: model_file yok (generate_model kapalı olabilir)")
    return _get(url, key), "glb"


def text_to_3d(prompt: str, params: dict, key: str, tick=None, *, variant: str = "") -> tuple[bytes, str]:
    if variant != "hunyuan3d":
        raise CloudError(f"{NAME}: metin→3D modeli tanımlı değil (görsel→3D kullanın)")
    return _hunyuan({"prompt": prompt[:1024]}, params, key, tick)


def text_to_image(prompt: str, params: dict, key: str, *, seed: int = 42, tick=None, variant: str = "") -> bytes:
    fast = params.get("detail") == "low"
    model = "black-forest-labs/flux-schnell" if fast else "black-forest-labs/flux-1.1-pro"
    pred = run(f"/models/{model}/predictions",
               {"input": {"prompt": prompt, "aspect_ratio": "1:1", "output_format": "png", "seed": int(seed)}},
               key, tick, timeout=300)
    out = pred.get("output")
    url = out[0] if isinstance(out, list) and out else out
    if not isinstance(url, str) or not url:
        raise CloudError(f"{NAME}: görsel dönmedi")
    return _get(url, key)
