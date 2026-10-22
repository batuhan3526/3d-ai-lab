import pytest
from common.engines.registry import (list_specs, resolve_engine_params,
                                     visible_gpu_set)


def test_specs_expose_params_and_presets():
    allowed = visible_gpu_set()
    for s in list_specs():
        assert isinstance(s["params"], list)  # edit motorları (intex) param'sız olabilir
        # Tek-GPU sözleşmesi: spec gpus'ları görünür kümenin alt kümesi olmalı
        # (hardcode [0,1] YOK; tek-GPU host'ta {0}).
        assert set(s["gpus"]) <= allowed
        assert "adapter" not in s
        # Placeholder/gated (available=False) motorlar katalog-kalite (preset/param
        # içerik) sözleşmesinden muaf — seçilemezler.
        if not s["available"]:
            continue
        assert set(s["presets"]) >= {"fast", "balanced", "quality"}
        # üretim motorları (text/image) ayarlanabilir param'lara sahip olmalı
        if s["kind"] in ("text", "image"):
            assert s["params"]


def test_nc_engines_not_recommended():
    # NC/gated motorlar "Önerilen" ROZETİ almaz. 2026-10-19'dan beri yerel kopyada
    # açık (ağırlıklar indirilmiş); ticari değil bayrağı korunur.
    by_id = {s["id"]: s for s in list_specs()}
    for eid in ("hunyuan-image", "hunyuan-mv", "worldtracing-image"):
        assert by_id[eid]["commercial_use"] is False
        assert by_id[eid]["recommended"] == ""
        assert by_id[eid]["available"] is True


def test_placeholder_engines_stay_unavailable():
    # Kodu/ağırlığı yayınlanmamış motorlar açılırsa işler kuyrukta asılı kalır.
    by_id = {s["id"]: s for s in list_specs()}
    for eid in ("flex4dhuman-4d", "pixworld-scene"):
        assert by_id[eid]["available"] is False


def test_resolve_trellis_balanced():
    p = resolve_engine_params("trellis-text", "balanced", None)
    assert p["sparse_steps"] == 25 and p["texture_size"] == 1024


def test_resolve_trellis_advanced_override():
    p = resolve_engine_params("trellis-image", "fast", {"texture_size": 256, "seed": 7})
    assert p["texture_size"] == 256 and p["seed"] == 7
    assert p["sparse_steps"] == 12  # fast preset


def test_resolve_hunyuan_has_own_params():
    p = resolve_engine_params("hunyuan-image", "quality", None)
    assert p["num_inference_steps"] == 50 and p["octree_resolution"] == 512
    assert "sparse_steps" not in p  # hunyuan'in kendi semasi


def test_resolve_rejects_unknown_param():
    with pytest.raises(ValueError):
        resolve_engine_params("hunyuan-image", "fast", {"sparse_steps": 5})


def test_resolve_rejects_out_of_range():
    with pytest.raises(ValueError):
        resolve_engine_params("trellis-text", "fast", {"texture_size": 999})
    with pytest.raises(ValueError):
        resolve_engine_params("trellis-text", "fast", {"sparse_steps": 500})


def test_resolve_unknown_preset():
    with pytest.raises(ValueError):
        resolve_engine_params("trellis-text", "ultra", None)
