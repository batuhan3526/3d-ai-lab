"""GPU lock — threading stub (Faz 0-1) veya Redis mutex (Faz 2+).

`client` verilmezse threading.Lock tabanlı in-process lock kullanılır
(test izolasyonu ve tek-process senaryolar için). `client` verilirse
Redis SET NX tabanlı cross-process lock devreye girer (spec §4.3).
"""
from __future__ import annotations

import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager

import redis as redis_lib

# ── Threading tabanlı (Faz 0-1) ──────────────────────────────────────────────

class GpuLockTimeout(TimeoutError):
    """GPU lock acquire timed out."""


_locks: dict[int, threading.Lock] = {}
_locks_dict_mutex = threading.Lock()


def _get_lock_for(gpu_id: int) -> threading.Lock:
    """Lazy-init per-GPU lock."""
    with _locks_dict_mutex:
        if gpu_id not in _locks:
            _locks[gpu_id] = threading.Lock()
        return _locks[gpu_id]


# ── Redis tabanlı (Faz 2+) ───────────────────────────────────────────────────

_LOCK_TTL = 600  # saniye — stale lock'u temizler
_POLL_INTERVAL = 0.05  # saniye


def _redis_acquire(
    r: redis_lib.Redis,
    key: str,
    timeout: int,
    blocking_timeout: int,
) -> bool:
    """SET NX tabanlı basit spin-lock. Lua gerektirmez (fakeredis uyumlu)."""
    deadline = time.monotonic() + blocking_timeout
    while True:
        if r.set(key, "1", nx=True, ex=timeout):
            return True
        if time.monotonic() >= deadline:
            return False
        time.sleep(_POLL_INTERVAL)


def _redis_release(r: redis_lib.Redis, key: str) -> None:
    # M2 NOTU: koşulsuz delete. timeout (TTL) bir holder hâlâ çalışırken dolarsa
    # başka worker kilidi alıp bu finally ikincinin kilidini silebilir (GPU çifte
    # kullanım). M1'de kilit kullanılmıyor; gerçek GPU inference'ı (M2) sarmadan
    # önce acquire'da benzersiz token saklayıp release'de yalnız sahipse sil.
    r.delete(key)


# ── Ortak context manager ────────────────────────────────────────────────────

@contextmanager
def gpu_lock(
    gpu_id: int,
    client: redis_lib.Redis | None = None,
    timeout: int | float = 600,
    blocking_timeout: int | float = 300,
) -> Iterator[None]:
    """GPU'yu eşzamanlı tek bir consumer kullansın diye lock.

    Args:
        gpu_id: 0, 1, … — fiziksel GPU index'i.
        client: Redis client (opsiyonel). Verilmezse threading.Lock kullanılır.
        timeout: Kilit süresi / lock TTL (saniye).
        blocking_timeout: Maksimum bekleme süresi (saniye).

    Raises:
        TimeoutError: Kilit `blocking_timeout` içinde alınamazsa.
        GpuLockTimeout: threading yolu için aynı durum (TimeoutError alt sınıfı).
    """
    if client is not None:
        # Redis yolu (cross-process, Faz 2+)
        key = f"gpu:{gpu_id}"
        acquired = _redis_acquire(client, key, int(timeout), blocking_timeout)
        if not acquired:
            raise TimeoutError(f"GPU {gpu_id} meşgul")
        try:
            yield
        finally:
            _redis_release(client, key)
    else:
        # Threading yolu (in-process, Faz 0-1 geriye dönük uyumluluk)
        lock = _get_lock_for(gpu_id)
        acquired = lock.acquire(timeout=timeout)
        if not acquired:
            raise GpuLockTimeout(f"GPU {gpu_id} lock timeout after {timeout}s")
        try:
            yield
        finally:
            lock.release()
