"""FLUX motif worker. `motif.generate`'i flux-gpuN queue'sunda dinler.

Prompt'tan 2D motif üretir (FLUX.1-dev + BiRefNet matte) ve DÜZENLENEN projenin
`decals/<uuid>.png` dosyasına şeffaf PNG yazar. YENİ proje OLUŞTURMAZ — motif,
mevcut tasarımın bir decal asset'idir (frontend mevcut DecalMesh ile yerleştirir).
decal_path job sonucunda döner; gateway token'sız serve eder.
"""
from __future__ import annotations

import os
import uuid
from pathlib import Path

os.environ.setdefault("CUDA_VISIBLE_DEVICES", os.getenv("GPU_ID", "0"))

from common.celery_app import celery_app  # noqa: E402
from common.config import get_settings  # noqa: E402
# WAL+busy_timeout paylaşılan yardımcı (eski ham sqlite3 kopyasının yerine).
from common.db_write import set_mesh_path as _set_mesh_path  # noqa: E402
from common.jobs import JobStore  # noqa: E402
from common.safety import SafetyBlocked, enforce  # noqa: E402

_engine = None


def _make_motif(out_path, *, text: str, style: dict | None, seed: int = 42) -> None:
    """Motif PNG üret: style verilirse stil görselinden kırp(+AI), yoksa metinden FLUX.
    'pluggable' motif kaynağı — decal ve bake aynı fonksiyonu kullanır."""
    if style:
        img = Path(get_settings().uploads_dir) / style["image_name"]
        if not img.exists():
            raise RuntimeError(f"stil görseli yok: {img}")
        _get().motif_from_style(str(img), style["crop"], str(out_path),
                                ai=bool(style.get("ai")), prompt=text or "", seed=seed)
    else:
        if not text:
            raise RuntimeError("prompt veya stil görseli gerekli")
        _get().generate(text, str(out_path), seed=seed)


def _translate(text: str, enhance: bool) -> str:
    text = (text or "").strip()
    if enhance and text:
        try:
            from common.translate import translate_tr_to_en
            tr = (translate_tr_to_en(text) or "").strip()
            if tr and tr != text:
                print(f"[i18n] prompt TR->EN: {text!r} -> {tr!r}", flush=True)
                text = tr
        except Exception as e:  # noqa: BLE001
            print(f"[i18n] UYARI: çeviri hatası: {e}", flush=True)
    return text


def _get():
    global _engine
    if _engine is None:
        from flux_motif_worker.engine import FluxMotifEngine
        _engine = FluxMotifEngine()
    return _engine


@celery_app.task(name="motif.generate", bind=True)
def generate_motif(self, job_id: str, project_id: str, prompt: str = "",
                   prompt_enhance: bool = True, style: dict | None = None,
                   seed: int = 42) -> dict:
    store = JobStore()
    settings = get_settings()
    try:
        store.set_state(job_id, "STARTED")
        text = _translate(prompt, prompt_enhance)
        store.set_progress(job_id, "generate", 30)
        rel = f"decals/{uuid.uuid4().hex}.png"
        out = Path(settings.projects_dir) / "default" / project_id / rel
        _make_motif(out, text=text, style=style, seed=seed)
        # Opsiyonel NSFW taraması (SAFETY_FILTER=block ise burada fırlatır).
        enforce(out, context="motif")
        store.set_progress(job_id, "matte", 95)
        store.succeed(job_id, {"project_id": project_id, "decal_path": rel})
        return {"project_id": project_id, "decal_path": rel}
    except SafetyBlocked:
        store.fail(job_id, "safety")
        raise
    except Exception as exc:  # noqa: BLE001
        store.fail(job_id, str(exc))
        raise


