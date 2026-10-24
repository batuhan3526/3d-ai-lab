"""Pixal3D image→3D adaptörü (TencentARC/Pixal3D, MIT; SIGGRAPH 2026).

Piksel özelliklerini geri izdüşümle 3B'ye taşır (pixel-aligned): görsele sadakat
TRELLIS.2/Hunyuan3D'den yüksek. Omurga TRELLIS.2 (açık yüzey, PBR); kamera açısı MoGe-2
ile tahmin edilir. Upstream inference.py modülü kullanılır; boru hattı bir kez kurulur.
Görüntü kodlayıcı DINOv3: upstream ayna depo yerine Meta'nın resmi deposu (HF erişimi
gerekir). Arka plan silme: gated RMBG-2.0 yerine açık BiRefNet (MIT).
"""
from __future__ import annotations

import os
from pathlib import Path

_DINOV3 = "facebook/dinov3-vitl16-pretrain-lvd1689m"
_OPEN_REMBG = "ZhengPeng7/BiRefNet"


class Pixal3DImageEngine:
    def __init__(self) -> None:
        self._inf = None
        self._pipe = None
        self._low_vram = None

    def is_loaded(self) -> bool:
        return self._pipe is not None

    def _module(self):
        if self._inf is None:
            os.environ.setdefault("ATTN_BACKEND", "xformers")
            os.environ.setdefault("SPARSE_ATTN_BACKEND", "xformers")
            import inference as inf  # engines/Pixal3D (ENGINE_EXTRA_PATH)
            for cfg in inf.IMAGE_COND_CONFIGS.values():
                cfg["model_name"] = _DINOV3
            try:
                from pixal3d.pipelines import rembg
                base = rembg.BiRefNet

                class _OpenBiRefNet(base):
                    def __init__(self, model_name: str | None = None, **_kw) -> None:
                        super().__init__(_OPEN_REMBG)

                rembg.BiRefNet = _OpenBiRefNet
            except (ImportError, AttributeError):
                pass
            self._inf = inf
        return self._inf

    def load(self, low_vram: bool = True) -> None:
        if self._pipe is not None and self._low_vram == low_vram:
            return
        self.unload()
        self._pipe = self._module().init_pipeline(low_vram=low_vram)
        self._low_vram = low_vram

    def unload(self) -> None:
        if self._pipe is None:
            return
        del self._pipe
        self._pipe = None
        import torch
        torch.cuda.empty_cache()

    def mem_report(self) -> dict:
        try:
            import torch
            if torch.cuda.is_available():
                return {"loaded": self.is_loaded(),
                        "reserved_mb": int(torch.cuda.memory_reserved() / 1024 / 1024),
                        "allocated_mb": int(torch.cuda.memory_allocated() / 1024 / 1024)}
        except Exception:  # noqa: BLE001
            pass
        return {"loaded": self.is_loaded(), "reserved_mb": 0, "allocated_mb": 0}

    def generate(self, image_path: str, garment_type: str, params: dict, out_path: Path) -> Path:
        low_vram = bool(params.get("low_vram", True))
        self.load(low_vram)
        inf = self._module()
        pipe = self._pipe
        orig = inf.init_pipeline
        inf.init_pipeline = lambda *a, **k: pipe       # upstream her çağrıda yeniden kurar
        try:
            out_path.parent.mkdir(parents=True, exist_ok=True)
            seed = params.get("seed")
            inf.run_inference(image_path=image_path, output_path=str(out_path),
                              seed=42 if seed is None else int(seed),
                              manual_fov=float(params.get("fov", -1.0)), low_vram=low_vram,
                              resolution=int(params.get("resolution", 1024)))
        finally:
            inf.init_pipeline = orig
        return out_path
