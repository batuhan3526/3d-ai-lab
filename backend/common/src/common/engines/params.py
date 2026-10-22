"""Üretim parametreleri: kalite presetleri + gelişmiş override + doğrulama.

3.10-uyumlu (worker venv py3.10 ve gateway py3.11 ikisi de import eder).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

VALID_TEXTURE_SIZES = (256, 512, 1024, 2048)
_STEP_MIN, _STEP_MAX = 1, 100
_CFG_MIN, _CFG_MAX = 0.0, 30.0
_SIMPLIFY_MIN, _SIMPLIFY_MAX = 0.0, 0.98


@dataclass(frozen=True)
class GenParams:
    """TRELLIS run() + to_glb() için çözülmüş tam parametre seti."""
    sparse_steps: int
    slat_steps: int
    sparse_cfg: float
    slat_cfg: float
    texture_size: int
    simplify: float
    seed: int | None  # None => worker rastgele üretir
    num_samples: int = 1


QUALITY_PRESETS: dict[str, dict[str, Any]] = {
    "fast": dict(sparse_steps=12, slat_steps=12, sparse_cfg=7.5, slat_cfg=7.5,
                 texture_size=512, simplify=0.95, seed=None),
    "balanced": dict(sparse_steps=25, slat_steps=25, sparse_cfg=7.5, slat_cfg=7.5,
                     texture_size=1024, simplify=0.95, seed=None),
    "quality": dict(sparse_steps=40, slat_steps=40, sparse_cfg=7.5, slat_cfg=7.5,
                    texture_size=2048, simplify=0.90, seed=None),
}

_ALLOWED_ADVANCED = {
    "sparse_steps", "slat_steps", "sparse_cfg", "slat_cfg",
    "texture_size", "simplify", "seed", "num_samples",
}


def _validate(values: dict) -> None:
    if values["texture_size"] not in VALID_TEXTURE_SIZES:
        raise ValueError(f"texture_size {VALID_TEXTURE_SIZES} içinde olmalı")
    for key in ("sparse_steps", "slat_steps"):
        if not (_STEP_MIN <= values[key] <= _STEP_MAX):
            raise ValueError(f"{key} {_STEP_MIN}..{_STEP_MAX} aralığında olmalı")
    for key in ("sparse_cfg", "slat_cfg"):
        if not (_CFG_MIN <= values[key] <= _CFG_MAX):
            raise ValueError(f"{key} {_CFG_MIN}..{_CFG_MAX} aralığında olmalı")
    if not (_SIMPLIFY_MIN <= values["simplify"] <= _SIMPLIFY_MAX):
        raise ValueError(f"simplify {_SIMPLIFY_MIN}..{_SIMPLIFY_MAX} aralığında olmalı")
    if not (1 <= values["num_samples"] <= 4):
        raise ValueError("num_samples 1..4 aralığında olmalı")


def resolve_params(quality: str, advanced: dict | None) -> GenParams:
    """Preset taban + gelişmiş override → doğrulanmış GenParams."""
    if quality not in QUALITY_PRESETS:
        raise ValueError(f"Bilinmeyen kalite: {quality}")
    values = dict(QUALITY_PRESETS[quality])
    values.setdefault("num_samples", 1)
    if advanced is not None:
        unknown = set(advanced) - _ALLOWED_ADVANCED
        if unknown:
            raise ValueError(f"Bilinmeyen gelişmiş alan: {sorted(unknown)}")
        values.update({k: v for k, v in advanced.items() if v is not None})
    _validate(values)
    return GenParams(**values)
