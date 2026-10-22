"""Hi3DGen image→3D engine adapter (geometri-detaylı, normal-map kılavuzlu, MIT).

Akış: foto → StableNormal (normal-map) → Hi3DGen TRELLIS-normal backbone → mesh.
hi3dgen/torch/PIL importları lazy (yalnız ~/Hi3DGen venv'inde; TRELLIS kernel'leri
kopyalanmış venv). Backbone TRELLIS-türevi → ATTN_BACKEND=xformers + SPARSE_BACKEND=spconv.

Çıktı: yüksek-detaylı geometri mesh (doku değil; geometri odaklı). Sonradan InTeX ile
doku eklenebilir. Params: ss_steps/ss_cfg (sparse-structure), slat_steps/slat_cfg, seed.
"""
from __future__ import annotations

import os
from pathlib import Path

from common.config import engines_dir

_MODEL = "Stable-X/trellis-normal-v0-1"
# Override with HI3DGEN_WEIGHTS; default is the Hi3DGen checkout's weights dir.
_WEIGHTS_DIR = os.environ.get(
    "HI3DGEN_WEIGHTS", str(engines_dir() / "Hi3DGen" / "weights")
)


class Hi3DGenImageEngine:
    def __init__(self) -> None:
        self._pipe = None
        self._normal = None

    def is_loaded(self) -> bool:
        return self._pipe is not None

    def load(self) -> None:
        if self._pipe is not None:
            return
        os.environ.setdefault("ATTN_BACKEND", "xformers")
        os.environ.setdefault("SPARSE_BACKEND", "spconv")
        os.environ.setdefault("SPCONV_ALGO", "native")
        import torch
        from hi3dgen.pipelines import Hi3DGenPipeline
        self._pipe = Hi3DGenPipeline.from_pretrained(_MODEL)
        self._pipe.cuda()
        self._normal = torch.hub.load(
            "hugoycj/StableNormal", "StableNormal_turbo", trust_repo=True,
            yoso_version="yoso-normal-v1-8-1", local_cache_dir=_WEIGHTS_DIR,
        )

    def unload(self) -> None:
        if self._pipe is None:
            return
        del self._pipe
        self._pipe = None
        self._normal = None
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
        img = Image.open(image_path)
        img = self._pipe.preprocess_image(img, resolution=1024)
        normal_image = self._normal(img, resolution=768, match_input_resolution=True,
                                    data_type="object")
        seed = params.get("seed")
        outputs = self._pipe.run(
            normal_image,
            seed=int(seed) if seed is not None else 0,
            formats=["mesh"],
            preprocess_image=False,
            sparse_structure_sampler_params={
                "steps": int(params.get("ss_steps", 50)),
                "cfg_strength": float(params.get("ss_cfg", 3.0)),
            },
            slat_sampler_params={
                "steps": int(params.get("slat_steps", 6)),
                "cfg_strength": float(params.get("slat_cfg", 3.0)),
            },
        )
        mesh = outputs["mesh"][0].to_trimesh(transform_pose=True)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        mesh.export(str(out_path))
        return out_path

    def generate_multi(self, image_paths: list[str], garment_type: str, params: dict,
                       out_path: Path) -> Path:
        """Multi-view (multi-image) → 3D: converts each image to a normal map then
        calls run_multi_image with the full list of normals.  Mirrors generate() exactly
        except for the multi-image call path.
        """
        self.load()
        from PIL import Image
        normals = []
        for path in image_paths:
            img = Image.open(path)
            img = self._pipe.preprocess_image(img, resolution=1024)
            normal_image = self._normal(img, resolution=768, match_input_resolution=True,
                                        data_type="object")
            normals.append(normal_image)
        seed = params.get("seed")
        outputs = self._pipe.run_multi_image(
            normals,
            seed=int(seed) if seed is not None else 0,
            formats=["mesh"],
            preprocess_image=False,
            sparse_structure_sampler_params={
                "steps": int(params.get("ss_steps", 50)),
                "cfg_strength": float(params.get("ss_cfg", 3.0)),
            },
            slat_sampler_params={
                "steps": int(params.get("slat_steps", 6)),
                "cfg_strength": float(params.get("slat_cfg", 3.0)),
            },
        )
        mesh = outputs["mesh"][0].to_trimesh(transform_pose=True)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        mesh.export(str(out_path))
        return out_path
