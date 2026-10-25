"""Hi3D çıktısı merkezli + birim yarıçaplı gelir; kaynağın kutusuna geri oturtulur."""
import numpy as np
from hi3d_worker.engine import fit_to_bounds


def test_fit_to_bounds_restores_source_box():
    rng = np.random.default_rng(0)
    src = rng.uniform([-0.2, 0.9, -0.1], [0.2, 1.5, 0.1], (500, 3))      # ~1.2 m'de bir kıyafet
    unit = (src - src.mean(0)) / np.linalg.norm(src - src.mean(0), axis=1).max()
    out = fit_to_bounds(unit, src)
    assert np.allclose(out.min(0), src.min(0)) and np.allclose(out.max(0), src.max(0))


def test_fit_to_bounds_keeps_aspect_ratio():
    src = np.array([[0, 0, 0], [2, 1, 1]], float)
    v = np.array([[0, 0, 0], [1, 1, 1]], float)                          # farklı oranlı çıktı
    out = fit_to_bounds(v, src)
    ext = out.max(0) - out.min(0)
    assert np.allclose(ext, [2, 2, 2])                                   # tekdüze ölçek, en uzun kenar eşit
    assert np.allclose((out.min(0) + out.max(0)) / 2, [1, 0.5, 0.5])


def test_openings_keep_long_loops_fill_tears():
    from hi3d_worker.engine import openings
    # elbise: etek ucu 1500, yaka 600, iki kol 350; yırtık 90, iğne delikleri 6
    lengths = [1500, 600, 350, 350, 90, 6, 6]
    assert openings(lengths, 1024) == {0, 1, 2, 3}
    assert openings([40, 8], 1024) == set()                              # açıklık yok: hepsi dolar
    assert openings([], 1024) == set()
