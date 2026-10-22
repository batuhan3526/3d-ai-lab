"""TRELLIS-text motor adapter'ı. torch/trellis importları fonksiyon-içi (lazy)."""
from __future__ import annotations

import time
from pathlib import Path


def build_full_prompt(prompt_en: str, garment_type: str) -> str:
    """Motora giden İngilizce tam prompt (kalıp uygulanmamış ham prompt için)."""
    return f"{prompt_en}, a {garment_type} clothing item, 3d model"


class TrellisTextEngine:
    def __init__(self) -> None:
        self._pipe = None

    def is_loaded(self) -> bool:
        return self._pipe is not None

    def load(self) -> None:
        if self._pipe is not None:
            return
        from trellis.pipelines import TrellisTextTo3DPipeline
        self._pipe = TrellisTextTo3DPipeline.from_pretrained(
            "microsoft/TRELLIS-text-xlarge")
        self._pipe.cuda()

    def unload(self) -> None:
        if self._pipe is None:
            return
        del self._pipe
        self._pipe = None
        import torch
        torch.cuda.empty_cache()

    def mem_report(self) -> dict:
        import torch
        if not torch.cuda.is_available():
            return {"loaded": self.is_loaded(), "reserved_mb": 0, "allocated_mb": 0}
        return {
            "loaded": self.is_loaded(),
            "reserved_mb": int(torch.cuda.memory_reserved() / 1024 / 1024),
            "allocated_mb": int(torch.cuda.memory_allocated() / 1024 / 1024),
        }

    def generate(self, prompt_en: str, garment_type: str, params: dict,
                 out_path: Path) -> Path:
        self.load()
        full_prompt = prompt_en  # worker tam prompt'u kurar (kalıp veya verbatim)
        seed = params.get("seed")
        if seed is None:
            seed = int(time.time()) % 2147483647
        outputs = self._pipe.run(
            full_prompt,
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
