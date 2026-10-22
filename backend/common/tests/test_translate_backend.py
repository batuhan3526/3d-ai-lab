import common.translate as t


def test_default_backend_is_argos_dispatch(monkeypatch):
    called = {}
    monkeypatch.setattr(t, "_translate_argos", lambda s: called.setdefault("argos", s) and "EN" or "EN")
    monkeypatch.setattr(t, "_backend_name", lambda: "argos")
    assert t.translate_tr_to_en("merhaba") == "EN"
    assert called["argos"] == "merhaba"


def test_opus_backend_dispatch(monkeypatch):
    called = {}
    monkeypatch.setattr(t, "_translate_opus", lambda s: called.setdefault("opus", s) and "ENO" or "ENO")
    monkeypatch.setattr(t, "_backend_name", lambda: "opus")
    assert t.translate_tr_to_en("merhaba") == "ENO"
    assert called["opus"] == "merhaba"


def test_empty_returns_empty():
    assert t.translate_tr_to_en("") == ""


def test_backend_error_falls_back_to_input(monkeypatch):
    def boom(_s):
        raise RuntimeError("model yok")
    monkeypatch.setattr(t, "_translate_opus", boom)
    monkeypatch.setattr(t, "_backend_name", lambda: "opus")
    assert t.translate_tr_to_en("merhaba dünya") == "merhaba dünya"


def test_english_input_not_sent_to_backend(monkeypatch):
    """İngilizce girdi TR->EN modeline gitmemeli (gider ise bozulur:
    'yellow flower' -> 'windlow flower'). Dil-tespit guard'ı atlamalı."""
    called = {"n": 0}

    def mangle(_s):
        called["n"] += 1
        return "windlow flower"

    monkeypatch.setattr(t, "_translate_opus", mangle)
    monkeypatch.setattr(t, "_backend_name", lambda: "opus")
    assert t.translate_tr_to_en("yellow flower") == "yellow flower"
    assert called["n"] == 0  # backend hiç çağrılmadı


def test_turkish_still_dispatched_despite_guard(monkeypatch):
    """Guard Türkçe'yi engellememeli: özel karakterli ve ASCII Türkçe çevrilir."""
    monkeypatch.setattr(t, "_translate_opus", lambda s: "EN:" + s)
    monkeypatch.setattr(t, "_backend_name", lambda: "opus")
    assert t.translate_tr_to_en("kırmızı çiçek") == "EN:kırmızı çiçek"
    assert t.translate_tr_to_en("mavi bluz") == "EN:mavi bluz"


def test_looks_english_detection():
    assert t._looks_english("yellow flower")
    assert t._looks_english("red rose")
    assert t._looks_english("blue t-shirt")
    assert not t._looks_english("kırmızı çiçek")   # Türkçe özel karakter
    assert not t._looks_english("mavi bluz")        # ASCII Türkçe, EN sözlükte yok
    assert not t._looks_english("merhaba")
