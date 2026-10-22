"""Opsiyonel NSFW/güvenlik filtresi (SAFETY_FILTER=off|log|block).

`opennsfw2` (CPU) LAZY import edilir — `common`'un sabit bağımlılığı DEĞİL.
Paket kurulu değilse "unavailable" loglanır ve HİÇBİR şey engellenmez
(graceful fallback). Varsayılan mod `off`: `enforce` hemen döner, opennsfw2
import edilmez, sıfır ek yük.

Tarama noktaları:
- flux motif worker: üretilen motif PNG'si (block → job FAILURE("safety")).
- gateway: upload edilen foto (block → 422).

Eşik ve mod `common.config.Settings` üzerinden gelir
(`safety_filter`, `safety_threshold`).
"""
from __future__ import annotations

from pathlib import Path

from common.config import get_settings
from common.logging import get_logger

_log = get_logger("safety")


class SafetyBlocked(Exception):
    """`block` modunda işaretli (flagged) içerik için fırlatılır."""


def check_image(path: str | Path, threshold: float | None = None) -> tuple[bool, float]:
    """Görseli NSFW açısından tara.

    Dönüş: `(flagged, score)`. `score` [0,1] NSFW olasılığı; `flagged` = score >= eşik.
    `opennsfw2` kurulu değilse ya da tahmin başarısızsa `(False, -1.0)` döner ve
    uyarı loglar (asla engelleme yapmaz).
    """
    if threshold is None:
        threshold = get_settings().safety_threshold

    try:
        import opennsfw2  # noqa: PLC0415  (lazy — sabit bağımlılık değil)
    except Exception as exc:  # noqa: BLE001
        _log.warning("safety.unavailable", error=str(exc),
                     hint="pip install opennsfw2 (flux_motif requirements.txt)")
        return (False, -1.0)

    try:
        score = float(opennsfw2.predict_image(str(path)))
    except Exception as exc:  # noqa: BLE001
        _log.warning("safety.error", error=str(exc), path=str(path))
        return (False, -1.0)

    return (score >= threshold, score)


def enforce(path: str | Path, *, context: str) -> None:
    """Güvenlik moduna göre `path`'i uygula.

    - `off`  : hemen döner (opennsfw2 import edilmez — sıfır ek yük).
    - `log`  : tarar; işaretliyse loglar, engellemez.
    - `block`: tarar; işaretliyse loglar VE `SafetyBlocked` fırlatır.

    opennsfw2 yoksa (score < 0) hiçbir modda engelleme yapılmaz.
    """
    mode = (get_settings().safety_filter or "off").strip().lower()
    if mode == "off":
        return

    flagged, score = check_image(path)
    if score < 0:
        # opennsfw2 kullanılamıyor — check_image zaten uyardı; engelleme yok.
        return

    if flagged:
        _log.warning("safety.flagged", context=context, score=round(score, 4),
                     mode=mode, path=str(path))
        if mode == "block":
            raise SafetyBlocked(f"safety: {context} işaretlendi (score={score:.3f})")
    else:
        _log.info("safety.pass", context=context, score=round(score, 4), mode=mode)
