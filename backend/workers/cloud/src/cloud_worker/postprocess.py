"""Sağlayıcı çıktılarını sistemin beklediği biçime getir (GPU'suz).

- `to_rgba_motif`: motif PNG'si → şeffaf zeminli RGBA. Sağlayıcı zaten alfa verdiyse
  dokunulmaz; vermediyse kenarlara bağlı açık (beyaz) zemin taşkın-dolgu ile silinir
  (FLUX motifindeki BiRefNet matte'in GPU'suz karşılığı; motif prompt'u "düz beyaz
  zemin" ister).
- `to_glb`: 3D çıktı → GLB (GLB değilse trimesh ile dönüştürülür).
"""
from __future__ import annotations

import io
from pathlib import Path

import numpy as np
from PIL import Image

_BG_TOL = 28  # zemin rengine RGB uzaklığı (0-255 ölçeğinde, kanal başına max)


def to_rgba_motif(data: bytes, out_path: Path) -> Path:
    img = Image.open(io.BytesIO(data))
    img.load()
    if img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info):
        rgba = img.convert("RGBA")
        a = np.asarray(rgba)[:, :, 3]
        if (a < 250).mean() > 0.02:  # gerçekten şeffaf zemin var
            out_path.parent.mkdir(parents=True, exist_ok=True)
            rgba.save(out_path)
            return out_path
    rgb = np.asarray(img.convert("RGB")).astype(np.int16)
    h, w, _ = rgb.shape
    border = np.concatenate([rgb[0], rgb[-1], rgb[:, 0], rgb[:, -1]])
    bg = np.median(border, axis=0)
    near = (np.abs(rgb - bg).max(axis=2) <= _BG_TOL)
    from scipy import ndimage
    lab, _ = ndimage.label(near)
    edge = np.unique(np.concatenate([lab[0], lab[-1], lab[:, 0], lab[:, -1]]))
    mask = np.isin(lab, edge[edge > 0])
    alpha = np.where(mask, 0, 255).astype(np.uint8)
    out = np.dstack([rgb.astype(np.uint8), alpha])
    out_path.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(out, "RGBA").save(out_path)
    return out_path


def to_glb(data: bytes, out_path: Path, hint: str = "") -> Path:
    """GLB baytlarını yaz; değilse (OBJ/FBX-zip/PLY…) trimesh ile GLB'ye çevir."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if data[:4] == b"glTF":
        out_path.write_bytes(data)
        return out_path
    import trimesh
    ftype = (hint or "").lower().lstrip(".") or None
    try:
        scene = trimesh.load(io.BytesIO(data), file_type=ftype or "obj", force="scene")
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(f"3D çıktı GLB değil ve dönüştürülemedi ({ftype or '?'})") from exc
    scene.export(out_path)
    return out_path
