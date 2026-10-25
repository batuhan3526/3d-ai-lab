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
M_HUNYUAN_RAPID_IMAGE = "fal-ai/hunyuan-3d/v3.1/rapid/image-to-3d"
M_TRELLIS = "fal-ai/trellis-2"
M_TRIPO = "tripo3d/h3.1/{kind}-to-3d"
M_MESHY = "meshy/v7.1/{kind}-to-3d"
M_RODIN_IMAGE = "fal-ai/hyper3d/rodin/v2.5"            # görsel uç yolu alt-yolsuz
M_RODIN_TEXT = "fal-ai/hyper3d/rodin/v2.5/text-to-3d"
M_HITEM3D = "hitem3d/hi3d/v3.0/image-to-3d"
M_SAM3D = "fal-ai/sam-3/3d-objects"
M_PIXAL3D = "fal-ai/pixal3d"
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
    """Modele göre GLB farklı anahtarda: model_glb (Hunyuan, Meshy, TRELLIS.2, Pixal3D, SAM-3),
    model_mesh (Tripo, Rodin, Hitem3D), model_urls.glb, model (Seed3D)."""
    paths = (("model_glb",), ("model_mesh",), ("model_urls", "glb"), ("model_urls", "pbr_model"),
             ("individual_glbs", 0), ("model",))
    for path in paths:
        cur = res
        for k in path:
            if isinstance(k, int):
                cur = cur[k] if isinstance(cur, list) and len(cur) > k else None
            else:
                cur = cur.get(k) if isinstance(cur, dict) else None
        if not isinstance(cur, dict) or not cur.get("url"):
            continue
        # Rapid modellerde model_glb OBJ içerebilir (doküman notu); quad Tripo FBX döner.
        kind = f"{cur.get('content_type', '')} {cur.get('file_name', '')} {cur['url']}".lower()
        if "obj" in kind or "fbx" in kind:
            continue
        return cur["url"]
    raise CloudError(f"{NAME}: yanıtta GLB yok")


def _seed(params: dict, cap: int = 2_000_000_000) -> dict:
    return {"seed": int(params["seed"]) % cap} if params.get("seed") else {}


def _tripo(params: dict) -> dict:
    hi, tex = params.get("detail") == "high", bool(params.get("texture", True))
    b = {"texture": tex, "pbr": tex, "texture_quality": "detailed" if hi else "standard",
         "geometry_quality": "detailed" if hi else "standard"}
    if params.get("seed"):
        b["model_seed"] = b["texture_seed"] = int(params["seed"])
    return b


def _meshy(params: dict) -> dict:
    return {"target_polycount": {"low": 10_000, "medium": 30_000, "high": 100_000}[params.get("detail", "medium")],
            "enable_pbr": bool(params.get("texture", True))}


def _rodin(params: dict) -> dict:
    return {"tier": {"low": "Gen-2.5-Low", "medium": "Gen-2.5-Medium", "high": "Gen-2.5-High"}[params.get("detail", "medium")],
            "material": "PBR" if params.get("texture", True) else "None",
            "geometry_file_format": "glb", **_seed(params, 65_536)}


def text_to_3d(prompt: str, params: dict, key: str, tick=None, *, variant: str = "") -> tuple[bytes, str]:
    tex = bool(params.get("texture", True))
    if variant == "hunyuan3d":
        res = run(M_HUNYUAN_TEXT, {"prompt": prompt[:200], "enable_pbr": tex and params.get("detail") == "high"},
                  key, tick)
    elif variant == "tripo":
        res = run(M_TRIPO.format(kind="text"), {"prompt": prompt[:1024], **_tripo(params)}, key, tick)
    elif variant == "meshy":
        res = run(M_MESHY.format(kind="text"), {"prompt": prompt[:600], "mode": "full" if tex else "preview",
                                                **_meshy(params), **_seed(params)}, key, tick, timeout=1200)
    elif variant == "rodin":
        res = run(M_RODIN_TEXT, {"prompt": prompt, **_rodin(params)}, key, tick, timeout=1200)
    else:
        raise CloudError(f"{NAME}: {variant} metin→3D desteklemiyor")
    return download(_glb_url(res), NAME), "glb"


def image_to_3d(image: Path, params: dict, key: str, tick=None, *, variant: str = "") -> tuple[bytes, str]:
    url = upload(image, key)
    detail, tex = params.get("detail", "medium"), bool(params.get("texture", True))
    if variant == "hunyuan3d":
        body = {"input_image_url": url, "generate_type": "Normal" if tex else "Geometry",
                "enable_pbr": tex and detail == "high"}
        res = run(M_HUNYUAN_IMAGE, body, key, tick)
    elif variant == "hunyuanrapid":
        res = run(M_HUNYUAN_RAPID_IMAGE, {"input_image_url": url, "enable_pbr": tex and detail == "high",
                                          "enable_geometry": not tex}, key, tick)
    elif variant == "trellis":
        body = {"image_url": url, "resolution": {"low": 512, "medium": 1024, "high": 1536}[detail],
                "texture_size": 1024 if detail == "low" else 2048, **_seed(params)}
        res = run(M_TRELLIS, body, key, tick)
    elif variant == "tripo":
        res = run(M_TRIPO.format(kind="image"), {"image_url": url, **_tripo(params)}, key, tick)
    elif variant == "meshy":
        res = run(M_MESHY.format(kind="image"), {"image_url": url, "should_texture": tex, **_meshy(params)},
                  key, tick, timeout=1200)
    elif variant == "rodin":
        res = run(M_RODIN_IMAGE, {"image_urls": [url], **_rodin(params)}, key, tick, timeout=1200)
    elif variant == "hitem3d":
        body = {"image_url": url, "enable_texture": tex, "enable_pbr": tex, "export_format": "glb",
                "face_count": {"low": 300_000, "medium": 1_000_000, "high": 2_000_000}[detail]}
        res = run(M_HITEM3D, body, key, tick, timeout=1800)
    elif variant == "sam3d":
        # prompt = bölütleme metni (varsayılanı "car") → kıyafet/nesne için genel bir ifade.
        res = run(M_SAM3D, {"image_url": url, "prompt": params.get("object_prompt") or "garment",
                            "export_textured_glb": tex, **_seed(params)}, key, tick)
    elif variant == "pixal3d":
        res = run(M_PIXAL3D, {"image_url": url, "resolution": 1536 if detail == "high" else 1024,
                              **_seed(params)}, key, tick)
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
