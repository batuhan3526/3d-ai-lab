"""
VideoMDM text → motion wrapper.

Wraps the VideoMDM generate.py sampling loop, exposing a simple
MotionGenerator class that can be loaded/unloaded by the Celery worker.

Real signatures (verified against VideoMDM_release source):

  create_model_and_diffusion(args, data) -> (MDM, SpacedDiffusion)
    args:  namespace with fields from args.json (arch, latent_dim, layers,
           cond_mask_prob, emb_trans_dec, dataset, noise_schedule,
           diffusion_steps, sigma_small, video_mdm, text_encoder_type, ...)
    data:  dataset loader (or None for text-only inference)

  load_saved_model(model, model_path, use_avg=False) -> model
    model_path: path to .pt checkpoint
    use_avg:    load 'model_avg' key if present (EMA weights)

  The sampling loop uses:
    diffusion.p_sample_loop(model, shape, clip_denoised, model_kwargs,
                            skip_timesteps, init_image, progress,
                            dump_steps, noise, const_noise)

  model_kwargs structure:
    {'y': {'text': [str,...], 'lengths': tensor, 'mask': tensor,
           'text_embed': tensor (pre-encoded), 'scale': tensor (CFG)}}

GPU note: CUDA_VISIBLE_DEVICES must be set to GPU 1 before import in worker.
"""
from __future__ import annotations

import json
import os
import types
from pathlib import Path

import numpy as np
from common.config import engines_dir

# Default checkpoint path; override with VIDEOMDM_CKPT env var.
_CKPT = os.environ.get(
    "VIDEOMDM_CKPT",
    str(
        engines_dir()
        / "VideoMDM_release/save/videomdm_ckpts"
        / "HUMANML3D_VIDEOMDM_ON_MVLIFT/model000600091.pt"
    ),
)

# VideoMDM checkout root; override with VIDEOMDM_DIR env var.
_REPO = os.environ.get(
    "VIDEOMDM_DIR",
    str(engines_dir() / "VideoMDM_release"),
)


def _build_args(ckpt_path: str, text: str, motion_length: float, guidance: float, seed: int) -> types.SimpleNamespace:
    """Build an args namespace from args.json next to the checkpoint.

    Merges saved model args with the runtime text/length/guidance overrides.
    """
    args_path = Path(ckpt_path).parent / "args.json"
    with open(args_path, "r") as f:
        saved = json.load(f)

    args = types.SimpleNamespace(**saved)

    # Runtime overrides
    args.model_path = ckpt_path
    args.text_prompt = text
    args.input_text = ""
    args.action_file = ""
    args.action_name = ""
    args.motion_length = motion_length
    args.guidance_param = guidance
    args.seed = seed
    args.num_samples = 1
    args.num_repetitions = 1
    args.batch_size = 1
    args.output_dir = ""
    args.unconstrained = False
    args.dont_use_ema = False

    # Fields required by create_model_and_diffusion that may not be in older checkpoints
    if not hasattr(args, "device"):
        args.device = 1  # GPU 1 (set by CUDA_VISIBLE_DEVICES in worker env)
    if not hasattr(args, "cuda"):
        args.cuda = True

    return args