@celery_app.task(name="motif.bake", bind=True)
def bake_motif(self, job_id: str, project_id: str, source_project_id: str,
               prompt: str, center: list, normal: list, scale: float,
               prompt_enhance: bool = True, style: dict | None = None,
               channels: dict | None = None) -> dict:
    """İşaretli bölgeye motif DOKU olarak: FLUX motif üret → mesh'in UV
    texture'una 3B projeksiyonla pişir → YENİ projenin mesh.glb'si (decal değil,
    dokuya gömülü, dışa aktarımda kalıcı). Poz frontend'in decal poz hesabıyla aynı.
    channels (BATCH-F, opsiyonel): {roughness?, metallic?} UV-uzayı dataURL'leri →
    glTF metallicRoughnessTexture (R=1, G=roughness, B=metallic). Yoksa yalnız albedo."""
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
            raise RuntimeError(f"Kaynak mesh yok: {src}")
        store.set_progress(job_id, "generate", 30)
        motif_png = base / project_id / "decals" / "motif_src.png"
        _make_motif(motif_png, text=text, style=style)
        store.set_progress(job_id, "bake", 70)
        out = base / project_id / "mesh.glb"
        out.parent.mkdir(parents=True, exist_ok=True)
        from flux_motif_worker.bake import bake_motif_into_texture
        info = bake_motif_into_texture(str(src), str(motif_png), str(out),
                                       center=center, normal=normal, scale=float(scale),
                                       channels=channels)
        print(f"[bake] {info}", flush=True)
        store.set_progress(job_id, "pack", 95)
        _set_mesh_path(settings.database_url, project_id, str(out))
        store.succeed(job_id, {"project_id": project_id})
        return {"project_id": project_id}
    except Exception as exc:  # noqa: BLE001
        store.fail(job_id, str(exc))
        raise


def _hex_rgb(hex_color: str) -> tuple:
    h = (hex_color or "#ffffff").lstrip("#")
    if len(h) != 6:
        return (255, 255, 255)
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


@celery_app.task(name="tile.bake", bind=True)
def tile_bake(self, job_id: str, project_id: str, source_project_id: str,
              motif_rel: str, repeat: int = 3, bg_color: str = "#ffffff") -> dict:
    """Motifi N×N döşeyip kaynak mesh'in UV texture'ına tam-UV uygula → YENİ proje
    mesh.glb (dışa aktarılabilir desen). Projeksiyon yok; FLUX modeli yüklenmez (saf
    PIL+trimesh, hızlı)."""
    store = JobStore()
    settings = get_settings()
    try:
        store.set_state(job_id, "STARTED")
        base = Path(settings.projects_dir) / "default"
        src = base / source_project_id / "mesh_view.glb"
        if not src.exists():
            src = base / source_project_id / "mesh.glb"
        if not src.exists():
            raise RuntimeError(f"Kaynak mesh yok: {src}")
        motif = base / source_project_id / motif_rel
        if not motif.exists():
            raise RuntimeError(f"Motif yok: {motif}")
        store.set_progress(job_id, "tile", 40)
        out = base / project_id / "mesh.glb"
        out.parent.mkdir(parents=True, exist_ok=True)
        from flux_motif_worker.tile import bake_tiled_texture
        info = bake_tiled_texture(str(src), str(motif), str(out),
                                  repeat=int(repeat), bg_color=_hex_rgb(bg_color))
        print(f"[tile] {info}", flush=True)
        store.set_progress(job_id, "pack", 95)
        _set_mesh_path(settings.database_url, project_id, str(out))
        store.succeed(job_id, {"project_id": project_id})
        return {"project_id": project_id}
    except Exception as exc:  # noqa: BLE001
        store.fail(job_id, str(exc))
        raise


