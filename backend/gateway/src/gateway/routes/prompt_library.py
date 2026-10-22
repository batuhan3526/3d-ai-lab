"""Prompt/seed şablon kütüphanesi — token korumalı (kayıtlı prompt'lar).

Kullanıcı sık kullandığı prompt + motor + parametre + seed kombinasyonlarını
kaydeder ("Şablonlar" çekmecesi) ve yeniden yükler. Kalıcılık, motif/manken
şablonlarıyla aynı desende dosya tabanlıdır: `templates_dir/prompt_library.json`.

Şema (SABİT):
    [{id, title, prompt, engine_id?, params?, seed?, created_at}]

Rotalar:
    GET    /library/prompts        -> list (dosya yoksa boş liste)
    POST   /library/prompts        -> yeni giriş (id + created_at üretilir)
    DELETE /library/prompts/{id}   -> siler (yoksa 404)

Dosya yazımı atomik değildir ama ev/LAN tek-kullanıcı senaryosunda yeterli;
motif kütüphanesi/şablon manifest'i deseniyle tutarlıdır.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

from common.config import get_settings
from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from gateway.auth import require_token

router = APIRouter(prefix="/library/prompts", dependencies=[require_token()])


# --- Şemalar -------------------------------------------------------------------
class PromptTemplateIn(BaseModel):
    """Kaydedilecek şablon (id + created_at sunucuda üretilir)."""

    title: str = Field(min_length=1, max_length=120)
    prompt: str = Field(min_length=1, max_length=4000)
    engine_id: str | None = Field(default=None, max_length=120)
    params: dict | None = None
    seed: int | None = None


class PromptTemplateOut(BaseModel):
    id: str
    title: str
    prompt: str
    engine_id: str | None = None
    params: dict | None = None
    seed: int | None = None
    created_at: str


# --- Kalıcılık yardımcıları ----------------------------------------------------
def _library_file() -> Path:
    return get_settings().templates_dir / "prompt_library.json"


def _load() -> list[dict]:
    """Kütüphaneyi okur; dosya yok/bozuk/liste-değil ise boş liste (kırılmaz)."""
    path = _library_file()
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    return data if isinstance(data, list) else []


def _save(entries: list[dict]) -> None:
    path = _library_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(entries, ensure_ascii=False, indent=2), encoding="utf-8")


# --- Rotalar -------------------------------------------------------------------
@router.get("", response_model=list[PromptTemplateOut])
def list_prompts() -> list[dict]:
    """Kayıtlı tüm prompt/seed şablonları (en yeni önce)."""
    return list(reversed(_load()))


@router.post("", response_model=PromptTemplateOut, status_code=status.HTTP_201_CREATED)
def create_prompt(payload: PromptTemplateIn) -> dict:
    entries = _load()
    entry = {
        "id": uuid.uuid4().hex,
        "title": payload.title,
        "prompt": payload.prompt,
        "engine_id": payload.engine_id,
        "params": payload.params,
        "seed": payload.seed,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    entries.append(entry)
    _save(entries)
    return entry


@router.delete("/{template_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_prompt(template_id: str) -> None:
    entries = _load()
    remaining = [e for e in entries if e.get("id") != template_id]
    if len(remaining) == len(entries):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Şablon bulunamadı")
    _save(remaining)
