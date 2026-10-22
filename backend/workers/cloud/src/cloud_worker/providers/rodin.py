"""Hyper3D Rodin Gen-2.5 (docs.hyper3d.ai). Bearer anahtar. Üç adım: multipart /rodin
→ /status (subscription_key) → /download (task uuid). `tier` HER ZAMAN gönderilir."""
from __future__ import annotations

from pathlib import Path

from cloud_worker.http import CloudError, client, download, json_of, poll

BASE = "https://api.hyper3d.com/api/v2"
NAME = "Rodin"
_TIER = {"low": "Gen-2.5-Low", "medium": "Gen-2.5-Medium", "high": "Gen-2.5-High"}


def _headers(key: str) -> dict:
    return {"Authorization": f"Bearer {key}"}


def _run(key: str, fields: dict, image: Path | None, tick) -> tuple[bytes, str]:
    form = {"tier": _TIER.get(fields.pop("detail", "medium"), "Gen-2.5-Medium"),
            "geometry_file_format": "glb", "mesh_mode": "Raw", **fields}
    if image is not None:
        mime = "image/jpeg" if image.suffix.lower() in (".jpg", ".jpeg") else "image/png"
        files = [("images", (image.name, image.read_bytes(), mime))]
    else:
        # Dosyasız multipart: prompt alanı dosya-adsız parça olarak gider.
        files = [("prompt", (None, str(form.pop("prompt")).encode()))]
    with client(_headers(key)) as c:
        sub = json_of(c.post(f"{BASE}/rodin", data=form, files=files), NAME)
        if sub.get("error") or not sub.get("uuid"):
            raise CloudError(f"{NAME}: gönderim reddedildi: {sub.get('error') or sub.get('message')}")
        skey = (sub.get("jobs") or {}).get("subscription_key")

        def fetch() -> dict:
            return json_of(c.post(f"{BASE}/status", json={"subscription_key": skey}), NAME)

        def statuses(d: dict) -> list[str]:
            return [j.get("status") for j in d.get("jobs") or []]

        def failed(d: dict) -> str | None:
            st = statuses(d)
            if "Failed" in st:
                return "bir alt iş Failed"
            if any(s not in ("Waiting", "Generating", "Done") for s in st):
                return f"durum={st}"
            return None

        def done(d: dict) -> bool:
            st = statuses(d)
            return bool(st) and all(s == "Done" for s in st)

        def on_tick(d: dict) -> None:
            st = statuses(d)
            if tick and st:
                tick(100.0 * sum(s == "Done" for s in st) / len(st))

        poll(fetch, done, failed, provider=NAME, interval=6.0, timeout=1200, on_tick=on_tick)
        files_out = json_of(c.post(f"{BASE}/download", json={"task_uuid": sub["uuid"]}), NAME).get("list") or []
    glb = next((f["url"] for f in files_out if str(f.get("name", "")).lower().endswith(".glb")), None)
    if not glb:
        raise CloudError(f"{NAME}: indirme listesinde .glb yok")
    return download(glb, NAME), "glb"


def text_to_3d(prompt: str, params: dict, key: str, tick=None, *, variant: str = "") -> tuple[bytes, str]:
    return _run(key, {"prompt": prompt, "detail": params.get("detail", "medium")}, None, tick)


def image_to_3d(image: Path, params: dict, key: str, tick=None, *, variant: str = "") -> tuple[bytes, str]:
    return _run(key, {"detail": params.get("detail", "medium")}, image, tick)
