"""BytePlus ModelArk 3D (docs.byteplus.com/en/docs/ModelArk) — Hyper3D Rodin Gen-2. Bearer
ARK anahtarı; Türkiye desteklenen bölgelerde (ABD/AB değil). Parametreler metin öğesinde
`--ad değer` bayrakları olarak gider; sonuç content.file_url (24 saat geçerli)."""
from __future__ import annotations

from pathlib import Path

from cloud_worker.http import CloudError, client, data_uri, download, json_of, poll

BASE = "https://ark.ap-southeast.bytepluses.com/api/v3"
M_RODIN = "hyper3d-gen2-260112"
NAME = "BytePlus ModelArk"


def _flags(params: dict) -> str:
    tex = bool(params.get("texture", True))
    return (f"--material {'PBR' if tex else 'None'} --mesh_mode Raw --ff glb "
            f"--sl {params.get('detail', 'medium')}")


def _run(key: str, content: list, params: dict, tick) -> tuple[bytes, str]:
    body = {"model": M_RODIN, "content": content}
    if params.get("seed"):
        body["seed"] = int(params["seed"]) % 65_536
    with client({"Authorization": f"Bearer {key}"}) as c:
        task = json_of(c.post(f"{BASE}/contents/generations/tasks", json=body), NAME).get("id")
        if not task:
            raise CloudError(f"{NAME}: görev kimliği dönmedi")

        def failed(d: dict) -> str | None:
            st = d.get("status")
            if st in ("failed", "cancelled", "expired"):
                return (d.get("error") or {}).get("message") or st
            return None if st in ("queued", "running", "succeeded") else f"durum={st}"

        done = poll(lambda: json_of(c.get(f"{BASE}/contents/generations/tasks/{task}"), NAME),
                    lambda d: d.get("status") == "succeeded", failed, provider=NAME, interval=6.0, timeout=1200,
                    on_tick=lambda d: tick and tick(50.0 if d.get("status") == "running" else 10.0))
    url = (done.get("content") or {}).get("file_url")
    if not url:
        raise CloudError(f"{NAME}: model bağlantısı yok")
    return download(url, NAME), "glb"


def text_to_3d(prompt: str, params: dict, key: str, tick=None, *, variant: str = "") -> tuple[bytes, str]:
    # Rodin istemi yalnız İngilizce, ≤400 karakter (worker zaten TR→EN çeviriyor).
    return _run(key, [{"type": "text", "text": f"{prompt[:400]} {_flags(params)}"}], params, tick)


def image_to_3d(image: Path, params: dict, key: str, tick=None, *, variant: str = "") -> tuple[bytes, str]:
    return _run(key, [{"type": "text", "text": _flags(params)},
                      {"type": "image_url", "image_url": {"url": data_uri(image)}}], params, tick)
