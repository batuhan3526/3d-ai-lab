"""Bulut API motorları Celery worker'ı — kuyruk `cloud-cpu` (GPU YOK).

Gateway'in yerel motorlarla AYNI görev adlarını sunar; hangi sağlayıcının çalışacağını
`engine_id` (cloud-<sağlayıcı>-<tür>) belirler:
- text_to_3d.generate / image_to_3d.generate → projects/default/<id>/mesh.glb
- motif.generate → projects/default/<id>/decals/<uuid>.png (şeffaf)
- motif.bake → motif üret + flux_motif'in GPU'suz bake'iyle dokuya pişir (yeni proje)
- engine.status / engine.release → panel uyumluluğu (VRAM yok)

Anahtarlar Settings'ten (.env) okunur; yoksa iş açık bir Türkçe hata ile FAILURE olur.
"""
from __future__ import annotations

import io
import uuid
from pathlib import Path

from common.celery_app import celery_app
from common.config import get_settings
from common.db_write import set_mesh_path as _set_mesh_path
from common.engines.registry import get_spec, resolve_engine_params
from common.jobs import JobStore

from cloud_worker import postprocess
from cloud_worker.http import CloudError, register_secret
from cloud_worker.providers import catalog


def _key(engine_id: str) -> str:
    spec = get_spec(engine_id)
    env = spec.requires_key
    val = str(getattr(get_settings(), env.lower(), "") or "").strip() if env else ""
    if env and not val:
        raise CloudError(f"{spec.label} için API anahtarı ayarlı değil ({env}). "
                         ".env dosyasına ekleyip servisleri yeniden başlatın.")
    return register_secret(val)


def _translate(text: str, enhance: bool) -> str:
    text = (text or "").strip()
    if enhance and text:
        try:
            from common.translate import translate_tr_to_en
            text = (translate_tr_to_en(text) or text).strip()
        except Exception as e:  # noqa: BLE001
            print(f"[i18n] UYARI: çeviri hatası: {e}", flush=True)
    return text


def motif_prompt(prompt: str) -> str:
    """FLUX motif kalıbıyla aynı: tek nesne + düz beyaz zemin (matte bunu varsayar)."""
    return (f"{prompt}, single centered subject, isolated on a plain solid white "
            f"background, flat vector illustration, bold clean shapes, crisp edges, "
            f"no drop shadow, no text, no border")


def _progress(store: JobStore, job_id: str, stage: str, lo: int, hi: int):
    """Sağlayıcıdan gelen 0-100 ilerlemeyi [lo, hi] aralığına yansıt."""
    def tick(pct: float | None) -> None:
        if pct is None:
            return
        store.set_progress(job_id, stage, int(lo + (hi - lo) * max(0.0, min(1.0, pct / 100.0))))
    return tick


def _mesh_out(project_id: str) -> Path:
    return Path(get_settings().projects_dir) / "default" / project_id / "mesh.glb"


@celery_app.task(name="text_to_3d.generate", bind=True)
def generate_text_to_3d(self, job_id: str, project_id: str, prompt: str = "",
                        garment_type: str = "tshirt", engine_id: str = "",
                        quality: str = "balanced", advanced: dict | None = None,
                        prompt_enhance: bool = True, precision: str | None = None,
                        device_mode: str | None = None) -> dict:
    store = JobStore()
    try:
        store.set_state(job_id, "STARTED")
        params = resolve_engine_params(engine_id, quality, advanced)
        key = _key(engine_id)
        text = _translate(prompt, prompt_enhance)
        store.set_progress(job_id, "cloud", 10)
        data, fmt = catalog.text_to_3d(engine_id, text, params, key,
                                       _progress(store, job_id, "cloud", 10, 85))
        store.set_progress(job_id, "pack", 90)
        out = postprocess.to_glb(data, _mesh_out(project_id), fmt)
        _set_mesh_path(get_settings().database_url, project_id, str(out))
        store.succeed(job_id, {"project_id": project_id})
        return {"project_id": project_id}
    except Exception as exc:  # noqa: BLE001
        store.fail(job_id, str(exc))
        raise


@celery_app.task(name="image_to_3d.generate", bind=True)
def generate_image_to_3d(self, job_id: str, project_id: str, image_name: str,
                         garment_type: str = "tshirt", engine_id: str = "",
                         quality: str = "balanced", advanced: dict | None = None,
                         precision: str | None = None, device_mode: str | None = None) -> dict:
    store = JobStore()
    try:
        store.set_state(job_id, "STARTED")
        params = resolve_engine_params(engine_id, quality, advanced)
        key = _key(engine_id)
        image = Path(get_settings().uploads_dir) / image_name
        if not image.is_file():
            raise CloudError(f"Yüklenen görsel bulunamadı: {image_name}")
        store.set_progress(job_id, "cloud", 10)
        data, fmt = catalog.image_to_3d(engine_id, image, params, key,
                                        _progress(store, job_id, "cloud", 10, 85))
        store.set_progress(job_id, "pack", 90)
        out = postprocess.to_glb(data, _mesh_out(project_id), fmt)
        _save_ref_image(image, out.parent)
        _set_mesh_path(get_settings().database_url, project_id, str(out))
        store.succeed(job_id, {"project_id": project_id})
        return {"project_id": project_id}
    except Exception as exc:  # noqa: BLE001
        store.fail(job_id, str(exc))
        raise


