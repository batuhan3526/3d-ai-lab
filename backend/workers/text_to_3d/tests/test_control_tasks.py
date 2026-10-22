import text_to_3d.trellis_worker as w


def test_engine_status_shape_no_torch():
    r = w.engine_status.run()
    assert set(r) == {"gpu", "loaded", "reserved_mb", "allocated_mb"}
    assert r["loaded"] == []
    assert r["reserved_mb"] == 0
    assert isinstance(r["gpu"], str)


def test_engine_release_cache_mode_safe():
    r = w.engine_release.run(mode="cache")
    assert r["mode"] == "cache"
    assert r["unloaded"] == []


def test_engine_release_model_mode_clears_cache():
    class _Fake:
        def __init__(self): self.unloaded = False
        def unload(self): self.unloaded = True
    f = _Fake()
    w._ENGINES["trellis-text"] = f
    r = w.engine_release.run(mode="model")
    assert "trellis-text" in r["unloaded"]
    assert f.unloaded is True
    assert w._ENGINES == {}
