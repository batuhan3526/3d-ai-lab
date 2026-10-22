import pytest
from common.engines.params import (
    QUALITY_PRESETS,
    GenParams,
    resolve_params,
)


def test_balanced_preset_defaults():
    p = resolve_params("balanced", None)
    assert isinstance(p, GenParams)
    assert p.texture_size == 1024
    assert p.sparse_steps == 25
    assert p.slat_steps == 25
    assert p.simplify == 0.95


def test_fast_and_quality_presets_differ():
    fast = resolve_params("fast", None)
    quality = resolve_params("quality", None)
    assert fast.texture_size == 512
    assert quality.texture_size == 2048
    assert fast.sparse_steps < quality.sparse_steps


def test_advanced_overrides_preset():
    p = resolve_params("balanced", {"texture_size": 256, "sparse_steps": 8, "seed": 7})
    assert p.texture_size == 256
    assert p.sparse_steps == 8
    assert p.seed == 7
    assert p.slat_steps == 25


def test_unknown_preset_raises():
    with pytest.raises(ValueError):
        resolve_params("ultra", None)


def test_invalid_texture_size_raises():
    with pytest.raises(ValueError):
        resolve_params("balanced", {"texture_size": 999})


def test_invalid_simplify_raises():
    with pytest.raises(ValueError):
        resolve_params("balanced", {"simplify": 1.5})


def test_all_presets_present():
    assert set(QUALITY_PRESETS) == {"fast", "balanced", "quality"}


def test_empty_advanced_equals_none():
    assert resolve_params("balanced", {}) == resolve_params("balanced", None)


def test_seed_zero_is_preserved():
    assert resolve_params("balanced", {"seed": 0}).seed == 0
