import pytest
from gateway.models.schemas import GenerateTextIn
from pydantic import ValidationError


def test_text_advanced_validated_against_engine():
    # trellis param OK
    m = GenerateTextIn(prompt="x", garment_type="tshirt",
                       engine_id="trellis-text", advanced={"sparse_steps": 30})
    assert m.advanced["sparse_steps"] == 30


def test_text_advanced_unknown_param_for_engine_rejected():
    with pytest.raises(ValidationError):
        GenerateTextIn(prompt="x", garment_type="tshirt",
                       engine_id="trellis-text", advanced={"num_inference_steps": 50})


def test_text_advanced_out_of_range_rejected():
    with pytest.raises(ValidationError):
        GenerateTextIn(prompt="x", garment_type="tshirt",
                       engine_id="trellis-text", advanced={"texture_size": 999})