def _save_ref_image(image: Path, project_dir: Path) -> None:
    """Girdi görseli projeye ref_image.png olarak yaz: UltraTex/Hi3D tasarımın kendi
    görselini buradan alır (yerel Hunyuan worker'ı da aynısını yapar)."""
    try:
        from PIL import Image
        Image.open(image).convert("RGBA").save(project_dir / "ref_image.png")
    except Exception as e:  # noqa: BLE001
        print(f"[cloud] UYARI: ref_image yazılamadı: {e}", flush=True)


def _make_motif(out_path: Path, *, engine_id: str, text: str, style: dict | None,
                seed: int, tick=None) -> Path:
    """Bulut motif: stil görseli (AI'sız) yerelde kırpılır; aksi halde sağlayıcıdan üret."""
    if style and not style.get("ai"):
        from PIL import Image
        img = Image.open(Path(get_settings().uploads_dir) / style["image_name"])
        x0, y0, x1, y1 = style["crop"]
        w, h = img.size
        crop = img.crop((int(x0 * w), int(y0 * h), int(x1 * w), int(y1 * h)))
        buf = io.BytesIO()
        crop.save(buf, "PNG")
        return postprocess.to_rgba_motif(buf.getvalue(), out_path)
    if not text:
        raise CloudError("Bulut motif için prompt gerekli (AI stil aktarımı yalnız yerel FLUX'ta).")
    params = resolve_engine_params(engine_id, "balanced", None)
    data = catalog.text_to_image(engine_id, motif_prompt(text), params, _key(engine_id),
                                 seed=seed, tick=tick)
    return postprocess.to_rgba_motif(data, out_path)


@celery_app.task(name="motif.generate", bind=True)
def generate_motif(self, job_id: str, project_id: str, prompt: str = "",
                   prompt_enhance: bool = True, style: dict | None = None,
                   seed: int = 42, engine_id: str = "") -> dict:
    store = JobStore()
    try:
        store.set_state(job_id, "STARTED")
        text = _translate(prompt, prompt_enhance)
        store.set_progress(job_id, "generate", 30)
        rel = f"decals/{uuid.uuid4().hex}.png"
        out = Path(get_settings().projects_dir) / "default" / project_id / rel
        _make_motif(out, engine_id=engine_id, text=text, style=style, seed=seed,
                    tick=_progress(store, job_id, "generate", 30, 90))
        from common.safety import enforce
        enforce(out, context="motif")
        store.set_progress(job_id, "matte", 95)
        store.succeed(job_id, {"project_id": project_id, "decal_path": rel})
        return {"project_id": project_id, "decal_path": rel}
    except Exception as exc:  # noqa: BLE001
        store.fail(job_id, str(exc))
        raise


@celery_app.task(name="motif.bake", bind=True)
def bake_motif(self, job_id: str, project_id: str, source_project_id: str,
               prompt: str, center: list, normal: list, scale: float,
               prompt_enhance: bool = True, style: dict | None = None,
               channels: dict | None = None, engine_id: str = "") -> dict:
    store = JobStore()
    settings = get_settings()
    try:
        store.set_state(job_id, "STARTED")
        text = _translate(prompt, prompt_enhance)
        base = Path(settings.projects_dir) / "default"
        src = base / source_project_id / "mesh_view.glb"
        if not src.exists():
            src = base / source_project_id / "mesh.glb"
        if not src.exists():
            raise CloudError(f"Kaynak mesh yok: {source_project_id}")
        store.set_progress(job_id, "generate", 30)
        motif_png = base / project_id / "decals" / "motif_src.png"
        _make_motif(motif_png, engine_id=engine_id, text=text, style=style, seed=42,
                    tick=_progress(store, job_id, "generate", 30, 65))
        store.set_progress(job_id, "bake", 70)
        out = base / project_id / "mesh.glb"
        out.parent.mkdir(parents=True, exist_ok=True)
        from flux_motif_worker.bake import bake_motif_into_texture
        bake_motif_into_texture(str(src), str(motif_png), str(out), center=center,
                                normal=normal, scale=float(scale), channels=channels)
        store.set_progress(job_id, "pack", 95)
        _set_mesh_path(settings.database_url, project_id, str(out))
        store.succeed(job_id, {"project_id": project_id})
        return {"project_id": project_id}
    except Exception as exc:  # noqa: BLE001
        store.fail(job_id, str(exc))
        raise


@celery_app.task(name="engine.status")
def engine_status() -> dict:
    return {"gpu": None, "loaded": [], "reserved_mb": 0, "allocated_mb": 0, "cloud": True}


@celery_app.task(name="engine.release")
def engine_release(mode: str = "cache") -> dict:
    return {"mode": mode, "unloaded": []}
