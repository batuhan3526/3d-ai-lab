"""GET /health/deep — auth'lu derin sağlık probu.

`/health` hafif kalır (public, sadece "ayakta mıyım"). Bu ise:
- redis broker'a bağlanabiliyor muyuz (kombu ensure_connection),
- DB'ye YAZILABILIYOR mu (temp tablo write-probe, gerçek veriyi kirletmez),
- celery worker'ları hangi kuyrukları tüketiyor (inspect active_queues) →
  registry'den türetilen BEKLENEN kuyruk listesiyle karşılaştırıp ok/missing haritası.

Herhangi bir alt sistem düşükse status "degraded" ama HTTP 200 döner (503 DEĞİL);
frontend metrik paneli bu cevabı 30 sn'de bir çekip "Workers" satırını çizer.
"""
from __future__ import annotations

from common.engines.registry import default_gpu, engine_family, list_specs
from fastapi import APIRouter
from sqlalchemy import text

from gateway.auth import require_token

router = APIRouter(dependencies=[require_token()])

# inspect/broker probu için üst sınır — cevabı takılmadan tutmak için kısa.
_INSPECT_TIMEOUT = 2.0
_BROKER_TIMEOUT = 2.0


def expected_queues() -> list[str]:
    """Beklenen celery kuyruk isimleri (tek doğruluk kaynağı registry):

    - GPU motorları: yalnız `<family>-gpu{default_gpu()}` beklenir — görünür kümenin
      TAMAMI değil. 2-GPU host'ta worker'lar tek GPU'da koşabilir (ör. GPU0 kullanıcıya
      ayrılmış); orada olmayan kuyruğu "missing" saymak yanlış "degraded" üretir.
    - CPU motorları (spec.gpus == []): kuyruk `<family>-cpu` (ör. clothsim-cpu).
    - Available olmayan motorlar (gated/yayınlanmamış) hiç beklenmez.
    """
    dgpu = default_gpu()
    queues: set[str] = set()
    for s in list_specs():
        if not s.get("available", True):
            continue
        fam = engine_family(s["id"])
        if s.get("gpus") == []:
            queues.add(f"{fam}-cpu")
        else:
            queues.add(f"{fam}-gpu{dgpu}")
    return sorted(queues)


def _check_redis() -> bool:
    """Broker (redis) erişilebilir mi — kombu connection ile (yeni bağımlılık yok)."""
    from common.celery_app import celery_app

    conn = None
    try:
        conn = celery_app.connection()
        conn.ensure_connection(max_retries=0, timeout=_BROKER_TIMEOUT)
        return True
    except Exception:  # noqa: BLE001 — down/timeout → False
        return False
    finally:
        if conn is not None:
            try:
                conn.release()
            except Exception:  # noqa: BLE001
                pass


def _check_db() -> bool:
    """DB YAZILABILIRLIK probu: temp tabloya yaz + rollback (kalıcı iz bırakmaz)."""
    from gateway.db import get_sessionmaker

    try:
        sm = get_sessionmaker()
        with sm() as s:
            s.execute(text("CREATE TEMP TABLE IF NOT EXISTS _health_probe (x INTEGER)"))
            s.execute(text("INSERT INTO _health_probe (x) VALUES (1)"))
            s.rollback()
        return True
    except Exception:  # noqa: BLE001
        return False


def _served_queues() -> set[str]:
    """Worker'ların gerçekten tükettiği kuyruk isimleri (inspect active_queues).

    active_queues() cevabı: `{node_name: [{"name": "trellis-gpu1", ...}, ...]}`.
    Hiç worker yoksa None döner → boş küme. Node adları tutarsız olabildiğinden
    (ör. `hi3dgen-hi3dgen-gpu1@host`) kuyruk→worker haritası node adından DEĞİL,
    active_queues'ın bildirdiği kuyruk adlarından kurulur (güvenilir kaynak)."""
    from common.celery_app import celery_app

    try:
        insp = celery_app.control.inspect(timeout=_INSPECT_TIMEOUT)
        replies = insp.active_queues() or {}
    except Exception:  # noqa: BLE001 — broker down / timeout
        return set()
    served: set[str] = set()
    for queues in replies.values():
        for q in queues or []:
            name = q.get("name") if isinstance(q, dict) else None
            if name:
                served.add(name)
    return served


@router.get("/health/deep")
async def health_deep() -> dict:
    redis_ok = _check_redis()
    db_ok = _check_db()
    served = _served_queues() if redis_ok else set()
    expected = expected_queues()
    workers = {q: ("ok" if q in served else "missing") for q in expected}

    all_workers_ok = bool(expected) and all(v == "ok" for v in workers.values())
    status = "ok" if (redis_ok and db_ok and all_workers_ok) else "degraded"
    return {
        "status": status,
        "redis": redis_ok,
        "db": db_ok,
        "workers": workers,
    }
