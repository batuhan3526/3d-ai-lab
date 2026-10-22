"""Hunyuan3D-2mv multi-view engine (çoklu foto->3D, shape-only, non-commercial).

torch/hy3dshape/PIL importları lazy (yalnız hunyuan venv'inde var).
Desteklenen görünüm anahtarları: 'front', 'left', 'back', 'right' (MVImageProcessorV2'ye göre).
1-4 görsel verilir; eksik görünümler atlanır; dict en az 1 anahtar içermeli.
Texture YOK (shape mesh direkt export); gateway lazy mesh_view.glb üretir.

NOT: 2mv model config'i hy3dgen.shapegen.* importları kullanır (2.0 kodu).
2.1 venv'inde hy3dgen paketi yoktur; hy3dshape içindeki hy3dgen/ shim'i bunu çözer.
Worker'ın PYTHONPATH'i <ENGINES_DIR>/hunyuan3d-2.1/hy3dshape içermeli (infra/engines/hunyuan.sh verir).
"""
from __future__ import annotations

from pathlib import Path

_MV_MODEL = "tencent/Hunyuan3D-2mv"

# Görünüm sırası (MVImageProcessorV2.view2idx ile birebir): front=0, left=1, back=2, right=3
_VIEW_ORDER = ["front", "left", "back", "right"]


class HunyuanMVEngine:
    def __init__(self) -> None:
        self._pipe = None

    def is_loaded(self) -> bool:
        return self._pipe is not None

    def load(self) -> None:
        if self._pipe is not None:
            return
        import os
        # XET stall'ını önle
        os.environ.setdefault("HF_HUB_DISABLE_XET", "1")
        from hy3dshape.pipelines import Hunyuan3DDiTFlowMatchingPipeline
        self._pipe = Hunyuan3DDiTFlowMatchingPipeline.from_pretrained(
            _MV_MODEL,
            subfolder="hunyuan3d-dit-v2-mv",
            use_safetensors=True,  # safetensors daha hızlı yüklenir; tencent/Hunyuan3D-2mv'de mevcut
        )

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
                return {
                    "loaded": self.is_loaded(),
                    "reserved_mb": int(torch.cuda.memory_reserved() / 1024 / 1024),
                    "allocated_mb": int(torch.cuda.memory_allocated() / 1024 / 1024),
                }
        except Exception:  # noqa: BLE001
            pass
        return {"loaded": self.is_loaded(), "reserved_mb": 0, "allocated_mb": 0}

    def generate(
        self,
        image_paths: list[str],
        garment_type: str,
        params: dict,
        out_path: Path,
    ) -> Path:
        """Birden çok görsel yolundan 3D mesh üret.

        image_paths sıralanır: [0]=front, [1]=left, [2]=back, [3]=right.
        Eksik görünümler (1-3 görsel) sessizce atlanır.
        """
        self.load()
        from hy3dshape.rembg import BackgroundRemover
        from PIL import Image

        rembg = BackgroundRemover()

        # Sağlanan görselleri görünüm adlarıyla eşleştir (sıra: front, left, back, right)
        view_keys = _VIEW_ORDER[: len(image_paths)]
        image_dict: dict = {}
        for view_key, img_path in zip(view_keys, image_paths):
            img = Image.open(img_path).convert("RGBA")
            img = rembg(img)
            image_dict[view_key] = img

        seed = params.get("seed")
        generator = None
        if seed is not None:
            import torch
            generator = torch.Generator(device="cuda").manual_seed(int(seed))

        mesh = self._pipe(
            image=image_dict,
            num_inference_steps=params["num_inference_steps"],
            guidance_scale=params["guidance_scale"],
            octree_resolution=params["octree_resolution"],
            generator=generator,
            output_type="trimesh",
        )[0]

        out_path.parent.mkdir(parents=True, exist_ok=True)
        mesh.export(str(out_path))
        return out_path
