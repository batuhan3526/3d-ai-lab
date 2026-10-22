"""Bulut sağlayıcıları için ortak HTTP yardımcıları (httpx, senkron).

- Hata mesajlarına API anahtarı SIZMAZ (`CloudError` metni anahtarları maskeler).
- Uzun süren işler için `poll`: tamamlanana / hata verene / zaman aşımına kadar sorgular.
- Testler `set_transport` ile sahte bir httpx transport'u enjekte eder (ağ yok).
"""
from __future__ import annotations

import base64
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx

DEFAULT_TIMEOUT = httpx.Timeout(120.0, connect=15.0)
_transport: httpx.BaseTransport | None = None
_secrets: set[str] = set()


class CloudError(RuntimeError):
    """Kullanıcıya gösterilebilir bulut hatası (anahtarsız, Türkçe özet)."""


def set_transport(t: httpx.BaseTransport | None) -> None:
    """Test kancası: tüm istemciler bu transport'u kullanır (None = gerçek ağ)."""
    global _transport
    _transport = t


def register_secret(value: str) -> str:
    """Anahtarı maskeleme listesine ekle ve aynen döndür."""
    if value:
        _secrets.add(value)
    return value


def redact(text: str) -> str:
    for s in _secrets:
        if s and s in text:
            text = text.replace(s, "***")
    return text


def client(headers: dict[str, str] | None = None, timeout: httpx.Timeout | float = DEFAULT_TIMEOUT) -> httpx.Client:
    return httpx.Client(headers=headers or {}, timeout=timeout, transport=_transport,
                        follow_redirects=True)


def check(resp: httpx.Response, provider: str) -> httpx.Response:
    """2xx değilse CloudError (sağlayıcı mesajının kısa, maskelenmiş özeti)."""
    if resp.is_success:
        return resp
    body = resp.text[:400]
    hint = ""
    if resp.status_code in (401, 403):
        hint = " — API anahtarı geçersiz ya da yetkisiz"
    elif resp.status_code == 402:
        hint = " — hesapta kredi/bakiye yok"
    elif resp.status_code == 429:
        hint = " — istek sınırı aşıldı, biraz sonra tekrar deneyin"
    raise CloudError(redact(f"{provider} HTTP {resp.status_code}{hint}: {body}"))


def json_of(resp: httpx.Response, provider: str) -> Any:
    check(resp, provider)
    try:
        return resp.json()
    except ValueError:
        raise CloudError(f"{provider}: yanıt JSON değil") from None


def poll(fetch: Callable[[], dict], done: Callable[[dict], bool], failed: Callable[[dict], str | None],
         *, provider: str, interval: float = 3.0, timeout: float = 900.0,
         on_tick: Callable[[dict], None] | None = None) -> dict:
    """fetch() sonucu done ise döndür; failed bir mesaj verirse CloudError; süre dolarsa hata."""
    t0 = time.monotonic()
    while True:
        data = fetch()
        msg = failed(data)
        if msg:
            raise CloudError(redact(f"{provider} işi başarısız: {msg}"))
        if done(data):
            return data
        if on_tick:
            on_tick(data)
        if time.monotonic() - t0 > timeout:
            raise CloudError(f"{provider} işi {int(timeout)} sn içinde bitmedi")
        time.sleep(interval)


def download(url: str, provider: str, headers: dict[str, str] | None = None) -> bytes:
    if url.startswith("data:"):
        return base64.b64decode(url.split(",", 1)[1])
    with client(headers) as c:
        return check(c.get(url), provider).content


def data_uri(path: Path) -> str:
    """Görseli data URI'ye çevir (URL kabul eden sağlayıcılar için)."""
    ext = path.suffix.lower().lstrip(".") or "png"
    mime = "image/jpeg" if ext in ("jpg", "jpeg") else f"image/{ext}"
    return f"data:{mime};base64," + base64.b64encode(path.read_bytes()).decode()
