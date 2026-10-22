import inspect

from text_to_3d.engines.trellis_image import TrellisImageEngine


def test_generate_multi_exists_with_signature():
    sig = inspect.signature(TrellisImageEngine.generate_multi)
    params = list(sig.parameters)
    assert params == ["self", "image_paths", "garment_type", "params", "out_path"]
