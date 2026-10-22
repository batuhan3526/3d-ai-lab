from text_to_3d.engines.trellis_image import TrellisImageEngine


def test_engine_instantiates_and_not_loaded():
    e = TrellisImageEngine()
    assert e.is_loaded() is False


def test_mem_report_keys_without_torch():
    e = TrellisImageEngine()
    r = e.mem_report()
    assert set(r) >= {"loaded", "reserved_mb", "allocated_mb"}
