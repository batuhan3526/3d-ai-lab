"""fal.ai kuyruk API'si (docs: fal.ai/docs/model-endpoints/queue). `Authorization: Key ...`.
Gönderim yanıtındaki status_url / response_url AYNEN kullanılır (alt-yollu model
kimliklerinde SDK bunları alt-yolsuz kurar). Başarısız istek de COMPLETED döner →
`error` alanına bakılır. Yerel görseller fal CDN'e yüklenir (data URI yalnız küçük
dosyalar için önerilir)."""
from __future__ import annotations

from pathlib import Path

from cloud_worker.http import CloudError, client, download, json_of, poll

QUEUE = "https://queue.fal.run"
UPLOAD_INIT = "https://rest.fal.ai/storage/upload/initiate?storage_type=gcs"
NAME = "fal.ai"
M_HUNYUAN_TEXT = "fal-ai/hunyuan-3d/v3.1/rapid/text-to-3d"
M_HUNYUAN_IMAGE = "fal-ai/hunyuan-3d/v3.1/pro/image-to-3d"
M_TRELLIS = "fal-ai/trellis-2"
M_FLUX = "fal-ai/flux-2-pro"


def _headers(key: str) -> dict:
    return {"Authorization": f"Key {key}"}


def upload(image: Path, key: str) -> str:
    mime = "image/jpeg" if image.suffix.lower() in (".jpg", ".jpeg") else "image/png"
    with client(_headers(key)) as c:
        init = json_of(c.post(UPLOAD_INIT, json={"file_name": image.name, "content_type": mime}), NAME)
    if not init.get("upload_url") or not init.get("file_url"):
        raise CloudError(f"{NAME}: dosya yükleme başlatılamadı")
    with client() as c:  # imzalı URL: yetki başlığı YOK
        r = c.put(init["upload_url"], content=image.read_bytes(), headers={"Content-Type": mime})
        if not r.is_success:
            raise CloudError(f"{NAME}: dosya yüklenemedi (HTTP {r.status_code})")
    return init["file_url"]


def run(model: str, body: dict, key: str, tick=None, timeout: float = 900) -> dict:
    with client(_headers(key)) as c:
        sub = json_of(c.post(f"{QUEUE}/{model}", json=body), NAME)
        status_url, response_url = sub.get("status_url"), sub.get("response_url")
        if not status_url or not response_url:
            raise CloudError(f"{NAME}: kuyruk yanıtı eksik")

        def failed(d: dict) -> str | None:
            if d.get("error"):
                return f"{d.get('error_type', '')} {d.get('error')}".strip()
            if d.get("status") not in ("IN_QUEUE", "IN_PROGRESS", "COMPLETED"):
                return f"durum={d.get('status')}"
            return None

        def on_tick(d: dict) -> None:
            if tick:
                tick(50.0 if d.get("status") == "IN_PROGRESS" else 10.0)

        poll(lambda: json_of(c.get(status_url), NAME), lambda d: d.get("status") == "COMPLETED",
             failed, provider=NAME, interval=3.0, timeout=timeout, on_tick=on_tick)
        result = json_of(c.get(response_url), NAME)
    if isinstance(result, dict) and result.get("error"):
        raise CloudError(f"{NAME}: {result.get('error')}")
    return result


def _glb_url(res: dict) -> str:
    for path in (("model_glb", "url"), ("model_urls", "glb", "url"), ("model_mesh", "url")):
        cur = res
        for k in path:
            cur = cur.get(k) if isinstance(cur, dict) else None
        if isinstance(cur, str) and cur:
            # Rapid modellerde model_glb OBJ içerebilir (doküman notu) → content_type kontrolü.
            ct = (res.get(path[0]) or {}).get("content_type", "") if path[0] == "model_glb" else ""
            if "obj" in str(ct):
                continue
            return cur
    raise CloudError(f"{NAME}: yanıtta GLB yok")


def text_to_3d(prompt: str, params: dict, key: str, tick=None, *, variant: str = "") -> tuple[bytes, str]:
    if variant != "hunyuan3d":
        raise CloudError(f"{NAME}: {variant} metin→3D desteklemiyor")
    res = run(M_HUNYUAN_TEXT, {"prompt": prompt[:200],
                               "enable_pbr": bool(params.get("texture", True)) and params.get("detail") == "high"},
              key, tick)
    return download(_glb_url(res), NAME), "glb"


def image_to_3d(image: Path, params: dict, key: str, tick=None, *, variant: str = "") -> tuple[bytes, str]:
    url = upload(image, key)
    if variant == "hunyuan3d":
        body = {"input_image_url": url,
                "generate_type": "Normal" if params.get("texture", True) else "Geometry",
                "enable_pbr": bool(params.get("texture", True)) and params.get("detail") == "high"}
        res = run(M_HUNYUAN_IMAGE, body, key, tick)
    elif variant == "trellis":
        body = {"image_url": url, "resolution": {"low": 512, "medium": 1024, "high": 1536}[params.get("detail", "medium")],
                "texture_size": 1024 if params.get("detail") == "low" else 2048}
        if params.get("seed"):
            body["seed"] = int(params["seed"])
        res = run(M_TRELLIS, body, key, tick)
    else:
        raise CloudError(f"{NAME}: bilinmeyen 3D modeli {variant}")
    return download(_glb_url(res), NAME), "glb"


def text_to_image(prompt: str, params: dict, key: str, *, seed: int = 42, tick=None, variant: str = "") -> bytes:
    res = run(M_FLUX, {"prompt": prompt, "image_size": "square_hd", "seed": int(seed),
                       "output_format": "png"}, key, tick, timeout=300)
    imgs = res.get("images") or []
    if not imgs or not imgs[0].get("url"):
        raise CloudError(f"{NAME}: görsel dönmedi")
    return download(imgs[0]["url"], NAME)
