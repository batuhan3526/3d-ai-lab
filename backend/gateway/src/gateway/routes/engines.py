"""GET /engines (katalog) + /engines/status (canlı VRAM) + /engines/release."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from common.engines.registry import (default_gpu, engine_family, list_specs,
                                     visible_gpu_set)
from fastapi import APIRouter

from gateway.auth import require_token
from gateway.models.schemas import ReleaseIn, ReleaseModeIn

router = APIRouter(prefix="/engines", dependencies=[require_token()])

_STATUS_TIMEOUT = 2.5


def _gpus() -> list[int]:
    """Sorgulanacak GPU index'leri — tek doğruluk kaynağı visible_gpu_set().
    Tek-GPU host'ta [0]'a çöker; status/release-all hayalet GPU'ya fan-out ETMEZ."""
    return sorted(visible_gpu_set())


def _families() -> list[str]:
    """Kayıtlı motorlardan GPU'lu aileleri dinamik türet (yeni model otomatik kapsanır).
    GPU'suz aileler (clothsim, bulut: gpus=[]) VRAM tutmaz ve '-gpuN' kuyruğu dinlemez;
    sorgulansalar hep 'offline' görünüp zaman aşımı beklerlerdi."""
    return sorted({engine_family(s["id"]) for s in list_specs() if s.get("gpus")})


@router.get("")
def list_engines() -> list[dict]:
    # Tek-GPU sözleşmesi: frontend GPU seçiminin varsayılanı backend'den gelir
    # (DEFAULT_GPU); useState(0) gibi frontend sabitleri işleri ölü gpu0
    # kuyruğuna düşürüyordu (2026-07-12 gece bulgusu).
    dg = default_gpu()
    return [{**s, "default_gpu": dg} for s in list_specs()]


def _query(family: str, gpu: int) -> dict:
    from common.celery_app import celery_app
    queue = f"{family}-gpu{gpu}"
    try:
        res = celery_app.send_task("engine.status", queue=queue, expires=10)
        data = res.get(timeout=_STATUS_TIMEOUT)
        return {"online": True, **data, "family": family, "gpu": gpu, "queue": queue}
    except Exception:  # noqa: BLE001
        return {"family": family, "gpu": gpu, "queue": queue, "online": False,
                "loaded": [], "reserved_mb": 0, "allocated_mb": 0}


@router.get("/status")
def engines_status() -> list[dict]:
    # Sıralı sorgu offline worker başına 2.5s bekletir (7 aile × 2 GPU ≈ 35s worst case);
    # paralel sorguda toplam süre tek timeout'a iner.
    pairs = [(f, g) for f in _families() for g in _gpus()]
    with ThreadPoolExecutor(max_workers=len(pairs)) as ex:
        return list(ex.map(lambda p: _query(*p), pairs))


def _release_one(family: str, gpu: int, mode: str) -> dict | None:
    from common.celery_app import celery_app
    queue = f"{family}-gpu{gpu}"
    try:
        res = celery_app.send_task("engine.release", kwargs={"mode": mode},
                                   queue=queue, expires=10)
        out = res.get(timeout=8)
        return {"family": family, "gpu": gpu, "ok": True, **out}
    except Exception:  # noqa: BLE001 — offline/timeout worker'lar atlanir
        return None


@router.post("/release-all")
def engines_release_all(payload: ReleaseModeIn) -> dict:
    pairs = [(f, g) for f in _families() for g in _gpus()]
    with ThreadPoolExecutor(max_workers=len(pairs)) as ex:
        results = [r for r in ex.map(lambda p: _release_one(*p, payload.mode), pairs) if r]
    return {"mode": payload.mode, "released": results}


@router.post("/release")
def engines_release(payload: ReleaseIn) -> dict:
    from common.celery_app import celery_app
    queue = f"{payload.family}-gpu{payload.gpu}"
    try:
        res = celery_app.send_task("engine.release", kwargs={"mode": payload.mode},
                                   queue=queue, expires=10)
        out = res.get(timeout=30)
        return {"ok": True, "family": payload.family, "gpu": payload.gpu, **out}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "family": payload.family, "gpu": payload.gpu, "error": str(exc)}
