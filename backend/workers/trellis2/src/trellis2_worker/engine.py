"""TRELLIS.2 image→3D adaptörü (microsoft/TRELLIS.2-4B, MIT).

O-Voxel tabanlı; açık yüzeyleri (kıyafet, yaprak) ve manifold olmayan geometriyi
destekler — kapalı kütle yerine kol/boyun ağzı açık kabuk. torch/trellis2/o_voxel
importları lazy (yalnız trellis2 ortamında). Görüntü kodlayıcı DINOv3 (gated, HF
erişimi gerekir). Arka plan silme: yapılandırmadaki briaai/RMBG-2.0 gated ve ticari
değil → aynı mimarinin açık sürümü (ZhengPeng7/BiRefNet, MIT); saydam PNG gelirse
hiç çalışmaz.
"""
from __future__ import annotations

import os
from pathlib import Path

_MODEL = "microsoft/TRELLIS.2-4B"
_OPEN_REMBG = "ZhengPeng7/BiRefNet"


class Trellis2ImageEngine:
    def __init__(self) -> None:
        self._pipe = None

    def is_loaded(self) -> bool:
        return self._pipe is not None

    def load(self) -> None:
        if self._pipe is not None:
            return
        # expandable_segments (upstream örneğindeki ayar) WSL'de büyük modellerde PyTorch
        # ayırıcısını iç hatayla düşürüyor (CUDACachingAllocator handles_ assert) → kullanılmaz.
        os.environ.setdefault("ATTN_BACKEND", "xformers")
        os.environ.setdefault("SPARSE_ATTN_BACKEND", "xformers")
        from trellis2.pipelines import Trellis2ImageTo3DPipeline, rembg

        base = rembg.BiRefNet

        class _OpenBiRefNet(base):
            def __init__(self, model_name: str | None = None, **_kw) -> None:
                super().__init__(_OPEN_REMBG)

        rembg.BiRefNet = _OpenBiRefNet
        self._pipe = Trellis2ImageTo3DPipeline.from_pretrained(_MODEL)
        # Upstream varsayılanı low_vram: modeller RAM'de bekler, her aşamada GPU'ya taşınır
        # (~31 GB RAM/worker, ~5 dk). Tamamı GPU'da: tepe ~18 GB VRAM (3090'a sığar),
        # ~17 GB RAM, ~40 sn. 24 GB'tan küçük kartta TRELLIS2_LOW_VRAM=1.
        self._pipe.low_vram = os.getenv("TRELLIS2_LOW_VRAM", "0") == "1"
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

    def generate(self, image_path: str, garment_type: str, params: dict, out_path: Path) -> Path:
        self.load()
        import o_voxel
        from PIL import Image
        seed = params.get("seed")
        mesh = self._pipe.run(Image.open(image_path), seed=42 if seed is None else int(seed),
                              pipeline_type=str(params.get("pipeline_type", "1024_cascade")))[0]
        mesh.simplify(16777216)                   # nvdiffrast sınırı
        glb = o_voxel.postprocess.to_glb(
            vertices=mesh.vertices, faces=mesh.faces, attr_volume=mesh.attrs, coords=mesh.coords,
            attr_layout=mesh.layout, voxel_size=mesh.voxel_size,
            aabb=[[-0.5, -0.5, -0.5], [0.5, 0.5, 0.5]],
            decimation_target=int(params.get("decimation_target", 300000)),
            texture_size=int(params.get("texture_size", 2048)),
            # remesh yüzeyi kapatıp açık kenarları (kol/boyun ağzı) doldurabilir → varsayılan kapalı
            remesh=bool(params.get("remesh", False)), remesh_band=1, remesh_project=0, verbose=False)
        # Açık yüzeyli tek katman kumaş: tek taraflı malzemede arkası dönük yüzler (elbisenin
        # önü yer yer) görünmez → çift taraflı.
        mat = getattr(glb.visual, "material", None)
        if mat is not None and hasattr(mat, "doubleSided"):
            mat.doubleSided = True
        out_path.parent.mkdir(parents=True, exist_ok=True)
        glb.export(str(out_path))
        return out_path
