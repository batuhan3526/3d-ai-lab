"""ArtiFixer run_inference — 24GB VRAM (3090) sarmalayıcısı: int8 quantize / CPU-offload.

14B WanTransformer bf16'da ~28GB → tek 3090'a sığmaz. İki strateji (env ile seçilir):

  ARTIFIXER_QUANTIZE=int8   (varsayılan) torchao int8 weight-only → ~14GB, GPU'da koşar.
                            torchao yoksa/quantize patlarsa otomatik offload'a düşer.
  ARTIFIXER_QUANTIZE=none   quantize etme; ARTIFIXER_CPU_OFFLOAD=1 ise accelerate
                            cpu_offload (ağırlıklar CPU'da, forward'da bloklar GPU'ya akar).
  ARTIFIXER_CPU_OFFLOAD=0 + ARTIFIXER_QUANTIZE=none → orijinal davranış (büyük VRAM).

Not: checkpoint state_dict quantize'dan ÖNCE yüklenmeli; bu yüzden quantize burada
değil, checkpoint yüklemesinden sonra da çağrılabilsin diye pipe'a _artifixer_finalize
kancası iliştirilir ve run_inference.main içindeki yükleme akışına dokunulmaz —
torchao'nun Linear swap'i state_dict yüklemesini bozmasın diye quantize işlemi
get_eval_pipe dönüşünde DEĞİL, checkpoint yüklendikten sonraki ilk forward öncesinde
yapılmaz; pratikte run_inference checkpoint'i get_eval_pipe SONRASI yükler, bu yüzden
biz quantize'ı lazy yaparız: transformer'a forward-pre-hook takılır, ilk forward'dan
hemen önce (ağırlıklar artık final) quantize+GPU taşıma gerçekleşir.

Kullanım: python -m artifixer_worker.run_inference_offload <run_inference argları>
"""
from __future__ import annotations

import os

import torch

from model_eval import run_inference as _ri

_QUANT = os.getenv("ARTIFIXER_QUANTIZE", "int8").lower()
_OFFLOAD = os.getenv("ARTIFIXER_CPU_OFFLOAD", "1") != "0"


def _try_quantize_to_gpu(transformer: torch.nn.Module, device: torch.device) -> bool:
    """int8 weight-only quantize + GPU'ya taşı. Başarı=True; hata=False (offload'a düş)."""
    try:
        from torchao.quantization import Int8WeightOnlyConfig, quantize_  # noqa: PLC0415
    except ImportError:
        print("[quant] torchao yok → CPU-offload'a düşülüyor (pip install torchao)")
        return False
    try:
        n = sum(p.numel() for p in transformer.parameters())
        print(f"[quant] transformer {n/1e9:.1f}B param int8 weight-only quantize ediliyor...")
        quantize_(transformer, Int8WeightOnlyConfig())
        transformer.to(device)
        free, total = torch.cuda.mem_get_info(device)
        print(f"[quant] OK — GPU'da; boş VRAM {free/1e9:.1f}/{total/1e9:.1f}GB")
        return True
    except Exception as exc:  # noqa: BLE001
        print(f"[quant] BAŞARISIZ ({exc}) → CPU-offload'a düşülüyor")
        try:
            transformer.to("cpu")
            torch.cuda.empty_cache()
        except Exception:  # noqa: BLE001
            pass
        return False


def _install_lazy_finalizer(pipe, device: torch.device) -> None:
    """İlk forward'dan hemen önce quantize/offload uygula (ckpt o ana dek yüklenmiş olur)."""
    from accelerate import cpu_offload  # noqa: PLC0415

    tr = pipe.transformer
    state = {"done": False}

    def _finalize(module, args, kwargs=None):
        if state["done"]:
            return
        state["done"] = True
        handle.remove()
        ok = _QUANT == "int8" and _try_quantize_to_gpu(tr, device)
        if not ok:
            if _OFFLOAD:
                cpu_offload(tr, execution_device=device)
                print(f"[offload] transformer CPU-offload aktif (exec={device})")
            else:
                tr.to(device)
                print("[offload] kapalı → transformer doğrudan GPU'ya taşındı")

    handle = tr.register_forward_pre_hook(_finalize)


def _wrapped_eval_pipe(args, device: torch.device):
    """Orijinal get_eval_pipe'ın 24GB karşılığı: transformer CPU'da bırakılır, gerisi GPU."""
    if args.inference_pipeline == "bidirectional":
        pipe = _ri.get_pipe(
            args,
            load_pretrained_transformer_weights=False,
            frames_per_block=None,
            device=device,  # vae/scheduler cihaz seçimi orijinalle aynı
        )
    else:
        pipe = _ri.get_kv_cache_pipe(args, device)

    pipe = pipe.to(torch.bfloat16)  # yalnız dtype; toplu cihaz taşıma YOK

    if isinstance(getattr(pipe, "vae", None), torch.nn.Module):
        pipe.vae.to(device)
    _install_lazy_finalizer(pipe, device)
    return pipe


def main() -> None:
    if _QUANT == "int8" or _OFFLOAD:
        _ri.get_eval_pipe = _wrapped_eval_pipe
        print(f"[24GB modu] get_eval_pipe sarıldı — quantize={_QUANT} offload={_OFFLOAD}")
    _ri.main(_ri.parse_args())


if __name__ == "__main__":
    main()
