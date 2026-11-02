"""Idol image→3D adaptörü (speridlabs/idol, Apache-2.0).

Tek fotoğraftan 3D Gaussian splat (32k–1M Gaussian, ~7 GB VRAM, RTX 3090'da ~20-45 sn).
Uygulamanın geri kalanı (tasarım, decal, giydirme) mesh beklediği için splat'tan
vertex-renkli bir mesh de üretilir (splat_mesh.py); ham splat (standart 3DGS .ply) ve
renkli nokta bulutu projenin `idol/` klasörüne yazılır (Sonuçlar sayfasında görünür).

Kodlayıcılar: DINOv3 ViT-H+ (gated — HF erişimi gerekir) ve FLUX.2 VAE. Upstream config
VAE'yi gated FLUX.2-dev deposundan ister; aynı FLUX.2 VAE açık (Apache-2.0) FLUX.2-klein-4B
deposunda olduğu için oradan okunur (config'in kopyası `weights_open/` altında).
"""
from __future__ import annotations

import json
import os
from pathlib import Path

_OPEN_FLUX2_VAE = "black-forest-labs/FLUX.2-klein-4B"
_WEIGHT_FILES = ("denoiser", "decoder", "decoder_gs", "birefnet")


def _engine_root() -> Path:
    import idol
    return Path(idol.__file__).resolve().parent.parent


def _weights_dir() -> Path:
    """Upstream ağırlık klasörünün açık-VAE'li gölgesi: safetensors'lar symlink, config yamalı."""
    src = Path(os.getenv("IDOL_WEIGHTS", _engine_root() / "weights"))
    if not (src / "config.json").is_file():
        raise RuntimeError(f"Idol ağırlıkları yok: {src} (infra/scripts/engine.sh weights idol)")
    dst = src.parent / "weights_open"
    dst.mkdir(exist_ok=True)
    cfg = json.loads((src / "config.json").read_text())
    cfg["image_encoders"]["flux2_vae"] = os.getenv("IDOL_FLUX2_VAE", _OPEN_FLUX2_VAE)
    (dst / "config.json").write_text(json.dumps(cfg, indent=2))
    for name in _WEIGHT_FILES:
        link = dst / f"{name}.safetensors"
        if not link.exists():
            link.symlink_to(src / f"{name}.safetensors")
    return dst


class IdolImageEngine:
    def __init__(self) -> None:
        self._pipe = None

    def is_loaded(self) -> bool:
        return self._pipe is not None

    def load(self) -> None:
        if self._pipe is not None:
            return
        from idol import IdolPipeline
        # torch.compile ilk işte ~1 dk derler; IDOL_OPTIMIZE=0 ile kapatılabilir
        optimize = os.getenv("IDOL_OPTIMIZE", "1") != "0"
        pipe = IdolPipeline.from_pretrained(str(_weights_dir()), optimize=optimize)
        if optimize and os.getenv("IDOL_CUDNN_ATTN", "0") != "1":
            _keep_default_attention(pipe)
        self._pipe = pipe

    def unload(self) -> None:
        if self._pipe is None:
            return
        self._pipe = None
        import gc
        import torch
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

    def generate(self, image_path: str, params: dict, out_path: Path, progress=None) -> Path:
        """mesh.glb'yi out_path'e, splat/nokta bulutu/girdi görselini out_path.parent/'idol'a yazar."""
        import numpy as np
        import trimesh

        from idol_worker.splat_mesh import front_to_viewer, gaussian_colors, splat_to_mesh

        self.load()
        seed = params.get("seed")
        out = self._pipe(image_path, mode=str(params.get("mode", "real")),
                         seed=42 if seed is None else int(seed),
                         steps=int(params.get("steps", 50)),
                         cfg_strength=float(params.get("cfg_strength", 3.0)),
                         num_gaussians=int(params.get("num_gaussians", 524288)))
        if progress:
            progress("mesh", 75)

        extra = out_path.parent / "idol"
        extra.mkdir(parents=True, exist_ok=True)
        out.gaussian.save_ply(str(extra / "splat.ply"))
        out.preprocessed_image.save(extra / "input.png")
        (extra / "camera.json").write_text(json.dumps(out.camera, indent=2))

        g = out.gaussian
        xyz = g.xyz.detach().float().cpu().numpy()
        rgb = gaussian_colors(g.features_dc.detach().float().cpu().numpy().reshape(-1, 3))
        opacity = g.opacity.detach().float().cpu().numpy().reshape(-1)
        xyz = front_to_viewer(xyz, out.camera)

        verts, faces, colors = splat_to_mesh(
            xyz, rgb, opacity, resolution=int(params.get("mesh_resolution", 256)),
            min_opacity=float(params.get("min_opacity", 0.1)))
        mesh = trimesh.Trimesh(verts, faces, vertex_colors=colors, process=False)
        # marching-cubes voxel terracing → Taubin (shrink-free) smoothing
        trimesh.smoothing.filter_taubin(mesh, lamb=0.5, nu=-0.53,
                                        iterations=int(params.get("smooth_iterations", 10)))
        target = int(params.get("max_faces", 300000))
        if len(mesh.faces) > target:
            mesh = _decimate(mesh, target)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        mesh.export(out_path)

        vis = opacity >= float(params.get("min_opacity", 0.1))
        cloud = trimesh.PointCloud(xyz[vis], colors=(rgb[vis] * 255).astype(np.uint8))
        cloud.export(extra / "points.ply")
        return out_path


def _keep_default_attention(pipe) -> None:
    """Upstream's optimised sampling switches attention to cuDNN SDPA. On an RTX 3090 (sm_86,
    torch 2.6) that yields garbage (median opacity ~0.02, scattered blobs) — measured 2026-11-02.
    Keep the rest of the optimisation (torch.compile, batched CFG, TF32): ~32 s vs ~39 s eager
    at 25 steps. IDOL_CUDNN_ATTN=1 restores upstream behaviour (e.g. Hopper GPUs)."""
    import contextlib

    import torch

    @contextlib.contextmanager
    def tf32_only():
        old = torch.backends.cuda.matmul.allow_tf32
        torch.backends.cuda.matmul.allow_tf32 = True
        try:
            yield
        finally:
            torch.backends.cuda.matmul.allow_tf32 = old

    pipe._sampling_settings = tf32_only


def _decimate(mesh, target_faces: int):
    """open3d quadric decimation; vertex colours are carried over."""
    import numpy as np
    import open3d as o3d
    import trimesh

    m = o3d.geometry.TriangleMesh(o3d.utility.Vector3dVector(mesh.vertices.astype(np.float64)),
                                  o3d.utility.Vector3iVector(mesh.faces.astype(np.int32)))
    m.vertex_colors = o3d.utility.Vector3dVector(mesh.visual.vertex_colors[:, :3] / 255.0)
    m = m.simplify_quadric_decimation(target_number_of_triangles=target_faces)
    m.remove_unreferenced_vertices()
    cols = (np.asarray(m.vertex_colors) * 255).clip(0, 255).astype(np.uint8)
    return trimesh.Trimesh(np.asarray(m.vertices), np.asarray(m.triangles), vertex_colors=cols, process=False)
