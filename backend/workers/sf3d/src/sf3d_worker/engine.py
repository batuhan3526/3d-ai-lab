"""Stable-Fast-3D (SF3D) image→3D engine adapter (hızlı ~1s, PBR dokulu, UV'li).

torch/sf3d/rembg/PIL importları lazy (yalnız ~/stable-fast-3d venv'inde). Çıktı:
UV + PBR materyalli textured GLB (TripoSR vertex-color'dan üstün; InTeX yeniden-dokulamaya
uygun). LİSANS: Stability AI Community License (ticari kullanım koşullu — etikette belirtilir).

Params dict: texture_resolution (doku atlası), remesh_option (none|triangle|quad),
target_vertex_count (-1=indirme yok), foreground_ratio.
"""
from __future__ import annotations

from pathlib import Path

_MODEL = "stabilityai/stable-fast-3d"


class SF3DImageEngine:
    def __init__(self) -> None:
        self._model = None
        self._rembg = None

    def is_loaded(self) -> bool:
        return self._model is not None

    def load(self) -> None:
        if self._model is not None:
            return
        from sf3d.system import SF3D
        self._model = SF3D.from_pretrained(
            _MODEL, config_name="config.yaml", weight_name="model.safetensors",
        )
        self._model.to("cuda")
        self._model.eval()

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
        import rembg
        import torch
        from PIL import Image
        from sf3d.utils import remove_background, resize_foreground
        if self._rembg is None:
            self._rembg = rembg.new_session()
        fg = float(params.get("foreground_ratio", 0.85))
        tex = int(params.get("texture_resolution", 1024))
        remesh = str(params.get("remesh_option", "none"))
        vcount = int(params.get("target_vertex_count", -1))
        image = remove_background(Image.open(image_path).convert("RGBA"), self._rembg)
        image = resize_foreground(image, fg)
        with torch.no_grad(), torch.autocast(device_type="cuda", dtype=torch.bfloat16):
            mesh, _ = self._model.run_image(
                image, bake_resolution=tex, remesh=remesh, vertex_count=vcount,
            )
        out_path.parent.mkdir(parents=True, exist_ok=True)
        mesh.export(str(out_path), include_normals=True)
        return out_path
