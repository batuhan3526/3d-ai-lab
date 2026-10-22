"""PartCrafter image→3D engine adapter (parça-bilinçli, TripoSG-tabanlı, MIT).

Foto → num_parts adet parça mesh üretir → tek GLB'ye BİRLEŞTİRİR (clothing app
tek-garment akışı için; parça-ayrımı ileride designer'da kullanılabilir).
src/partcrafter importları lazy (yalnız ~/PartCrafter venv'inde, PYTHONPATH=~/PartCrafter).

Params: num_parts (1-16), num_tokens, num_inference_steps, guidance_scale, seed.
"""
from __future__ import annotations

import os
from pathlib import Path

from common.config import engines_dir

# Override weight dirs with PARTCRAFTER_DIR / PARTCRAFTER_RMBG_DIR (portability).
_PC_DIR = os.environ.get(
    "PARTCRAFTER_DIR",
    str(engines_dir() / "PartCrafter" / "pretrained_weights" / "PartCrafter"),
)
_RMBG_DIR = os.environ.get(
    "PARTCRAFTER_RMBG_DIR",
    str(engines_dir() / "PartCrafter" / "pretrained_weights" / "RMBG-1.4"),
)


class PartCrafterImageEngine:
    def __init__(self) -> None:
        self._pipe = None
        self._rmbg = None

    def is_loaded(self) -> bool:
        return self._pipe is not None

    def load(self) -> None:
        if self._pipe is not None:
            return
        import torch
        from huggingface_hub import snapshot_download
        from src.models.briarmbg import BriaRMBG
        from src.pipelines.pipeline_partcrafter import PartCrafterPipeline
        snapshot_download(repo_id="wgsxm/PartCrafter", local_dir=_PC_DIR)
        # RMBG: yalnız pytorch ağırlıkları + modeling dosyaları (onnx/örnek görseller gereksiz)
        snapshot_download(repo_id="briaai/RMBG-1.4", local_dir=_RMBG_DIR,
                          allow_patterns=["*.pth", "*.py", "*.json", "*.txt"])
        self._rmbg = BriaRMBG.from_pretrained(_RMBG_DIR).to("cuda").eval()
        self._pipe = PartCrafterPipeline.from_pretrained(_PC_DIR).to("cuda", torch.float16)

    def unload(self) -> None:
        if self._pipe is None:
            return
        del self._pipe
        self._pipe = None
        self._rmbg = None
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
        import torch
        import trimesh
        from src.utils.image_utils import prepare_image
        num_parts = int(params.get("num_parts", 4))
        num_parts = max(1, min(16, num_parts))
        seed = params.get("seed")
        seed = int(seed) if seed is not None else 0
        # prepare_image bir DOSYA YOLU bekler (kendi açar + arka plan kaldırır)
        img = prepare_image(image_path, bg_color=np.array([1.0, 1.0, 1.0]), rmbg_net=self._rmbg)
        meshes = self._pipe(
            image=[img] * num_parts,
            attention_kwargs={"num_parts": num_parts},
            num_tokens=int(params.get("num_tokens", 1024)),
            generator=torch.Generator(device="cuda").manual_seed(seed),
            num_inference_steps=int(params.get("num_inference_steps", 50)),
            guidance_scale=float(params.get("guidance_scale", 7.0)),
            max_num_expanded_coords=int(1e9),
            use_flash_decoder=False,
        ).meshes
        parts = [m for m in meshes if m is not None and len(getattr(m, "faces", [])) > 1]
        if not parts:
            raise RuntimeError("PartCrafter hiç geçerli parça üretmedi")
        combined = trimesh.util.concatenate(parts)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        combined.export(str(out_path))
        return out_path
