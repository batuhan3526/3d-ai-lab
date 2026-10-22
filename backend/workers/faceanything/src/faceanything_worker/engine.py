"""FaceAnything (ECCV 2026) motor adaptörü — 4D yüz rekonstrüksiyonu + yoğun takip.

Repo CLI'ı (run_inference.py) subprocess ile çağrılır; worker süreci FaceAnything
conda env'inde koştuğundan sys.executable doğru python'dur. Model ağır (15GB ckpt)
ve CLI kendi yaşam döngüsünü yönettiği için is_loaded/load bellek-içi model tutmaz.

⚠ Lisans: CC BY-NC 4.0 — TİCARİ KULLANIM YASAK (registry: commercial_use=False).
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from common.config import engines_dir

FACEANYTHING_REPO = Path(os.getenv("FACEANYTHING_REPO",
                                   str(engines_dir() / "FaceAnything")))
CHECKPOINT = Path(os.getenv("FACEANYTHING_CKPT",
                            str(FACEANYTHING_REPO / "checkpoints" / "checkpoint.pt")))


class FaceAnythingEngine:
    """Sözleşme: is_loaded/load/unload/mem_report/generate(...)->Path."""

    def __init__(self) -> None:
        self._loaded = False

    def is_loaded(self) -> bool:
        return self._loaded

    def load(self) -> None:
        # Model subprocess içinde yüklenir; burada yalnız ön koşullar doğrulanır.
        if not CHECKPOINT.exists():
            raise FileNotFoundError(f"FaceAnything checkpoint yok: {CHECKPOINT}")
        self._loaded = True

    def unload(self) -> None:
        self._loaded = False

    def mem_report(self) -> dict:
        # Subprocess modeli işi bitince bırakır; kalıcı VRAM tutulmaz.
        return {"loaded": self._loaded, "reserved_mb": 0, "allocated_mb": 0}

    def generate(
        self,
        input_path: Path,
        out_dir: Path,
        outputs: str = "pointcloud,canonical,grandtour,ply",
        process_mode: str = "all-at-once",
        process_res: int = 504,
        max_frames: int | None = None,
        log_cb=None,
    ) -> Path:
        """input (video/klasör/tek foto) → out_dir altında videolar + ply'ler.

        Döner: out_dir (içerik: videos/*.mp4, ply/geometry/*.ply, cameras.npz...).
        """
        self.load()
        input_path = Path(input_path)
        if not input_path.exists():
            raise FileNotFoundError(f"girdi yok: {input_path}")
        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)

        cmd = [
            sys.executable, str(FACEANYTHING_REPO / "run_inference.py"),
            "--input", str(input_path),
            "--output", str(out_dir),
            "--outputs", outputs,
            "--process-mode", process_mode,
            "--process-res", str(process_res),
            "--checkpoint", str(CHECKPOINT),
        ]
        if max_frames:
            cmd += ["--max-frames", str(max_frames)]

        proc = subprocess.run(
            cmd, cwd=str(FACEANYTHING_REPO),
            capture_output=True, text=True, timeout=3600,
        )
        if proc.returncode != 0:
            tail = (proc.stderr or proc.stdout or "")[-2000:]
            raise RuntimeError(f"FaceAnything çıkış kodu {proc.returncode}: {tail}")

        # Gerçek doğrulama (200 ≠ çalışıyor): en az bir video VE ply üretilmiş olmalı.
        videos = list((out_dir / "videos").glob("*.mp4"))
        plys = list((out_dir / "ply").rglob("*.ply"))
        if not videos and not plys:
            raise RuntimeError(f"FaceAnything çıktı üretmedi: {out_dir}")
        return out_dir
