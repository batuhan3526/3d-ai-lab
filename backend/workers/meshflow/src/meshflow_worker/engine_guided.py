# Copyright (c) Clothing App. All rights reserved.
#
# MeshFlowGuidedEngine — MeshFlowPipeline.run with optional reference image.
# DINOv3 visual encoder loads LAZILY on first call that provides an image;
# zero-cond path works without DINOv3 weights.
#
# Weights required (both gated/pending):
#   - facebook/meshflow  → MESHFLOW_CKPT/config.yaml + model.pth
#   - DINOv3 vitl16     → loaded via build_dinov3_encoder inside MeshFlowPipeline
#                         on first image-conditioned call only.

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from common.config import engines_dir

_CKPT_DIR = os.environ.get(
    "MESHFLOW_CKPT",
    str(engines_dir() / "meshflow" / "ckpt" / "meshflow"),
)


class MeshFlowGuidedEngine:
    """
    Engine adapter: MeshFlowPipeline DiT flow-matching with optional image guidance.

    Contract: is_loaded / load / unload / mem_report / generate(mesh_in, ref_image, params, out_path)->Path

    DINOv3 visual encoder is deferred inside MeshFlowPipeline._ensure_visual_encoder()
    and loads only when an image is supplied. DO NOT download DINOv3 until Meta
    access is granted.
    """

    def __init__(self) -> None:
        self._pipe = None

    # ------------------------------------------------------------------
    # Adapter contract
    # ------------------------------------------------------------------

    def is_loaded(self) -> bool:
        return self._pipe is not None

    def load(self) -> None:
        if self._pipe is not None:
            return
        from meshflow.pipelines import MeshFlowPipeline

        root = Path(_CKPT_DIR)
        if not (root / "config.yaml").is_file():
            raise FileNotFoundError(
                f"MeshFlow config not found: {root / 'config.yaml'}"
            )
        if not (root / "model.pth").is_file():
            raise FileNotFoundError(
                f"MeshFlow checkpoint not found: {root / 'model.pth'}  "
                "(gated — pending facebook/meshflow download)"
            )

        # from_pretrained defers DINOv3 loading — safe to call without its weights.
        self._pipe = MeshFlowPipeline.from_pretrained(
            str(root),
            device="cuda",
            dtype="fp16",
        )

    def unload(self) -> None:
        if self._pipe is None:
            return
        del self._pipe
        self._pipe = None
        try:
            import torch
            torch.cuda.empty_cache()
        except Exception:
            pass

    def mem_report(self) -> dict:
        base = {"loaded": self.is_loaded(), "reserved_mb": 0, "allocated_mb": 0}
        try:
            import torch
            if torch.cuda.is_available():
                base["reserved_mb"] = int(torch.cuda.memory_reserved() / 1_048_576)
                base["allocated_mb"] = int(torch.cuda.memory_allocated() / 1_048_576)
        except Exception:
            pass
        return base

    def generate(
        self,
        mesh_in: str,
        ref_image: Optional[str],
        params: dict,
        out_path: Path,
    ) -> Path:
        """
        Run guided mesh refinement via MeshFlowPipeline.

        Args:
            mesh_in: Input mesh path (str, passed to pipeline.run as-is).
            ref_image: Optional reference image path; when None, zero visual cond
                       is used (DINOv3 NOT loaded in that case).
            params: Engine params (steps, guidance_scale, seed, preprocess_image).
            out_path: Destination GLB path.

        Returns:
            out_path after writing.

        PENDING: ref_image != None path triggers DINOv3 load via
            MeshFlowPipeline._ensure_visual_encoder(). DINOv3 weights are
            gated (Meta); that branch will raise until weights arrive.
        """
        self.load()

        pil_img = None
        if ref_image is not None:
            from PIL import Image
            pil_img = Image.open(ref_image).convert("RGB")

        # MeshFlowPipeline.run() signature (verified against pipeline source):
        #   run(mesh, image=None, steps=None, guidance_scale=None, seed=42,
        #       preprocess_image=True, return_latent=False, disable_prog=False, num_verts=None)
        # Returns Mesh (or (Mesh, latents) when return_latent=True).
        out_mesh = self._pipe.run(
            mesh_in,
            image=pil_img,
            steps=params.get("steps"),            # None → pipeline default (28)
            guidance_scale=params.get("guidance_scale"),  # None → pipeline default (2.5)
            seed=int(params.get("seed", 42)),
            preprocess_image=bool(params.get("preprocess_image", True)),
        )

        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_mesh.to_trimesh().export(str(out_path))
        return out_path
