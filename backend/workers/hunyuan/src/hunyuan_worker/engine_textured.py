"""Hunyuan3D-2.1 TEXTURED engine (image->shape->paint, PBR doku).

LİSANS: Tencent Hunyuan NON-COMMERCIAL (ticari kullanım YASAK). Shape-only motorla
aynı ağırlıklar + ek paint pipeline (hy3dpaint).

SEQUENTIAL VRAM: shape (~8GB) ve paint (multiview diffusion + super-res + DINO-giant +
renderer; tek başına neredeyse tüm 24GB) BİRLİKTE tek GPU'ya sığmaz. Bu yüzden:
  shape yükle → mesh üret → shape BOŞALT (empty_cache) → paint yükle → dokula → boşalt.

Paint pipeline GÖRELİ yollar bekler (cfg: hy3dpaint/cfgs/..., ckpt: ckpt/RealESRGAN...)
ve hy3dpaint modülleri sys.path'te değildir → paint yüklemeden önce cwd=repo-root yapılır
ve hy3dpaint sys.path'e eklenir + torchvision uyumluluk yaması uygulanır (smoke ile aynı).
"""
from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

from common.config import engines_dir

_MODEL = "tencent/Hunyuan3D-2.1"
# Override the Hunyuan3D-2.1 checkout root with HUNYUAN_DIR (portability).
_ROOT = os.environ.get("HUNYUAN_DIR", str(engines_dir() / "hunyuan3d-2.1"))


class HunyuanTexturedEngine:
    def __init__(self) -> None:
        self._shape = None
        self._paint = None

    def is_loaded(self) -> bool:
        return self._shape is not None or self._paint is not None

    # ---- shape aşaması ----
    def _load_shape(self) -> None:
        if self._shape is None:
            from hy3dshape.pipelines import Hunyuan3DDiTFlowMatchingPipeline
            self._shape = Hunyuan3DDiTFlowMatchingPipeline.from_pretrained(_MODEL)

    def _unload_shape(self) -> None:
        if self._shape is not None:
            del self._shape
            self._shape = None
        self._empty_cache()

    # ---- paint aşaması ----
    def _load_paint(self) -> None:
        if self._paint is not None:
            return
        # paint göreli cfg/ckpt yolları + hy3dpaint modülleri için ortamı hazırla
        os.chdir(_ROOT)
        hy3dpaint = os.path.join(_ROOT, "hy3dpaint")
        if hy3dpaint not in sys.path:
            sys.path.insert(0, hy3dpaint)
        try:
            from utils.torchvision_fix import apply_fix
            apply_fix()
        except Exception:  # noqa: BLE001
            pass
        from textureGenPipeline import Hunyuan3DPaintConfig, Hunyuan3DPaintPipeline
        conf = Hunyuan3DPaintConfig(max_num_view=6, resolution=512)
        self._paint = Hunyuan3DPaintPipeline(conf)

    def _unload_paint(self) -> None:
        if self._paint is not None:
            del self._paint
            self._paint = None
        self._empty_cache()

    @staticmethod
    def _empty_cache() -> None:
        try:
            import torch
            torch.cuda.empty_cache()
        except Exception:  # noqa: BLE001
            pass

    def unload(self) -> None:
        self._unload_shape()
        self._unload_paint()

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
        from PIL import Image
        out_path = Path(out_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)

        # 1) SHAPE — arka planı kaldır, beyaz (dokusuz) mesh üret
        self._load_shape()
        from hy3dshape.rembg import BackgroundRemover
        img = Image.open(image_path).convert("RGBA")
        img = BackgroundRemover()(img)
        seed = params.get("seed")
        generator = None
        if seed is not None:
            import torch
            generator = torch.Generator(device="cuda").manual_seed(seed)
        mesh = self._shape(
            image=img,
            num_inference_steps=params["num_inference_steps"],
            guidance_scale=params["guidance_scale"],
            octree_resolution=params["octree_resolution"],
            generator=generator,
            output_type="trimesh",
        )[0]
        white_mesh = out_path.parent / "white_mesh.glb"
        mesh.export(str(white_mesh))
        # paint'in referans olarak kullanması için arka-planı kaldırılmış görseli kaydet
        ref_image = out_path.parent / "ref_image.png"
        img.save(str(ref_image))

        # SEQUENTIAL: paint için yer aç
        self._unload_shape()

        # 2) PAINT — beyaz mesh + referans görsel → PBR dokulu mesh
        self._load_paint()
        obj_out = out_path.parent / "textured_mesh.obj"
        self._paint(
            mesh_path=str(white_mesh),
            image_path=str(ref_image),
            output_mesh_path=str(obj_out),
        )
        glb_out = obj_out.with_suffix(".glb")
        if not glb_out.exists():
            raise RuntimeError(f"Paint dokulu GLB üretmedi: {glb_out}")
        # gateway projenin mesh.glb'sini servis ediyor → dokulu GLB'yi oraya yerleştir
        shutil.copyfile(str(glb_out), str(out_path))
        self._unload_paint()
        return out_path
