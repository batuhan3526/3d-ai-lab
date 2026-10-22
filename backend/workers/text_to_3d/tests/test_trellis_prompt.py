from text_to_3d.engines.trellis_text import build_full_prompt


def test_build_full_prompt_appends_garment_and_object_hints():
    out = build_full_prompt("an orange boot", "boots")
    assert "an orange boot" in out
    assert "boots" in out
    assert "3d model" in out


def test_build_full_prompt_still_available():
    out = build_full_prompt("x", "boots")
    assert "boots" in out
