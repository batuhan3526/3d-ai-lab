"""common.safety testleri — 3 mod (off/log/block) + opennsfw2 YOKKEN graceful.

opennsfw2 gerçekte kurulu olmayabilir; testler onu sahte skorlarla monkeypatch'ler
(sys.modules enjeksiyonu) ya da import'unu bozarak "unavailable" yolunu doğrular.
"""
from __future__ import annotations

import sys
import types

import pytest


@pytest.fixture(autouse=True)
def _clear_settings_cache(monkeypatch):
    """Her test taze Settings okusun (SAFETY_FILTER env override'ı geçerli olsun)."""
    monkeypatch.setenv("APP_TOKEN", "test-token")
    from common.config import get_settings
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


class _StubSettings:
    def __init__(self, safety_filter="off", safety_threshold=0.85):
        self.safety_filter = safety_filter
        self.safety_threshold = safety_threshold


def _stub_settings(monkeypatch, **kw):
    """Hermetik: common.safety.get_settings'i stub'la — env/cache'e bağımlılık yok."""
    import common.safety as safety
    monkeypatch.setattr(safety, "get_settings", lambda: _StubSettings(**kw))


def _fake_opennsfw2(monkeypatch, score: float):
    """sys.modules'e sahte opennsfw2 enjekte et (predict_image sabit skor döner)."""
    mod = types.ModuleType("opennsfw2")
    mod.predict_image = lambda path: score  # noqa: ARG005
    monkeypatch.setitem(sys.modules, "opennsfw2", mod)


def _break_opennsfw2(monkeypatch):
    """import opennsfw2 → ImportError (paket yok senaryosu)."""
    monkeypatch.setitem(sys.modules, "opennsfw2", None)


# --- check_image -----------------------------------------------------------

def test_check_image_flagged_above_threshold(monkeypatch):
    _fake_opennsfw2(monkeypatch, 0.97)
    from common.safety import check_image
    flagged, score = check_image("x.png", threshold=0.85)
    assert flagged is True
    assert score == pytest.approx(0.97)


def test_check_image_clean_below_threshold(monkeypatch):
    _fake_opennsfw2(monkeypatch, 0.10)
    from common.safety import check_image
    flagged, score = check_image("x.png", threshold=0.85)
    assert flagged is False
    assert score == pytest.approx(0.10)


def test_check_image_uses_settings_threshold(monkeypatch):
    _stub_settings(monkeypatch, safety_threshold=0.5)
    _fake_opennsfw2(monkeypatch, 0.6)
    from common.safety import check_image
    flagged, score = check_image("x.png")  # eşik verilmedi → settings 0.5
    assert flagged is True
    assert score == pytest.approx(0.6)


def test_check_image_unavailable_graceful(monkeypatch):
    """opennsfw2 YOKKEN (False, -1.0) döner, asla patlamaz."""
    _break_opennsfw2(monkeypatch)
    from common.safety import check_image
    flagged, score = check_image("x.png")
    assert flagged is False
    assert score == -1.0


def test_check_image_predict_error_graceful(monkeypatch):
    """predict_image patlarsa (False, -1.0) — engelleme yok."""
    mod = types.ModuleType("opennsfw2")

    def _boom(path):  # noqa: ARG001
        raise RuntimeError("model load failed")

    mod.predict_image = _boom
    monkeypatch.setitem(sys.modules, "opennsfw2", mod)
    from common.safety import check_image
    assert check_image("x.png") == (False, -1.0)


# --- enforce: 3 mod -------------------------------------------------------

def test_enforce_off_is_noop_zero_overhead(monkeypatch):
    """off modu: check_image ÇAĞRILMAZ (sıfır ek yük), asla fırlatmaz."""
    _stub_settings(monkeypatch, safety_filter="off")

    import common.safety as safety

    def _must_not_call(*a, **k):  # noqa: ARG001
        raise AssertionError("off modunda check_image çağrılmamalı")

    monkeypatch.setattr(safety, "check_image", _must_not_call)
    assert safety.enforce("x.png", context="upload") is None


def test_enforce_log_flagged_does_not_raise(monkeypatch):
    _stub_settings(monkeypatch, safety_filter="log")

    import common.safety as safety
    monkeypatch.setattr(safety, "check_image", lambda p, threshold=None: (True, 0.99))
    # log modu: işaretli olsa da fırlatmaz.
    assert safety.enforce("x.png", context="motif") is None


def test_enforce_block_flagged_raises(monkeypatch):
    _stub_settings(monkeypatch, safety_filter="block")

    import common.safety as safety
    monkeypatch.setattr(safety, "check_image", lambda p, threshold=None: (True, 0.99))
    with pytest.raises(safety.SafetyBlocked):
        safety.enforce("x.png", context="motif")


def test_enforce_block_clean_passes(monkeypatch):
    _stub_settings(monkeypatch, safety_filter="block")

    import common.safety as safety
    monkeypatch.setattr(safety, "check_image", lambda p, threshold=None: (False, 0.05))
    assert safety.enforce("x.png", context="upload") is None


def test_enforce_block_unavailable_does_not_raise(monkeypatch):
    """block modu ama opennsfw2 yok → check_image (False,-1.0); graceful, fırlatmaz."""
    _stub_settings(monkeypatch, safety_filter="block")
    _break_opennsfw2(monkeypatch)

    import common.safety as safety
    assert safety.enforce("x.png", context="motif") is None
