"""Hunyuan3D-2.1 shape engine (image->3D, SHAPE-ONLY, non-commercial).

torch/hy3dshape/PIL importları lazy (yalnız hunyuan venv'inde var).
octree_resolution, num_inference_steps, guidance_scale doğrudan resolve_engine_params
dict'inden okunur. Texture YOK (29GB>24GB), shape mesh direkt export.
"""
from __future__ import annotations

from pathlib import Path

_MODEL = "tencent/Hunyuan3D-2.1"


class HunyuanImageEngine:
    def __init__(self) -> None:
        self._pipe = None

    def is_loaded(self) -> bool:
        return self._pipe is not None

    def load(self) -> None:
        if self._pipe is not None:
            return
        from hy3dshape.pipelines import Hunyuan3DDiTFlowMatchingPipeline
        self._pipe = Hunyuan3DDiTFlowMatchingPipeline.from_pretrained(_MODEL)

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

    def generate(self, image_path: str, garment_type: str, params: dict,
                 out_path: Path) -> Path:
        self.load()
        from hy3dshape.rembg import BackgroundRemover
        from PIL import Image
        img = Image.open(image_path).convert("RGBA")
        img = BackgroundRemover()(img)
        seed = params.get("seed")
        generator = None
        if seed is not None:
            import torch
            generator = torch.Generator(device="cuda").manual_seed(seed)
        mesh = self._pipe(
            image=img,
            num_inference_steps=params["num_inference_steps"],
            guidance_scale=params["guidance_scale"],
            octree_resolution=params["octree_resolution"],
            generator=generator,
            output_type="trimesh",
        )[0]
        # Tam çözünürlük KORUNUR (üretim/edit hep full model üzerinden).
        # Görüntüleme için hafif kopyayı gateway lazy üretir (mesh_view.glb).
        out_path.parent.mkdir(parents=True, exist_ok=True)
        mesh.export(str(out_path))
        return out_path
