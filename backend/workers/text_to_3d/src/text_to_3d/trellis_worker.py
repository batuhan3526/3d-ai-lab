"""TRELLIS text->3D Celery worker (M-A) — kendi trellis venv'inde çalışır.

Gateway `text_to_3d.generate` task'ını seçilen GPU queue'suna enqueue eder; bu
worker (CUDA_VISIBLE_DEVICES ile bir GPU'ya sabitli) consume edip registry'den
motoru çözer, GLB'yi projenin kalıcı dizinine yazar, mesh_path'i sqlite ile günceller.
prompt_enhance açıksa prompt'u çevirir (FAZ B'de tek-nesne kalıbı da eklenecek).
"""
from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("CUDA_VISIBLE_DEVICES", os.getenv("GPU_ID", "0"))
os.environ.setdefault("ATTN_BACKEND", "xformers")
os.environ.setdefault("SPCONV_ALGO", "native")

from common.celery_app import celery_app  # noqa: E402
from common.config import get_settings  # noqa: E402
# WAL+busy_timeout paylaşılan yardımcı (eski ham sqlite3 kopyasının yerine).
from common.db_write import set_mesh_path as _set_mesh_path  # noqa: E402
from common.engines.registry import resolve_engine_params  # noqa: E402
from common.jobs import JobStore  # noqa: E402

_ENGINES: dict[str, object] = {}


def _make_engine(engine_id: str):
    if engine_id == "trellis-text":
        from text_to_3d.engines.trellis_text import TrellisTextEngine
        return TrellisTextEngine()
    if engine_id == "trellis-image":
        from text_to_3d.engines.trellis_image import TrellisImageEngine
        return TrellisImageEngine()
    raise ValueError(f"Bu worker'da yok: {engine_id}")


def _get_engine(engine_id: str):
    """Tek-resident (varsayılan): istenen dışındaki motorları boşalt (OOM koruması).
    MULTI_RESIDENT=1 ise boşaltma yapma → birden çok motor aynı anda yüklü kalır
    (VRAM yettiğince; kullanıcı VRAM butonlarıyla yönetir)."""
    multi = os.environ.get("MULTI_RESIDENT", "").lower() in ("1", "true", "yes")
    if not multi:
        for eid in list(_ENGINES):
            if eid != engine_id:
                try:
                    _ENGINES[eid].unload()
                except Exception:  # noqa: BLE001
                    pass
                del _ENGINES[eid]
    if engine_id not in _ENGINES:
        _ENGINES[engine_id] = _make_engine(engine_id)
    return _ENGINES[engine_id]


def _prepare_prompt(prompt: str, garment_type: str, prompt_enhance: bool) -> str:
    """enhance KAPALI: verbatim (kullanıcı tam kontrol).
    enhance AÇIK: TR→EN çeviri + tek-nesne kalıbı."""
    prompt = (prompt or "").strip()
    if not prompt_enhance:
        return prompt
    from common.translate import translate_tr_to_en

    from text_to_3d.engines.prompt_template import build_object_prompt
    translated = translate_tr_to_en(prompt) or prompt
    return build_object_prompt(translated, garment_type)


@celery_app.task(name="text_to_3d.generate", bind=True)
def generate_text_to_3d(self, job_id: str, project_id: str,
                        prompt: str = "", garment_type: str = "tshirt",
                        engine_id: str = "trellis-text", quality: str = "balanced",
                        advanced: dict | None = None, prompt_enhance: bool = True,
                        prompt_en: str | None = None,
                        precision: str | None = None,
                        device_mode: str | None = None) -> dict:
    store = JobStore()
    settings = get_settings()
    try:
        store.set_state(job_id, "STARTED")
        raw = prompt or prompt_en or ""
        prompt_en_final = _prepare_prompt(raw, garment_type, prompt_enhance)
        params = resolve_engine_params(engine_id, quality, advanced)

        store.set_progress(job_id, "shape", 25)
        engine = _get_engine(engine_id)
        mesh_file = Path(settings.projects_dir) / "default" / project_id / "mesh.glb"
        # generate() tek bloklayıcı çağrı (sampling + texture). İçine ilerleme kancası
        # yok; en azından "paint" aşamasını emit edip frontend'in 3-aşamalı çubuğunu
        # ilerletiyoruz (yoksa ~2dk %25'te takılı görünüp %95'e atlıyor).
        store.set_progress(job_id, "paint", 75)
        engine.generate(prompt_en_final, garment_type, params, mesh_file)

        store.set_progress(job_id, "pack", 95)
        _set_mesh_path(settings.database_url, project_id, str(mesh_file))
        store.succeed(job_id, {"project_id": project_id})
        return {"project_id": project_id}
    except Exception as exc:  # noqa: BLE001
        store.fail(job_id, str(exc))
        raise


