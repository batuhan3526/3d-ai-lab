import pytest
from gateway.models.schemas import GenerateTextIn
from pydantic import ValidationError


def test_defaults_backward_compatible():
    m = GenerateTextIn(prompt="kirmizi bluz", garment_type="tshirt")
    assert m.engine_id == "trellis-text"
    assert m.gpu == 1
    assert m.quality == "balanced"
    assert m.prompt_enhance is True
    assert m.advanced is None


def test_invalid_gpu_rejected():
    with pytest.raises(ValidationError):
        GenerateTextIn(prompt="x", garment_type="tshirt", gpu=3)


def test_invalid_quality_rejected():
    with pytest.raises(ValidationError):
        GenerateTextIn(prompt="x", garment_type="tshirt", quality="ultra")


def test_unknown_engine_rejected():
    with pytest.raises(ValidationError):
        GenerateTextIn(prompt="x", garment_type="tshirt", engine_id="nope")


def test_advanced_invalid_value_rejected():
    with pytest.raises(ValidationError):
        GenerateTextIn(prompt="x", garment_type="tshirt",
                       advanced={"texture_size": 999})


def test_advanced_valid_passes():
    m = GenerateTextIn(prompt="x", garment_type="tshirt",
                       advanced={"texture_size": 256, "seed": 5})
    assert m.advanced["texture_size"] == 256


def test_batch_in_clamps_and_requires_source():
    from gateway.models.schemas import BatchIn
    import pytest as _pt
    # count sınırları
    with _pt.raises(Exception):
        BatchIn(kind="motif", project_id="p", count=0, prompt="gül")
    with _pt.raises(Exception):
        BatchIn(kind="motif", project_id="p", count=21, prompt="gül")
    # motif: prompt şart
    with _pt.raises(Exception):
        BatchIn(kind="motif", project_id="p", count=4)
    # style: style şart
    with _pt.raises(Exception):
        BatchIn(kind="style", project_id="p", count=4, prompt="x")
    ok = BatchIn(kind="motif", project_id="p", count=9, prompt="kırmızı gül")
    assert ok.count == 9 and ok.kind == "motif"


def test_version_in_requires_name():
    from gateway.models.schemas import VersionIn
    import pytest as _pt
    with _pt.raises(Exception):
        VersionIn(name="", auto=False, customizations={"color": "#fff", "decals": []})
    ok = VersionIn(name="mavi", auto=True, customizations={"color": "#fff", "decals": []})
    assert ok.auto is True and ok.name == "mavi"