class MotionGenerator:
    """Text → SMPL motion generator backed by VideoMDM.

    Usage::

        gen = MotionGenerator()
        out = gen.generate("a person walks forward", out_npy=Path("/tmp/motion.npy"))
        # results.npy is produced by this process and contains only numpy arrays;
        # allow_pickle=True is safe here because the file is a trusted local output.
        data = np.load(out, allow_pickle=True).item()
        # data['motion'].shape == (1, njoints, 3, nframes)  [xyz positions]
        # data['lengths'] == array([nframes])
        # data['text'] == ['a person walks forward']
    """

    def __init__(self) -> None:
        self._model = None
        self._diffusion = None
        self._args = None

    def is_loaded(self) -> bool:
        return self._model is not None

    def load(self, ckpt_path: str | None = None) -> None:
        if self._model is not None:
            return

        import sys

        if _REPO not in sys.path:
            sys.path.insert(0, _REPO)

        ckpt_path = ckpt_path or _CKPT

        from utils.fixseed import fixseed  # noqa: PLC0415
        from utils.model_util import (  # noqa: PLC0415
            create_model_and_diffusion,
            load_saved_model,
        )

        self._args = _build_args(ckpt_path, text="", motion_length=6.0, guidance=2.5, seed=10)
        fixseed(self._args.seed)

        # create_model_and_diffusion(args, data) — data=None for text-only
        model, diffusion = create_model_and_diffusion(self._args, data=None)

        # load_saved_model(model, model_path, use_avg=False)
        load_saved_model(model, ckpt_path, use_avg=not self._args.dont_use_ema)

        import torch  # noqa: PLC0415

        model.eval()
        # Use the device index 0 relative to CUDA_VISIBLE_DEVICES (which maps to GPU 1)
        model.to("cuda")
        self._model = model
        self._diffusion = diffusion

    def unload(self) -> None:
        if self._model is None:
            return
        del self._model
        self._model = None
        self._diffusion = None
        import torch  # noqa: PLC0415

        torch.cuda.empty_cache()

    def mem_report(self) -> dict:
        import torch  # noqa: PLC0415

        if torch.cuda.is_available():
            return {
                "loaded": self.is_loaded(),
                "reserved_mb": int(torch.cuda.memory_reserved() / 1_048_576),
                "allocated_mb": int(torch.cuda.memory_allocated() / 1_048_576),
            }
        return {"loaded": self.is_loaded(), "reserved_mb": 0, "allocated_mb": 0}

    def generate(
        self,
        text: str,
        out_npy: Path,
        motion_length: float = 6.0,
        guidance: float = 2.5,
        seed: int = 10,
        ckpt_path: str | None = None,
    ) -> Path:
        """Generate SMPL joint-position motion from a text prompt.

        Mirrors the generate.py main() sampling loop (lines ~88-196) but
        exposes a simple function API instead of CLI args.

        Args:
            text:          Text prompt, e.g. "a person walks forward turning."
            out_npy:       Output path for results.npy.
            motion_length: Duration in seconds (max 9.8 for HumanML3D).
            guidance:      Classifier-free guidance scale (default 2.5).
            seed:          Random seed.
            ckpt_path:     Override checkpoint path (uses _CKPT env default).

        Returns:
            Path to saved results.npy containing::

                {
                  'motion':          np.ndarray [1, njoints, 3, nframes],
                  'lengths':         np.ndarray [1],
                  'text':            ['<prompt>'],
                  'num_samples':     1,
                  'num_repetitions': 1,
                }
        """
        import sys  # noqa: PLC0415

        if _REPO not in sys.path:
            sys.path.insert(0, _REPO)

        import torch  # noqa: PLC0415
        from data_loaders.tensors import collate  # noqa: PLC0415
        from data_loaders.humanml.scripts.motion_process import recover_from_ric  # noqa: PLC0415
        from utils import dist_util  # noqa: PLC0415
        from utils.fixseed import fixseed  # noqa: PLC0415
        from utils.sampler_util import ClassifierFreeSampleModel  # noqa: PLC0415

        fixseed(seed)
        self.load(ckpt_path)

        args = _build_args(ckpt_path or _CKPT, text, motion_length, guidance, seed)

        # Dataset-specific constants (VideoMDM checkpoint uses video_mdm_synthetic_mvlift
        # which is HumanML3D-derived with 22 joints)
        fps = 20
        max_frames = 196
        n_frames = min(max_frames, int(motion_length * fps))
        n_joints = 22  # HumanML3D

        dist_util.setup_dist(0)  # relative to CUDA_VISIBLE_DEVICES

        model = self._model
        diffusion = self._diffusion

        # Wrap with CFG sampler if guidance != 1
        if guidance != 1:
            model = ClassifierFreeSampleModel(model)

        # Build model_kwargs from text prompt (no dataset loader needed)
        collate_args = [
            {"inp": torch.zeros(n_frames), "tokens": None, "lengths": n_frames, "text": text}
        ]
        _, model_kwargs = collate(collate_args)
        model_kwargs["y"] = {
            k: v.to(dist_util.dev()) if torch.is_tensor(v) else v
            for k, v in model_kwargs["y"].items()
        }

        # CFG scale
        if guidance != 1:
            model_kwargs["y"]["scale"] = (
                torch.ones(1, device=dist_util.dev()) * guidance
            )

        # Pre-encode text (avoids per-iteration encoding overhead)
        if "text" in model_kwargs["y"]:
            model_kwargs["y"]["text_embed"] = self._model.encode_text(
                model_kwargs["y"]["text"]
            )

        motion_shape = (1, model.njoints, model.nfeats, n_frames)

        # --- p_sample_loop (mirrors generate.py lines ~115-140) ---
        sample = diffusion.p_sample_loop(
            model,
            motion_shape,
            clip_denoised=False,
            model_kwargs=model_kwargs,
            skip_timesteps=0,
            init_image=None,
            progress=True,
            dump_steps=None,
            noise=None,
            const_noise=False,
        )

        # Recover XYZ positions from HumanML3D vector representation
        if self._model.data_rep == "hml_vec":
            n_joints_rep = int((sample.shape[1] + 1) // 12)
            sample = sample.cpu().permute(0, 2, 3, 1).float()
            # Need the dataset's inv_transform — load a minimal version
            # For inference without a full dataset loader, use a zero-mean identity
            # transform (data is already normalised in the checkpoint's dataset).
            # Full inv_transform requires dataset stats; see data_loaders/humanml_utils.py.
            # TODO: wire in t2m_dataset.inv_transform when dataset loader is available.
            sample = recover_from_ric(sample, n_joints_rep)
            sample = sample.view(-1, *sample.shape[2:]).permute(0, 2, 3, 1)
        else:
            # rot6d path: run rot2xyz
            rot2xyz_mask = model_kwargs["y"]["mask"].reshape(1, n_frames).bool()
            sample = self._model.rot2xyz(
                x=sample,
                mask=rot2xyz_mask,
                pose_rep=self._model.data_rep,
                glob=True,
                translation=True,
                jointstype="smpl",
                vertstrans=True,
                betas=None,
                beta=0,
                glob_rot=None,
                get_rotations_back=False,
            )

        all_motions = sample.cpu().numpy()          # (1, njoints, 3, nframes)
        all_lengths = model_kwargs["y"]["lengths"].cpu().numpy()  # (1,)

        out_npy = Path(out_npy)
        out_npy.parent.mkdir(parents=True, exist_ok=True)

        results = {
            "motion": all_motions,
            "text": [text],
            "lengths": all_lengths,
            "num_samples": 1,
            "num_repetitions": 1,
        }
        np.save(str(out_npy), results)
        return out_npy
