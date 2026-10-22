# Copyright (c) Clothing App. All rights reserved.
#
# MeshFlowRefineEngine — VAE encode→decode path (topology refinement, no DINOv3).
# Based on inference_vae.py main() logic wrapped into the engine adapter contract.
#
# NOTE: `select_latents_by_mask` is defined at module level in inference_vae.py
# (NOT in meshflow.pipelines.utils — plan had wrong import path; fixed here).

from __future__ import annotations

import os
from pathlib import Path

import torch
from common.config import engines_dir
from omegaconf import OmegaConf

# Checkpoint directory — override with MESHFLOW_CKPT env var.
# Must contain config.yaml and model.pth (matching inference_vae.py bundle layout).
_CKPT_DIR = os.environ.get(
    "MESHFLOW_CKPT",
    str(engines_dir() / "meshflow" / "ckpt" / "meshflow"),
)


class MeshFlowRefineEngine:
    """
    Engine adapter: MeshFlow VAE encode→decode refine path.

    Contract: is_loaded / load / unload / mem_report / generate(mesh_in, garment_type, params, out_path)->Path
    Weights are gated (facebook/meshflow) — load() will raise until ckpt arrives.
    """

    def __init__(self) -> None:
        self._model = None
        self._data_cfg = None
        self._device: torch.device | None = None

    # ------------------------------------------------------------------
    # Adapter contract
    # ------------------------------------------------------------------

    def is_loaded(self) -> bool:
        return self._model is not None

    def load(self) -> None:
        if self._model is not None:
            return
        from meshflow.models.meshflow_vae import build_mesh_model

        root = Path(_CKPT_DIR)
        config_path = root / "config.yaml"
        ckpt_path = root / "model.pth"
        if not config_path.is_file():
            raise FileNotFoundError(f"MeshFlow config not found: {config_path}")
        if not ckpt_path.is_file():
            raise FileNotFoundError(
                f"MeshFlow checkpoint not found: {ckpt_path}  "
                "(gated — pending facebook/meshflow download)"
            )

        cfg = OmegaConf.load(config_path)
        self._data_cfg = cfg.data
        mesh_cfg = OmegaConf.to_container(cfg.system.mesh_model, resolve=True)
        mesh_cfg["pretrained_model_name_or_path"] = str(ckpt_path)

        self._device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        self._model = build_mesh_model(mesh_cfg).to(self._device).eval()

    def unload(self) -> None:
        if self._model is None:
            return
        del self._model
        self._model = None
        self._data_cfg = None
        if torch.cuda.is_available():
            torch.cuda.empty_cache()

    def mem_report(self) -> dict:
        base = {"loaded": self.is_loaded(), "reserved_mb": 0, "allocated_mb": 0}
        if torch.cuda.is_available():
            base["reserved_mb"] = int(torch.cuda.memory_reserved() / 1_048_576)
            base["allocated_mb"] = int(torch.cuda.memory_allocated() / 1_048_576)
        return base

    def generate(
        self,
        mesh_in: str,
        garment_type: str,
        params: dict,
        out_path: Path,
    ) -> Path:
        """
        Refine a mesh via MeshFlow VAE encode→decode.

        Args:
            mesh_in: Path to input mesh (.glb / .ply / .obj / .stl).
            garment_type: Unused by this engine (kept for contract compat).
            params: Engine params from registry (sample_posterior, dynamic_latent, dtype).
            out_path: Destination GLB path.

        Returns:
            out_path after writing.
        """
        self.load()

        # select_latents_by_mask lives in inference_vae.py (module-level function),
        # NOT in meshflow.pipelines.utils — verified by grep of the repo.
        from inference_vae import select_latents_by_mask
        from meshflow.utils.mesh import Mesh

        sample_posterior: bool = bool(params.get("sample_posterior", True))
        dynamic_latent: bool = bool(params.get("dynamic_latent", True))
        dtype_str: str = params.get("dtype", "fp16")
        dtype_map = {"fp16": torch.float16, "bf16": torch.bfloat16, "fp32": torch.float32}
        dtype = dtype_map.get(dtype_str, torch.float16)

        n_verts = int(self._data_cfg.n_verts)
        mesh = Mesh.load_mesh(
            str(mesh_in),
            normalize=True,
            normalize_by="bsphere",
            obj_scale=2.0,
            preprocess=True,
        )
        topo = mesh.build_topology(
            topology_feats_type=list(self._data_cfg.topology_feats_type),
            n_verts=n_verts,
            max_degree=int(self._data_cfg.max_degree),
        )
        batch = {
            k: (v.unsqueeze(0).to(self._device) if isinstance(v, torch.Tensor) else v)
            for k, v in topo.items()
        }

        with torch.no_grad(), torch.autocast(device_type=self._device.type, dtype=dtype):
            feats = self._model.collect_input(batch)
            enc = self._model.encode(
                feats,
                batch["padded_verts"],
                sample_posterior=sample_posterior,
            )
            z = enc["z"]
            if dynamic_latent:
                z = select_latents_by_mask(
                    z,
                    batch["verts_mask"],
                    downsample_ratio=self._model.encoder.downsample_ratio,
                )
            dec = self._model.decode(z)
            out_mesh = self._model.extract_mesh(dec)[0]

        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_mesh.to_trimesh().export(str(out_path))
        return out_path
