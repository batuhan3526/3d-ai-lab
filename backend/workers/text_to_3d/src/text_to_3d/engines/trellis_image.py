"""TRELLIS-image motor adapter'ı (foto→3D). torch/trellis/PIL importları lazy."""
from __future__ import annotations

import time
from pathlib import Path

_MODEL = "JeffreyXiang/TRELLIS-image-large"


class TrellisImageEngine:
    def __init__(self) -> None:
        self._pipe = None

    def is_loaded(self) -> bool:
        return self._pipe is not None

    def load(self) -> None:
        if self._pipe is not None:
            return
        from trellis.pipelines import TrellisImageTo3DPipeline
        self._pipe = TrellisImageTo3DPipeline.from_pretrained(_MODEL)
        self._pipe.cuda()

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
        from PIL import Image
        image = Image.open(image_path).convert("RGB")
        seed = params.get("seed")
        if seed is None:
            seed = int(time.time()) % 2147483647
        outputs = self._pipe.run(
            image,
            num_samples=params["num_samples"],
            seed=seed,
            sparse_structure_sampler_params={
                "steps": params["sparse_steps"], "cfg_strength": params["sparse_cfg"]},
            slat_sampler_params={
                "steps": params["slat_steps"], "cfg_strength": params["slat_cfg"]},
        )
        from trellis.utils import postprocessing_utils
        glb = postprocessing_utils.to_glb(
            outputs["gaussian"][0], outputs["mesh"][0],
            simplify=params["simplify"], texture_size=params["texture_size"],
        )
        out_path.parent.mkdir(parents=True, exist_ok=True)
        glb.export(str(out_path))
        return out_path

    def generate_multi(self, image_paths: list, garment_type: str, params: dict,
                       out_path: Path) -> Path:
        self.load()
        from PIL import Image
        images = [Image.open(p).convert("RGB") for p in image_paths]
        seed = params.get("seed")
        if seed is None:
            seed = int(time.time()) % 2147483647
        outputs = self._pipe.run_multi_image(
            images,
            num_samples=params["num_samples"],
            seed=seed,
            sparse_structure_sampler_params={
                "steps": params["sparse_steps"], "cfg_strength": params["sparse_cfg"]},
            slat_sampler_params={
                "steps": params["slat_steps"], "cfg_strength": params["slat_cfg"]},
        )
        from trellis.utils import postprocessing_utils
        glb = postprocessing_utils.to_glb(
            outputs["gaussian"][0], outputs["mesh"][0],
            simplify=params["simplify"], texture_size=params["texture_size"],
        )
        out_path.parent.mkdir(parents=True, exist_ok=True)
        glb.export(str(out_path))
        return out_path
