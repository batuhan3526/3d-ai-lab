import pytest
from common.engines.registry import EngineSpec, get_spec, list_specs


def test_trellis_text_registered():
    spec = get_spec("trellis-text")
    assert isinstance(spec, EngineSpec)
    assert spec.kind == "text"
    assert spec.license == "MIT"
    assert "balanced" in spec.quality_presets


def test_list_specs_returns_serializable_dicts():
    specs = list_specs()
    assert any(s["id"] == "trellis-text" for s in specs)
    one = specs[0]
    assert {"id", "label", "kind", "quality_presets", "vram_estimate_mb", "license"} <= set(one)
    assert "adapter" not in one  # iç detay API'ye sızmamalı


def test_unknown_engine_raises():
    with pytest.raises(KeyError):
        get_spec("does-not-exist")


def test_trellis_image_registered():
    spec = get_spec("trellis-image")
    assert spec.kind == "image"
    assert spec.license == "MIT"


def test_list_specs_includes_both_engines():
    ids = {s["id"] for s in list_specs()}
    assert {"trellis-text", "trellis-image"} <= ids


def test_hunyuan_image_registered_noncommercial():
    spec = get_spec("hunyuan-image")
    assert spec.kind == "image"
    assert "NON-COMMERCIAL" in spec.license.upper() or "NONCOMMERCIAL" in spec.license.upper()


def test_engine_family_helper():
    from common.engines.registry import engine_family
    assert engine_family("trellis-text") == "trellis"
    assert engine_family("trellis-image") == "trellis"
    assert engine_family("hunyuan-image") == "hunyuan"


@pytest.mark.parametrize("eid,family", [("trellis2-image", "trellis2"), ("pixal3d-image", "pixal3d")])
def test_trellis2_family_engines_registered(eid, family):
    """TRELLIS.2 omurgalı motorlar: kendi ailesi/kuyruğu (TRELLIS v1 ile karışmaz), her preset
    şemayla geçerli."""
    from common.engines.registry import engine_family, queue_for, resolve_engine_params
    spec = get_spec(eid)
    assert spec.kind == "image" and "image-to-3d" in spec.capabilities
    assert engine_family(eid) == family
    assert queue_for(eid, 1) == f"{family}-gpu1"
    for preset in spec.quality_presets:
        resolve_engine_params(eid, preset, None)