@celery_app.task(name="texture.upscale", bind=True)
def upscale_texture(self, job_id: str, project_id: str, scale: int = 4) -> dict:
    """Projenin mesh dokusunu (baseColorTexture) Real-ESRGAN ile netleştir →
    YENİ VARYANT GLB'si (`variations/upscale_<uuid>.glb`). Kaynak mesh'e/DB'ye
    DOKUNMAZ (drape ile aynı güvenli varyant deseni); sonuç `decal_path` anahtarıyla
    döner → mevcut /variations reconcile onu result_path'e yazar.

    spandrel yoksa ya da ESRGAN ağırlığı diskte değilse job FAILURE('esrgan-missing')
    (raise etmez) → kullanıcı 'modeli indir' adımına yönlendirilir."""
    store = JobStore()
    settings = get_settings()
    try:
        store.set_state(job_id, "STARTED")
        base = Path(settings.projects_dir) / "default"
        src = base / project_id / "mesh_view.glb"
        if not src.exists():
            src = base / project_id / "mesh.glb"
        if not src.exists():
            raise RuntimeError(f"Kaynak mesh yok: {src}")

        store.set_progress(job_id, "load", 20)
        import numpy as np
        import trimesh
        # force="mesh" sahnedeki TÜM geometrileri kaynaklar; dokusuz bir parça
        # (ör. sızmış zemin düzlemi) birleşimde görseli düşürebilir. Sahneyi yükle,
        # baseColorTexture'ı OLAN en büyük geometriyi seç (canlı vaka 2026-07-06:
        # 4 dokusuz Plane yüzünden yanlış "baseColorTexture yok" hatası).
        loaded = trimesh.load(str(src), force="scene")
        geoms = list(loaded.geometry.values()) if hasattr(loaded, "geometry") else [loaded]
        textured = [g for g in geoms
                    if getattr(getattr(g.visual, "material", None), "baseColorTexture", None) is not None]
        if not textured:
            raise RuntimeError(
                "mesh'te baseColorTexture yok — doku netleştirilemez "
                f"(geometri yüz sayıları: {[len(g.faces) for g in geoms]})")
        m = max(textured, key=lambda g: len(g.faces))
        mat = m.visual.material
        tex = mat.baseColorTexture
        uv = getattr(m.visual, "uv", None)

        store.set_progress(job_id, "upscale", 55)
        from flux_motif_worker.engine import EsrganMissing
        try:
            up = _get().upscale_image(tex, scale=int(scale))
        except EsrganMissing:
            store.fail(job_id, "esrgan-missing")
            return {"error": "esrgan-missing"}

        store.set_progress(job_id, "pack", 90)
        rel = f"variations/upscale_{uuid.uuid4().hex}.glb"
        out = base / project_id / rel
        out.parent.mkdir(parents=True, exist_ok=True)
        new_mat = trimesh.visual.material.PBRMaterial(baseColorTexture=up)
        if uv is not None:
            m.visual = trimesh.visual.TextureVisuals(
                uv=np.asarray(uv, dtype=np.float64), material=new_mat)
        else:
            m.visual.material = new_mat
        m.export(str(out))

        # decal_path → /variations reconcile; upscale_path semantik netlik için.
        result = {"project_id": project_id, "upscale_path": rel, "decal_path": rel}
        store.succeed(job_id, result)
        return result
    except Exception as exc:  # noqa: BLE001
        store.fail(job_id, str(exc))
        raise


@celery_app.task(name="image.matte", bind=True)
def matte_image(self, job_id: str, image_path: str, out_path: str) -> dict:
    """Foto ön-kırpma: yüklenen görselin arka planını BiRefNet ile kaldır →
    şeffaf RGBA PNG out_path'e yaz. FLUX yüklenmez (yalnız BiRefNet resident kalır).
    Sonuç job'ında out_path döner; gateway token'sız serve eder."""
    store = JobStore()
    try:
        store.set_state(job_id, "STARTED")
        store.set_progress(job_id, "matte", 40)
        _get().matte_file(image_path, out_path)
        store.set_progress(job_id, "matte", 95)
        store.succeed(job_id, {"out_path": out_path})
        return {"out_path": out_path}
    except Exception as exc:  # noqa: BLE001
        store.fail(job_id, str(exc))
        raise


@celery_app.task(name="engine.status")
def engine_status() -> dict:
    gpu = os.environ.get("CUDA_VISIBLE_DEVICES", "")
    rep = _engine.mem_report() if _engine else {"loaded": False, "reserved_mb": 0, "allocated_mb": 0}
    return {"gpu": gpu, "loaded": [], "reserved_mb": rep["reserved_mb"],
            "allocated_mb": rep["allocated_mb"]}


@celery_app.task(name="engine.release")
def engine_release(mode: str = "cache") -> dict:
    if _engine is not None and mode == "full":
        _engine.release()
    else:
        try:
            import torch
            torch.cuda.empty_cache()
        except Exception:  # noqa: BLE001
            pass
    return {"mode": mode, "unloaded": []}
