from text_to_3d.engines.prompt_template import GARMENT_EN, build_object_prompt


def test_garment_map_has_all_types():
    assert set(GARMENT_EN) == {"model", "tshirt", "shirt", "pants", "skirt", "hat", "boots"}


def test_build_object_prompt_single_object_constraints():
    out = build_object_prompt("orange fox-themed boot with diamonds", "boots")
    assert out.startswith("a single boot")
    assert "orange fox-themed boot with diamonds" in out
    assert "isolated" in out


def test_build_object_prompt_has_no_negations():
    # CLIP olumsuzlamayı anlamaz; "no person" tam insan figürü üretiyordu.
    out = build_object_prompt("plain white t-shirt", "tshirt")
    for word in ("person", "mannequin", "animal", "character"):
        assert word not in out


def test_build_object_prompt_unknown_garment_falls_back():
    out = build_object_prompt("red top", "tshirt")
    assert "a single t-shirt" in out
