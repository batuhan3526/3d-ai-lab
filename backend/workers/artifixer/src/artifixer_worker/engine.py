"""ArtiFixer (SIGGRAPH 2026, Apache-2.0) motor adaptörü — 3D tarama iyileştirme.

İki aşama, ikisi de subprocess (worker artifixer conda env'inde koşar):
  prepare  — COLMAP sahnesi → 3DGRUT rekonstrüksiyon + MoGe ölçek + caption
             (data_processing.prepare_colmap_artifixer_inputs; GPU ister, uzun)
  fix      — hazırlanmış sahne → ArtiFixer düzeltilmiş kareler
             (artifixer_worker.run_inference_offload; 3090'da CPU-offload'lu)

Checkpoint: <ENGINES_DIR>/ArtiFixer/checkpoints/artifixer-14b.pt (67.6GB, bf16'da ~28GB).
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from common.config import engines_dir

ARTIFIXER_REPO = Path(os.getenv("ARTIFIXER_REPO",
                                str(engines_dir() / "ArtiFixer")))
CHECKPOINT = Path(os.getenv("ARTIFIXER_CKPT",
                            str(ARTIFIXER_REPO / "checkpoints" / "artifixer-14b.pt")))
_WORKER_SRC = Path(__file__).resolve().parents[1]


def _env() -> dict:
    env = os.environ.copy()
    # model_eval + artifixer_worker importları için repo ve worker src PYTHONPATH'te.
    env["PYTHONPATH"] = f"{ARTIFIXER_REPO}:{_WORKER_SRC}:" + env.get("PYTHONPATH", "")
    return env


class ArtiFixerEngine:
    """Sözleşme: is_loaded/load/unload/mem_report + prepare/fix."""

    def __init__(self) -> None:
        self._loaded = False

    def is_loaded(self) -> bool:
        return self._loaded

    def load(self) -> None:
        if not CHECKPOINT.exists():
            raise FileNotFoundError(f"ArtiFixer checkpoint yok: {CHECKPOINT}")
        self._loaded = True

    def unload(self) -> None:
        self._loaded = False

    def mem_report(self) -> dict:
        return {"loaded": self._loaded, "reserved_mb": 0, "allocated_mb": 0}

    def prepare(self, colmap_dir: Path, output_root: Path,
                selected_images_file: Path | None = None,
                trajectory_path: Path | None = None) -> Path:
        """COLMAP sahnesi → ArtiFixer girdileri (split.json + 3DGRUT render'ları)."""
        cmd = [sys.executable, "-m", "data_processing.prepare_colmap_artifixer_inputs",
               "--colmap_dir", str(colmap_dir), "--output_root", str(output_root)]
        if selected_images_file:
            cmd += ["--selected_image_names_file", str(selected_images_file)]
        if trajectory_path:
            cmd += ["--trajectory_path", str(trajectory_path)]
        proc = subprocess.run(cmd, cwd=str(ARTIFIXER_REPO), env=_env(),
                              capture_output=True, text=True, timeout=4 * 3600)
        if proc.returncode != 0:
            tail = (proc.stderr or proc.stdout or "")[-2000:]
            raise RuntimeError(f"artifixer prepare çıkış kodu {proc.returncode}: {tail}")
        split = Path(output_root) / "split.json"
        if not split.exists():
            raise RuntimeError(f"prepare split.json üretmedi: {output_root}")
        return split

    def fix(self, split_path: Path, save_dir: Path,
            render_trajectory: str = "all_frames",
            num_inference_steps: int = 4) -> Path:
        """Hazırlanmış sahne → ArtiFixer düzeltilmiş kare PNG'leri + mp4."""
        self.load()
        save_dir = Path(save_dir)
        save_dir.mkdir(parents=True, exist_ok=True)
        cmd = [sys.executable, "-m", "artifixer_worker.run_inference_offload",
               "--evalset", "reconstructed_colmap",
               "--checkpoint_pt", str(CHECKPOINT),
               "--save_dir", str(save_dir),
               "--split_path", str(split_path),
               "--render_trajectory", render_trajectory,
               "--num_inference_steps", str(num_inference_steps)]
        proc = subprocess.run(cmd, cwd=str(ARTIFIXER_REPO), env=_env(),
                              capture_output=True, text=True, timeout=6 * 3600)
        if proc.returncode != 0:
            tail = (proc.stderr or proc.stdout or "")[-2000:]
            raise RuntimeError(f"artifixer fix çıkış kodu {proc.returncode}: {tail}")

        # Gerçek doğrulama: en az bir pred karesi (png) veya mp4 üretilmiş olmalı.
        preds = list(save_dir.rglob("pred/*.png")) or list(save_dir.rglob("*.mp4"))
        if not preds:
            raise RuntimeError(f"ArtiFixer çıktı üretmedi: {save_dir}")
        return save_dir
