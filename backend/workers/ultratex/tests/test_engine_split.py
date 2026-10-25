"""UltraTex bellek yardımcıları: önbellekli metin koşulu + DiT bloklarını ikinci karta bölme.

ultratex conda ortamında çalışır (torch gerekir):
  ~/miniforge3/envs/ultratex/bin/python -m pytest backend/workers/ultratex/tests
"""
import pytest

torch = pytest.importorskip("torch")

from ultratex_worker.engine import _CachedEncoder, _split_blocks  # noqa: E402


def test_cached_encoder_repeats_for_batch():
    ctx = torch.randn(1, 7, 4)
    enc = _CachedEncoder(ctx)
    out = enc(["", ""])
    assert out.shape == (2, 7, 4)
    assert torch.equal(out[1], ctx[0])
    assert enc.eval() is enc and enc.requires_grad_(False) is enc


def test_cached_encoder_rejects_prompt():
    with pytest.raises(ValueError):
        _CachedEncoder(torch.zeros(1, 1, 1))(["kırmızı elbise"])


class _Block(torch.nn.Module):
    def __init__(self) -> None:
        super().__init__()
        self.lin = torch.nn.Linear(8, 8)

    def forward_kv_extract(self, img, pe, scale):
        return self.lin(img) * scale + pe, None


class _Dit(torch.nn.Module):
    def __init__(self) -> None:
        super().__init__()
        self.inp = torch.nn.Linear(8, 8)
        self.single_blocks = torch.nn.ModuleList(_Block() for _ in range(4))

    def forward(self, x, pe):
        img = self.inp(x)
        for b in self.single_blocks:
            img, _ = b.forward_kv_extract(img, pe, 0.5)
        return img


@pytest.mark.skipif(torch.cuda.device_count() < 2, reason="iki GPU gerekir")
def test_split_blocks_same_result_across_two_gpus():
    torch.manual_seed(0)
    dit = _Dit().to("cuda:0")
    x, pe = torch.randn(2, 5, 8, device="cuda:0"), torch.randn(2, 5, 8, device="cuda:0")
    ref = dit(x, pe)
    n = _split_blocks(dit, torch.device("cuda:1"))
    assert 0 < n < len(dit.single_blocks)
    assert next(dit.single_blocks[-1].parameters()).device.index == 1
    out = dit(x, pe)
    assert out.device.index == 0                       # son taşınan bloktan sonra asıl karta döner
    assert torch.allclose(out, ref, atol=1e-5)
