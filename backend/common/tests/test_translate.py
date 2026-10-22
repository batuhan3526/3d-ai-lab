def test_returns_string_and_nonempty():
    from common.translate import translate_tr_to_en
    out = translate_tr_to_en("kırmızı çiçekli bluz")
    assert isinstance(out, str) and out.strip()


def test_empty_input_returns_empty():
    from common.translate import translate_tr_to_en
    assert translate_tr_to_en("") == ""
