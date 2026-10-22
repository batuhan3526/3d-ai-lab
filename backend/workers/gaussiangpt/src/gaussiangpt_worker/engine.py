"""GaussianGPT (ECCV 2026, MIT) motor adaptörü — otoregresif 3DGS sahne üretimi.

generate_chunks.py (Hydra CLI) subprocess ile çağrılır: GPT'den token örnekle →
VQ-VAE ile Gaussian'lara çöz → orbit GIF render + .pt payload dump. Ardından
scripts/convert_pt_to_ply.py ile INRIA .ply'a çevrilir (harici viewer uyumu).

Sahne-seviyesi checkpoint'ler (3D-FRONT iç mekan). Obje-seviyesi ckpt beklemede
(README: 2026-07-13) — çıkınca aynı adaptör GAUSSIANGPT_GPT/VQVAE env'leriyle kullanılır.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from common.config import engines_dir

GAUSSIANGPT_REPO = Path(os.getenv("GAUSSIANGPT_REPO",
                                  str(engines_dir() / "GaussianGPT")))
GPT_CKPT = Path(os.getenv("GAUSSIANGPT_GPT",
                          str(GAUSSIANGPT_REPO / "checkpoints" / "gpt_vfront.ckpt")))
VQVAE_CKPT = Path(os.getenv("GAUSSIANGPT_VQVAE",
                            str(GAUSSIANGPT_REPO / "checkpoints" / "vqvae_vfront.ckpt")))


class GaussianGPTEngine:
    """Sözleşme: is_loaded/load/unload/mem_report/generate(...)->Path."""

    def __init__(self) -> None:
        self._loaded = False

    def is_loaded(self) -> bool:
        return self._loaded

    def load(self) -> None:
        for ckpt in (GPT_CKPT, VQVAE_CKPT):
            if not ckpt.exists():
                raise FileNotFoundError(f"GaussianGPT checkpoint yok: {ckpt}")
        self._loaded = True

    def unload(self) -> None:
        self._loaded = False

    def mem_report(self) -> dict:
        return {"loaded": self._loaded, "reserved_mb": 0, "allocated_mb": 0}

    def generate(
        self,
        out_dir: Path,
        num_samples: int = 1,
        temperature: float = 1.0,
        top_k: int | None = None,
        top_p: float | None = None,
        seed: int | None = None,
    ) -> Path:
        """Koşulsuz sahne chunk üretimi → out_dir (gif + .pt + .ply)."""
        self.load()
        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)

        overrides = [
            f"checkpoint={GPT_CKPT}",
            f"vqvae_checkpoint={VQVAE_CKPT}",
            f"num_samples={num_samples}",
            "batch_size=1",
            f"temperature={temperature}",
            "store_samples=true",
            "render_gifs=true",
            f"output_dir={out_dir}",
        ]
        if top_k is not None:
            overrides.append(f"top_k={top_k}")
        if top_p is not None:
            overrides.append(f"top_p={top_p}")
        if seed is not None:
            overrides.append(f"seed={seed}")

        proc = subprocess.run(
            [sys.executable, str(GAUSSIANGPT_REPO / "generate_chunks.py"), *overrides],
            cwd=str(GAUSSIANGPT_REPO), capture_output=True, text=True, timeout=3600,
        )
        if proc.returncode != 0:
            tail = (proc.stderr or proc.stdout or "")[-2000:]
            raise RuntimeError(f"generate_chunks çıkış kodu {proc.returncode}: {tail}")

        # .pt payload'ları .ply'a çevir (INRIA formatı — harici 3DGS viewer'lar için).
        pts = sorted(out_dir.rglob("*.pt"))
        for pt in pts:
            ply = pt.with_suffix(".ply")
            conv = subprocess.run(
                [sys.executable, str(GAUSSIANGPT_REPO / "scripts" / "convert_pt_to_ply.py"),
                 "--input", str(pt), "--output", str(ply)],
                cwd=str(GAUSSIANGPT_REPO), capture_output=True, text=True, timeout=600,
            )
            if conv.returncode != 0:
                # Dönüşüm başarısızlığı işi öldürmez; .pt yine de duruyor.
                print(f"convert_pt_to_ply uyarı ({pt.name}): {(conv.stderr or '')[-500:]}")

        # Gerçek doğrulama: en az bir örnek (.pt) veya render (.gif) üretilmiş olmalı.
        gifs = sorted(out_dir.rglob("*.gif"))
        if not pts and not gifs:
            raise RuntimeError(f"GaussianGPT çıktı üretmedi: {out_dir}")
        return out_dir
