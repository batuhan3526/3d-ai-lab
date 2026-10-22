import text_to_3d.trellis_worker as w


def test_get_engine_single_resident_evicts_others(monkeypatch):
    class _Fake:
        def __init__(self): self.unloaded = False
        def unload(self): self.unloaded = True
    monkeypatch.delenv("MULTI_RESIDENT", raising=False)
    w._ENGINES.clear()
    old = _Fake()
    w._ENGINES["trellis-text"] = old
    monkeypatch.setattr(w, "_make_engine", lambda eid: _Fake())
    e = w._get_engine("trellis-image")
    assert old.unloaded is True
    assert set(w._ENGINES) == {"trellis-image"}
    assert e is w._ENGINES["trellis-image"]
    w._ENGINES.clear()


def test_get_engine_multi_resident_keeps_others(monkeypatch):
    class _Fake:
        def __init__(self): self.unloaded = False
        def unload(self): self.unloaded = True
    w._ENGINES.clear()
    old = _Fake()
    w._ENGINES["trellis-text"] = old
    monkeypatch.setenv("MULTI_RESIDENT", "1")
    monkeypatch.setattr(w, "_make_engine", lambda eid: _Fake())
    w._get_engine("trellis-image")
    assert old.unloaded is False           # MULTI_RESIDENT → boşaltma YOK
    assert set(w._ENGINES) == {"trellis-text", "trellis-image"}
    w._ENGINES.clear()
