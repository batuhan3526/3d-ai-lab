"""WorldTracingEngine — adapter for the World Tracing image→3D model.

Two mesh modes:
  * ``poisson`` (default): fast, textureless Poisson surface reconstruction.
  * ``trellis2``: textured GLB via the TRELLIS.2 pipeline (requires
    microsoft/TRELLIS.2 clone + weights — PENDING gated download).

Satisfies the engine adapter contract:
  is_loaded() / load() / unload() / mem_report() / generate(...) -> Path
"""
from __future__ import annotations

import os
from pathlib import Path

import numpy as np
from common.config import engines_dir

# Object model: config "r75b" (architecture). Checkpoint already downloaded locally
# (haoz19/object-model-6layer) — point to the local .pt to AVOID re-downloading ~6GB
# to the HF cache (disk-tight). Override with WORLDTRACING_CKPT.
_CKPT_NAME = "r75b"
_CKPT_PATH = os.environ.get(
    "WORLDTRACING_CKPT",
    str(engines_dir() / "world-tracing/checkpoints/object-6layer/model.pt"),
)


class WorldTracingEngine:
    def __init__(self) -> None:
        self._model = None
        self._cfg: dict | None = None
        self._trellis2 = None
        self._device = None

    # ------------------------------------------------------------------
    # Adapter contract
    # ------------------------------------------------------------------

    def is_loaded(self) -> bool:
        return self._model is not None

    def load(self) -> None:
        """Load the World Tracing checkpoint.  Downloads from HF on first run
        (haoz19/object-model-6layer — gated; requires HF token + approval).
        """
        if self._model is not None:
            return
        import torch
        from wt.checkpoint import build_model_and_load_ckpt

        device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        # build_model_and_load_ckpt(config_name, ckpt_path, device) -> (model, cfg)
        # Use the LOCAL .pt if present (avoids HF re-download); else fall back to config name.
        ckpt = _CKPT_PATH if Path(_CKPT_PATH).is_file() else _CKPT_NAME
        self._model, self._cfg = build_model_and_load_ckpt(_CKPT_NAME, ckpt, device)
        self._device = device

    def unload(self) -> None:
        if self._model is None:
            return
        del self._model
        self._model = None
        self._trellis2 = None
        try:
            import torch
            torch.cuda.empty_cache()
        except Exception:
            pass

    def mem_report(self) -> dict:
        try:
            import torch
            if torch.cuda.is_available():
                return {
                    "loaded": self.is_loaded(),
                    "reserved_mb": int(torch.cuda.memory_reserved() / 1048576),
                    "allocated_mb": int(torch.cuda.memory_allocated() / 1048576),
                }
        except Exception:
            pass
        return {"loaded": self.is_loaded(), "reserved_mb": 0, "allocated_mb": 0}

    def generate(self, image_path: str, garment_type: str, params: dict, out_path: Path) -> Path:
        """image → GLB.

        Args:
            image_path: path to the input RGBA (or RGB) image.
            garment_type: e.g. ``"tshirt"`` (informational, not used yet).
            params: resolved engine params (from ``resolve_engine_params``).
                Relevant keys: ``mode``, ``poisson_depth``, ``seed``,
                ``texture_size``.
            out_path: destination ``.glb``.
        """
        self.load()
        mode = params.get("mode", "poisson")
        rgba, xyz_np, mask_np = self._infer_cloud(image_path)
        if mode == "trellis2":
            return self._to_glb_trellis2(rgba, xyz_np, mask_np, params, out_path)
        # --- poisson path (textureless, fast) ---
        from wt.textured_mesh import aggregate_camera_cloud
        from worldtracing_worker.cloud_to_mesh import points_to_glb

        cloud = aggregate_camera_cloud(xyz_np, mask_np)
        return points_to_glb(cloud, out_path, depth=params.get("poisson_depth", 8))

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _infer_cloud(self, image_path: str):
        """Run the diffusion model; return (rgba_uint8, xyz_LHWC, mask_LHW)."""
        import torch
        from wt.data import load_rgba_image, preprocess_rgba_for_model
        from wt.inference import inference_diffusion, _bypass_activation_checkpointing

        rgba = load_rgba_image(image_path, auto_alpha=True)

        # _cfg keys: "image_size", "model_kwargs" (contains "num_layers"), "inference_kwargs"
        rgb_t, mask_t, intr_t = preprocess_rgba_for_model(
            rgba,
            image_size=self._cfg["image_size"],
            num_layers=self._cfg["model_kwargs"]["num_layers"],
            bg_color=(128, 128, 128),
        )

        with torch.no_grad(), _bypass_activation_checkpointing(self._model):
            xyz, msk, _ = inference_diffusion(
                self._model,
                rgb_t.to(self._device),
                gt_mask=mask_t.to(self._device),
                use_gt_mask=True,
                intrinsics=intr_t.to(self._device),
                invalid_fill_mode="noise",
                **self._cfg["inference_kwargs"],
            )
        # xyz: [B, L, H, W, 3]  →  [L, H, W, 3] (B=1)
        # msk: [B, L, H, W]     →  [L, H, W]
        return (
            rgba,
            xyz[0].float().cpu().numpy(),
            msk[0].cpu().numpy().astype(bool),
        )

    def _to_glb_trellis2(
        self, rgba: np.ndarray, xyz_np: np.ndarray, mask_np: np.ndarray,
        params: dict, out_path: Path,
    ) -> Path:
        """TRELLIS.2 textured-mesh path (requires gated weights + TRELLIS.2 clone).

        PENDING: haoz19/* weights + microsoft/TRELLIS.2 not yet downloaded.
        This code path is written but cannot run until the controller completes
        Task 1.7 (TRELLIS.2 clone + weight download).
        """
        from PIL import Image
        from wt.textured_mesh import (
            load_trellis2_pipeline,
            compute_canonical_transform,
            aggregate_camera_cloud,
            v4_ray_fill,
            inject_coords_into_trellis2,
            save_mesh_glb,
        )

        if self._trellis2 is None:
            self._trellis2 = load_trellis2_pipeline(device=self._device)

        cloud = aggregate_camera_cloud(xyz_np, mask_np)
        tf = compute_canonical_transform(cloud, half_target=0.45)

        # v4_ray_fill(xyz_np, mask_np, transform_fn, res, ray_steps, seed) -> (coords, ...)
        coords, _ = v4_ray_fill(
            xyz_np, mask_np, tf.apply,
            res=64, ray_steps=4, seed=params.get("seed", 42),
        )

        meshes = inject_coords_into_trellis2(
            self._trellis2,
            Image.fromarray(rgba, "RGBA"),
            coords,
            seed=params.get("seed", 42),
            pipeline_type="1024_cascade",
            preprocess_image=False,
        )

        out_path = Path(out_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        save_mesh_glb(
            str(out_path), meshes[0],
            texture_size=params.get("texture_size", 2048),
        )
        return out_path
