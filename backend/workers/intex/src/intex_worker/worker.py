"""InTeX doku-edit worker. `texture_edit.generate`'i intex-gpuN queue'sunda dinler.

Kaynak projenin mesh.glb'sini alır, prompt'la yeniden-dokular, YENİ projenin
mesh.glb'sine yazar (orijinal korunur). Yollar worker'ın PROJECTS_DIR'i ile
çözülür (cross-OS uyumu — gateway sadece project id'leri geçer).
"""
from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("CUDA_VISIBLE_DEVICES", os.getenv("GPU_ID", "0"))

from common.celery_app import celery_app  # noqa: E402
from common.config import get_settings  # noqa: E402
# WAL+busy_timeout paylaşılan yardımcı (eski ham sqlite3 kopyasının yerine).
from common.db_write import set_mesh_path as _set_mesh_path  # noqa: E402
from common.jobs import JobStore  # noqa: E402

_engine = None


def _get():
    global _engine
    if _engine is None:
        from intex_worker.engine import IntexEditEngine
        _engine = IntexEditEngine()
    return _engine


@celery_app.task(name="texture_edit.generate", bind=True)
def generate_texture_edit(self, job_id: str, project_id: str, source_project_id: str,
                          prompt: str, prompt_enhance: bool = False,
                          engine_id: str = "intex-retexture", quality: str = "balanced",
                          advanced: dict | None = None, mask_name: str | None = None) -> dict:
    store = JobStore()
    settings = get_settings()
    try:
        store.set_state(job_id, "STARTED")
        # prompt_enhance açıksa TR→EN çevir (InTeX İngilizce prompt ister)
        text = (prompt or "").strip()
        if prompt_enhance:
            try:
                from common.translate import translate_tr_to_en
                translated = (translate_tr_to_en(text) or "").strip()
                # translate_tr_to_en hata yutar ve girdiyi döndürür — değişmeyen
                # Türkçe prompt SD'ye Türkçe gider, sonuç sessizce bozulur. Logla.
                if translated and translated != text:
                    print(f"[i18n] prompt TR->EN: {text!r} -> {translated!r}", flush=True)
                    text = translated
                else:
                    print(f"[i18n] UYARI: çeviri prompt'u değiştirmedi ({text!r}) — "
                          "TRANSLATE_BACKEND/sentencepiece kontrol et", flush=True)
            except Exception as e:  # noqa: BLE001
                print(f"[i18n] UYARI: çeviri hatası: {e}", flush=True)
        src = Path(settings.projects_dir) / "default" / source_project_id / "mesh.glb"
        if not src.exists():
            raise RuntimeError(f"Kaynak mesh yok: {src}")
        out = Path(settings.projects_dir) / "default" / project_id / "mesh.glb"
        mask_path = None
        if mask_name:
            mp = Path(settings.uploads_dir) / mask_name
            if not mp.exists():
                raise RuntimeError(f"Bölge maskesi yok: {mp}")
            mask_path = str(mp)
            # Zemin/baskı yönlendirmesi engine'de eklenir (kumaş rengini o örnekler).
            # Bölge maskesi viewer'daki mesh'in UV'sinde boyandı. Gateway dev/UV'siz
            # mesh'ler için mesh_view.glb (decimate+unwrap) servis eder — maske
            # hizalaması için bölge modunda AYNI mesh kullanılmalı. Tüm-model
            # retexture tam çözünürlüklü mesh.glb ile çalışmaya devam eder.
            view = src.with_name("mesh_view.glb")
            if view.exists():
                src = view
        store.set_progress(job_id, "paint", 40)
        _get().retexture(str(src), text, out, mask_path=mask_path)
        store.set_progress(job_id, "pack", 95)
        _set_mesh_path(settings.database_url, project_id, str(out))
        store.succeed(job_id, {"project_id": project_id})
        return {"project_id": project_id}
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
    try:
        import torch
        torch.cuda.empty_cache()
    except Exception:  # noqa: BLE001
        pass
    return {"mode": mode, "unloaded": []}
