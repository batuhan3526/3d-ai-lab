"""Tiling: motif PNG'sini N×N ızgaraya döşe + kumaşın UV texture'ına tam-UV uygula.
Projeksiyon YOK (bake_motif_into_texture'dan farklı) — UV 0..1 tüm döşeli tuvale
eşlenir, motif N×N tekrar görünür. Sonuç: dışa aktarılabilir kalıcı desen."""
from __future__ import annotations


def build_tiled_texture(motif_path: str, repeat: int, bg_color=(255, 255, 255), size: int = 2048):
    """motif PNG → size×size RGB döşeli görsel (PIL Image). repeat=N → N×N ızgara."""
    from PIL import Image
    repeat = max(1, int(repeat))
    bg = Image.new("RGB", (size, size), tuple(bg_color))
    motif = Image.open(motif_path).convert("RGBA")
    cell = max(1, size // repeat)
    tile = motif.resize((cell, cell), Image.LANCZOS)
    for r in range(repeat):
        for c in range(repeat):
            bg.paste(tile, (c * cell, r * cell), tile)  # alfa maskesi ile kompozit
    return bg


def bake_tiled_texture(mesh_path: str, motif_path: str, out_path: str, *,
                       repeat: int, bg_color=(255, 255, 255), tex_size: int = 2048) -> str:
    """mesh + motif → döşeli texture'lı yeni mesh.glb (tam-UV doku değişimi)."""
    import numpy as np
    import trimesh

    m = trimesh.load(mesh_path, force="mesh")
    uv_attr = getattr(m.visual, "uv", None)
    if uv_attr is None or len(uv_attr) != len(m.vertices):
        raise RuntimeError("mesh'te UV yok — tiling edilemez")
    tex = build_tiled_texture(motif_path, repeat, bg_color, tex_size)
    m.visual = trimesh.visual.TextureVisuals(
        uv=np.asarray(uv_attr, dtype=np.float64),
        material=trimesh.visual.material.PBRMaterial(baseColorTexture=tex))
    m.export(out_path)
    return f"tiled repeat={repeat}"
