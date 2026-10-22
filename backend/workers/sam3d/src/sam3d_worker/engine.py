"""SAM 3D Objects image→3D engine adapter (gerçek-foto reconstruction, SAM License).

Meta SAM 3D Objects: maskeli nesneyi 3D'ye çevirir. tdfy_dit backbone (TRELLIS-türevi).
Çıktı: DOKULU mesh (with_mesh_postprocess + texture_baking → outputs["glb"], PBR trimesh).
Düzensiz/gerçek-dünya fotolarında sağlam. Garment fotosu için maske rembg ile üretilir.

Ortam: conda env `sam3d-objects` (torch2.5.1/cu121 + pytorch3d + kaolin). Inference repo-
göreli checkpoint yolu ister → load'da cwd=repo-root + notebook sys.path.

NOT: setup.md 32GB VRAM önerir; 24GB'a sığmazsa low_vram/offload denenir (LOW_VRAM env).
LİSANS: SAM License (Meta) — ticari kısıtları olabilir, UI'da etiketli.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

from common.config import engines_dir

# Override the SAM3D-Objects checkout root with SAM3D_DIR (portability).
_ROOT = os.environ.get("SAM3D_DIR", str(engines_dir() / "SAM3D-Objects"))
_CONFIG = "checkpoints/hf/pipeline.yaml"


class SAM3DObjectEngine:
    def __init__(self) -> None:
        self._inf = None
        self._rembg = None

    def is_loaded(self) -> bool:
        return self._inf is not None

    def load(self) -> None:
        if self._inf is not None:
            return
        os.chdir(_ROOT)
        nb = os.path.join(_ROOT, "notebook")
        if nb not in sys.path:
            sys.path.insert(0, nb)
        from inference import Inference
        self._inf = Inference(_CONFIG, compile=False)

    def unload(self) -> None:
        if self._inf is None:
            return
        del self._inf
        self._inf = None
        self._rembg = None
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
        from PIL import Image
        if self._rembg is None:
            self._rembg = rembg.new_session()
        # garment fotosu → rembg ön-plan maskesi (SAM3D maskeli nesne bekler)
        rgba = rembg.remove(Image.open(image_path).convert("RGB"), session=self._rembg)
        arr = np.array(rgba.convert("RGBA"))
        image_np = arr[..., :3]
        mask_np = arr[..., 3] > 127  # bool ön-plan
        seed = params.get("seed")
        seed = int(seed) if seed is not None else 42
        rgba_image = self._inf.merge_mask_to_rgba(image_np, mask_np)
        outputs = self._inf._pipeline.run(
            rgba_image,
            None,
            seed,
            stage1_only=False,
            with_mesh_postprocess=True,
            with_texture_baking=True,
            use_vertex_color=False,
        )
        glb = outputs.get("glb")
        if glb is None:
            raise RuntimeError("SAM3D mesh/glb üretmedi (outputs['glb'] yok)")
        out_path.parent.mkdir(parents=True, exist_ok=True)
        glb.export(str(out_path))
        return out_path
