"""Medya dönüştürme route'ları — Task A: turntable webm → mp4 (ffmpeg).

`POST /convert/video`: tarayıcının `MediaRecorder` ile ürettiği turntable
kaydı (webm/VP8/VP9) yüklenir; ffmpeg ile H.264/yuv420p mp4'e çevrilip mp4
ikilisi indirme olarak döner. Amaç: webm'i her yerde (özellikle iOS/QuickTime
ve sosyal medya) oynatılabilen mp4'e çevirmek.

Harici binary: ffmpeg. Çözümleme sırası → `FFMPEG_BIN` env, sonra
`shutil.which("ffmpeg")` (PATH), sonra sabit varsayılan
`<ENGINES_DIR>/bin/ffmpeg`. Binary bulunamazsa 422 (Türkçe detay)
döner; frontend bu durumda webm indirmesine düşer (toast ile bilgilendirir).

Eşzamanlılık: ffmpeg CPU-yoğun. print-prep/sewing desenindeki gibi ağır işi
sınırlı bir havuza (max 2) alırız ki eşzamanlı istekler makineyi boğmasın
(Starlette senkron route'u dış havuzda koşar; `.result()` ile iç havuzun
bitmesini bekleriz → en fazla 2 eşzamanlı dönüştürme).
"""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from common.config import engines_dir
from fastapi import APIRouter, File, HTTPException, UploadFile, status
from fastapi.responses import Response

from gateway.auth import require_token

router = APIRouter(dependencies=[require_token()])

# ffmpeg PATH'te değilse bakılacak sabit varsayılan (indirme bekleyen binary).
DEFAULT_FFMPEG = str(engines_dir() / "bin" / "ffmpeg")

# Ağır ffmpeg işini sınırla (max 2 eşzamanlı dönüştürme) — print-prep deseni.
_CONVERT_POOL = ThreadPoolExecutor(max_workers=2, thread_name_prefix="convert-video")


def _resolve_ffmpeg() -> str | None:
    """ffmpeg binary yolunu çöz; bulunamazsa None.

    Sıra: FFMPEG_BIN env → PATH (which) → sabit varsayılan. Yalnız gerçekten
    var olan (çalıştırılabilir) bir yol döner.
    """
    env = os.environ.get("FFMPEG_BIN")
    if env and Path(env).is_file():
        return env
    which = shutil.which("ffmpeg")
    if which:
        return which
    if Path(DEFAULT_FFMPEG).is_file():
        return DEFAULT_FFMPEG
    return None


def _convert(ffmpeg: str, webm: bytes) -> bytes:
    """webm ikilisini mp4'e çevir (havuzda koşar). Hata → HTTPException(422)."""
    with tempfile.TemporaryDirectory(prefix="turntable-") as tmp:
        inp = Path(tmp) / "in.webm"
        outp = Path(tmp) / "out.mp4"
        inp.write_bytes(webm)
        cmd = [
            ffmpeg, "-y", "-i", str(inp),
            "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-movflags", "+faststart", str(outp),
        ]
        try:
            proc = subprocess.run(cmd, capture_output=True)
        except OSError as exc:  # binary silinmiş/çalıştırılamıyor
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                "ffmpeg çalıştırılamadı; video dönüştürme yapılamıyor.",
            ) from exc
        if proc.returncode != 0 or not outp.exists():
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                "Video dönüştürme başarısız (ffmpeg hata verdi).",
            )
        return outp.read_bytes()


@router.post("/convert/video")
def convert_video(file: UploadFile = File(...)) -> Response:
    """Yüklenen webm turntable kaydını mp4'e çevirip ikili olarak döner."""
    ffmpeg = _resolve_ffmpeg()
    if ffmpeg is None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "ffmpeg bulunamadı; mp4 dönüştürme yapılamıyor (webm olarak indirin).",
        )
    webm = file.file.read()
    if not webm:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, "Boş video yüklendi."
        )
    # Ağır işi sınırlı havuza al (max 2 eşzamanlı); sonucu bekle.
    mp4 = _CONVERT_POOL.submit(_convert, ffmpeg, webm).result()
    return Response(
        content=mp4,
        media_type="video/mp4",
        headers={"Content-Disposition": 'attachment; filename="turntable.mp4"'},
    )
