"""Hi3D v1.0 geometri inceltme adaptörü (hi3d-official/Hi3Dv1.0, Sparc3D tabanlı; Hi3D Open License 1.0).

Mevcut kaba mesh + aynı nesnenin referans görseli → seyrek akış (512³ → 1024³ → 1536³ geçişleri)
→ yüksek çözünürlüklü geometri. Yalnız geometri: doku/renk yok (sonra UltraTex ile dokulanır).
Upstream çıktıyı merkezler ve birim yarıçapa ölçekler → kaynağın kutusuna geri oturtulur, yoksa
manken/ölçü hizası bozulur. Upstream 1M yüze sadeleştiriyor; görüntüleyici ve UV açma (xatlas)
için `faces` hedefine indirilir.

Upstream her sınır halkasını (10 000 kenara kadar) kulak kırpmayla kapatıyor: kıyafette yaka,
kol ve etek ucu kapanıp kapalı bir katıya dönüyor (manken içine giremez). `keep_openings`
açıkken uzun halkalar (açıklıklar) açık kalır, kısa olanlar (iğne deliği, ince kumaşta yırtık)
doldurulur.
"""
from __future__ import annotations

import os
from pathlib import Path

ENGINE_DIR = Path(os.getenv("HI3D_DIR", Path(__file__).resolve().parents[5] / "engines" / "Hi3D"))


def fit_to_bounds(verts, ref_verts):
    """`verts`i `ref_verts`in eksen-hizalı kutusuna oturt: kutu merkezleri çakışır, en uzun kenar
    eşitlenir (tekdüze ölçek, oran korunur)."""
    import numpy as np
    v, r = np.asarray(verts, float), np.asarray(ref_verts, float)
    vmin, vmax, rmin, rmax = v.min(0), v.max(0), r.min(0), r.max(0)
    scale = (rmax - rmin).max() / max((vmax - vmin).max(), 1e-12)
    return (v - (vmin + vmax) / 2) * scale + (rmin + rmax) / 2


def openings(lengths: list[int], resolution: int, share: float = 0.1) -> set[int]:
    """Açık kalacak sınır halkalarının indeksleri. Yaka/kol/etek ucu nesnenin en uzun halkaları:
    en uzunun `share`'inden ve 1024³'te 64 kenardan (≈ boyun %6'sı) uzun olan her halka açıklık
    sayılır. Kol ağzı elbise eteğinin ~%25'i → açık kalır; yırtık ve iğne delikleri dolar."""
    if not lengths:
        return set()
    floor = max(share * max(lengths), resolution // 16)
    return {i for i, n in enumerate(lengths) if n >= floor}


class Hi3DEngine:
    def __init__(self) -> None:
        self._pipe = None

    def is_loaded(self) -> bool:
        return self._pipe is not None

    def load(self) -> None:
        if self._pipe is not None:
            return
        from sparc3d import Sparc3DPipeline
        weights = ENGINE_DIR / "weights"
        self._pipe = Sparc3DPipeline.from_pretrained(
            str(weights) if (weights / "model_index.json").exists() else "hi3d-official/Hi3Dv1.0",
        ).to("cuda")

    def unload(self) -> None:
        """İki transformer + kodlayıcılar ~9 GB; ardından gelen UltraTex iki kartı da dolu ister."""
        import gc

        import torch
        self._pipe = None
        gc.collect()
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

    def refine(self, mesh_path: str, ref_path: str, params: dict, out_path: Path) -> Path:
        """mesh_path'i ref_path görseline göre incelt → out_path (dokusuz GLB, kaynak ölçeğinde)."""
        import pyfqmr
        import sparc3d.sparcubes.fill_hole as fh
        import trimesh
        from PIL import Image

        self.load()
        src = trimesh.load(mesh_path, force="mesh", process=False)
        resolution = int(params.get("resolution", 1024))
        orig_loops = fh._boundary_loops          # yalnız doldurulacak halkaları seçmek için kullanılır
        if params.get("keep_openings", True):
            def fill_only_small(boundary):
                loops = orig_loops(boundary)
                keep = openings([len(lp) for lp in loops], resolution)
                return [lp for i, lp in enumerate(loops) if i not in keep]
            fh._boundary_loops = fill_only_small
        try:
            res = self._pipe(Image.open(ref_path), src, resolution=resolution,
                             num_inference_steps=int(params.get("steps", 25)),
                             seed=int(params.get("seed") or 0))
        finally:
            fh._boundary_loops = orig_loops
            self.unload()
        mesh = res.mesh
        target = int(params.get("faces", 200_000))
        if len(mesh.faces) > target:
            s = pyfqmr.Simplify()
            s.setMesh(mesh.vertices, mesh.faces)
            s.simplify_mesh(target_count=target, aggressiveness=7, preserve_border=True, verbose=False)
            v, f, _ = s.getMesh()
            mesh = trimesh.Trimesh(v, f, process=False)
        out = trimesh.Trimesh(fit_to_bounds(mesh.vertices, src.vertices), mesh.faces, process=False)
        out.visual = trimesh.visual.TextureVisuals(material=trimesh.visual.material.PBRMaterial(
            baseColorFactor=[200, 200, 200, 255], doubleSided=True, metallicFactor=0.0, roughnessFactor=0.8))
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out.export(str(out_path))
        return out_path