@celery_app.task(name="image_to_3d.generate", bind=True)
def generate_image_to_3d(self, job_id: str, project_id: str, image_name: str,
                         garment_type: str = "tshirt", engine_id: str = "trellis-image",
                         quality: str = "balanced", advanced: dict | None = None,
                         precision: str | None = None,
                         device_mode: str | None = None) -> dict:
    store = JobStore()
    settings = get_settings()
    try:
        store.set_state(job_id, "STARTED")
        params = resolve_engine_params(engine_id, quality, advanced)
        store.set_progress(job_id, "shape", 25)
        engine = _get_engine(engine_id)
        # gateway yalnız DOSYA ADI geçer; worker kendi uploads_dir'i
        # ile birleştirir (cross-OS yol uyumu — projects_dir ile aynı desen).
        image_path = str(Path(settings.uploads_dir) / image_name)
        mesh_file = Path(settings.projects_dir) / "default" / project_id / "mesh.glb"
        store.set_progress(job_id, "paint", 75)
        engine.generate(image_path, garment_type, params, mesh_file)
        store.set_progress(job_id, "pack", 95)
        _set_mesh_path(settings.database_url, project_id, str(mesh_file))
        store.succeed(job_id, {"project_id": project_id})
        return {"project_id": project_id}
    except Exception as exc:  # noqa: BLE001
        store.fail(job_id, str(exc))
        raise


@celery_app.task(name="multi_image_to_3d.generate", bind=True)
def generate_multi_image_to_3d(self, job_id: str, project_id: str, image_names: list,
                               garment_type: str = "tshirt", engine_id: str = "trellis-image",
                               quality: str = "balanced", advanced: dict | None = None,
                               precision: str | None = None,
                               device_mode: str | None = None) -> dict:
    store = JobStore()
    settings = get_settings()
    try:
        store.set_state(job_id, "STARTED")
        params = resolve_engine_params(engine_id, quality, advanced)
        store.set_progress(job_id, "shape", 25)
        engine = _get_engine(engine_id)
        image_paths = [str(Path(settings.uploads_dir) / n) for n in image_names]
        mesh_file = Path(settings.projects_dir) / "default" / project_id / "mesh.glb"
        store.set_progress(job_id, "paint", 75)
        engine.generate_multi(image_paths, garment_type, params, mesh_file)
        store.set_progress(job_id, "pack", 95)
        _set_mesh_path(settings.database_url, project_id, str(mesh_file))
        store.succeed(job_id, {"project_id": project_id})
        return {"project_id": project_id}
    except Exception as exc:  # noqa: BLE001
        store.fail(job_id, str(exc))
        raise


@celery_app.task(name="engine.status")
def engine_status() -> dict:
    """Bu worker'ın GPU'su + yüklü motorlar + torch VRAM (idle iken anlık)."""
    gpu = os.environ.get("CUDA_VISIBLE_DEVICES", "")
    loaded = [eid for eid, e in _ENGINES.items() if getattr(e, "is_loaded", lambda: False)()]
    reserved = allocated = 0
    try:
        import torch
        if torch.cuda.is_available():
            reserved = int(torch.cuda.memory_reserved() / 1024 / 1024)
            allocated = int(torch.cuda.memory_allocated() / 1024 / 1024)
    except Exception:  # noqa: BLE001
        pass
    return {"gpu": gpu, "loaded": loaded, "reserved_mb": reserved, "allocated_mb": allocated}


@celery_app.task(name="engine.release")
def engine_release(mode: str = "cache") -> dict:
    """mode=cache: torch cache temizle. mode=model: motorları boşalt + cache temizle."""
    unloaded = []
    if mode == "model":
        for eid, e in list(_ENGINES.items()):
            try:
                e.unload()
                unloaded.append(eid)
            except Exception:  # noqa: BLE001
                pass
        _ENGINES.clear()
    try:
        import torch
        torch.cuda.empty_cache()
    except Exception:  # noqa: BLE001
        pass
    return {"mode": mode, "unloaded": unloaded}
