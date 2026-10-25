"""Tencent HY 3D Global (Hunyuan 3D Pro, resmi uluslararası API; tencentcloud.com/document/api/1284).
TC3-HMAC-SHA256 imzası (SecretId + SecretKey) → anahtar `.env`'de `SECRET_ID:SECRET_KEY` biçiminde
tek değişken. Submit → JobId, Query → Status WAIT/RUN/FAIL/DONE, ResultFile3Ds[].Url."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from datetime import UTC, datetime
from pathlib import Path

from cloud_worker.http import CloudError, client, download, json_of, poll

HOST = "hunyuan.intl.tencentcloudapi.com"
SERVICE = "hunyuan"
VERSION = "2023-09-01"
REGION = "ap-singapore"
MODEL = "3.1"
NAME = "Tencent HY 3D"


def _split(key: str) -> tuple[str, str]:
    sid, _, skey = key.partition(":")
    if not sid or not skey:
        raise CloudError(f"{NAME}: anahtar 'SECRET_ID:SECRET_KEY' biçiminde olmalı (TENCENTCLOUD_API_KEY)")
    return sid, skey


def sign(secret_id: str, secret_key: str, action: str, payload: str, ts: int) -> dict:
    """TC3-HMAC-SHA256 başlıkları (imzalanan başlıklar: content-type;host)."""
    date = datetime.fromtimestamp(ts, UTC).strftime("%Y-%m-%d")
    canonical = "\n".join(["POST", "/", "", f"content-type:application/json\nhost:{HOST}\n",
                           "content-type;host", hashlib.sha256(payload.encode()).hexdigest()])
    scope = f"{date}/{SERVICE}/tc3_request"
    to_sign = "\n".join(["TC3-HMAC-SHA256", str(ts), scope, hashlib.sha256(canonical.encode()).hexdigest()])

    def h(k: bytes, msg: str) -> bytes:
        return hmac.new(k, msg.encode(), hashlib.sha256).digest()
    signing = h(h(h(("TC3" + secret_key).encode(), date), SERVICE), "tc3_request")
    sig = hmac.new(signing, to_sign.encode(), hashlib.sha256).hexdigest()
    return {"Authorization": f"TC3-HMAC-SHA256 Credential={secret_id}/{scope}, "
                             f"SignedHeaders=content-type;host, Signature={sig}",
            "Content-Type": "application/json", "Host": HOST, "X-TC-Action": action,
            "X-TC-Version": VERSION, "X-TC-Region": REGION, "X-TC-Timestamp": str(ts)}


def call(key: str, action: str, body: dict) -> dict:
    sid, skey = _split(key)
    payload = json.dumps(body, separators=(",", ":"))
    with client(sign(sid, skey, action, payload, int(time.time()))) as c:
        resp = (json_of(c.post(f"https://{HOST}/", content=payload.encode()), NAME) or {}).get("Response") or {}
    err = resp.get("Error")
    if err:
        raise CloudError(f"{NAME} {err.get('Code')}: {err.get('Message', '')}")
    return resp


def _run(key: str, body: dict, tick) -> tuple[bytes, str]:
    job = call(key, "SubmitHunyuanTo3DProJob", body).get("JobId")
    if not job:
        raise CloudError(f"{NAME}: JobId dönmedi")

    def failed(d: dict) -> str | None:
        st = d.get("Status")
        if st == "FAIL":
            return f"{d.get('ErrorCode', '')} {d.get('ErrorMessage', '')}".strip() or "FAIL"
        return None if st in ("WAIT", "RUN", "DONE") else f"durum={st}"

    done = poll(lambda: call(key, "QueryHunyuanTo3DProJob", {"JobId": job}),
                lambda d: d.get("Status") == "DONE", failed, provider=NAME, interval=5.0, timeout=1200,
                on_tick=lambda d: tick and tick(50.0 if d.get("Status") == "RUN" else 10.0))
    files = done.get("ResultFile3Ds") or []
    glb = next((f.get("Url") for f in files if str(f.get("Type", "")).upper() == "GLB" and f.get("Url")), None)
    if not glb:
        raise CloudError(f"{NAME}: sonuçta GLB yok ({[f.get('Type') for f in files]})")
    return download(glb, NAME), "glb"


def _opts(params: dict) -> dict:
    tex = bool(params.get("texture", True))
    return {"Model": MODEL, "GenerateType": "Normal" if tex else "Geometry",
            "EnablePBR": tex and params.get("detail") == "high",
            "FaceCount": {"low": 100_000, "medium": 500_000, "high": 1_000_000}[params.get("detail", "medium")]}


def text_to_3d(prompt: str, params: dict, key: str, tick=None, *, variant: str = "") -> tuple[bytes, str]:
    return _run(key, {"Prompt": prompt[:1024], **_opts(params)}, tick)


def image_to_3d(image: Path, params: dict, key: str, tick=None, *, variant: str = "") -> tuple[bytes, str]:
    if image.stat().st_size > 6_000_000:
        raise CloudError(f"{NAME}: görsel 6 MB'tan büyük")
    return _run(key, {"ImageBase64": base64.b64encode(image.read_bytes()).decode(), **_opts(params)}, tick)
