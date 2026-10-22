"""TripoSR image→3D engine adapter (hızlı feed-forward, ~4s inference, MIT).

torch/tsr/rembg/PIL/numpy importları lazy (yalnız TripoSR venv'inde). Params dict:
mc_resolution (marching-cubes çözünürlük), foreground_ratio. TripoSR deterministik
(seed yok). Vertex-color mesh export (texture-bake'siz; bpy/GL gerektirmez).
"""
from __future__ import annotations

from pathlib import Path

from common.engines.params import GenParams  # noqa: F401  (tip uyumu; params dict gelir)

_MODEL = "stabilityai/TripoSR"


class TripoSRImageEngine:
    def __init__(self) -> None:
        self._model = None
        self._rembg = None

    def is_loaded(self) -> bool:
        return self._model is not None

    def load(self) -> None:
        if self._model is not None:
            return
        from tsr.system import TSR
        self._model = TSR.from_pretrained(_MODEL, config_name="config.yaml",
                                          weight_name="model.ckpt")
        self._model.renderer.set_chunk_size(8192)
        self._model.to("cuda")

    def unload(self) -> None:
        if self._model is None:
            return
        del self._model
        self._model = None
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
        import numpy as np
        import rembg
        import torch
        from PIL import Image
        from tsr.utils import remove_background, resize_foreground
        if self._rembg is None:
            self._rembg = rembg.new_session()
        fg = float(params.get("foreground_ratio", 0.85))
        mc = int(params.get("mc_resolution", 256))
        image = remove_background(Image.open(image_path), self._rembg)
        image = resize_foreground(image, fg)
        arr = np.array(image).astype(np.float32) / 255.0
        arr = arr[:, :, :3] * arr[:, :, 3:4] + (1 - arr[:, :, 3:4]) * 0.5
        image = Image.fromarray((arr * 255.0).astype(np.uint8))
        with torch.no_grad():
            scene_codes = self._model([image], device="cuda")
        meshes = self._model.extract_mesh(scene_codes, True, resolution=mc)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        meshes[0].export(str(out_path))
        return out_path
