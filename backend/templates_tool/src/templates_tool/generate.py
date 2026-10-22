"""CLI: 6×N prosedürel garment GLB + thumbnail + manifest.json yaz.

Çalıştır:
    cd backend/templates_tool
    uv run python -m templates_tool.generate
Çıktı: common.config.get_settings().templates_dir (varsayılan <repo>/data/templates)
"""
from __future__ import annotations

import json
from pathlib import Path

import trimesh
from common.config import get_settings

from templates_tool.garments import GARMENT_TYPES, build_garment
from templates_tool.manifest import build_manifest

PER_TYPE = 5
_SWATCHES = ["#9aa0a6", "#a78bfa", "#60a5fa", "#34d399", "#f472b6"]


def _render_thumbnail(mesh: trimesh.Trimesh, out_png: Path, hex_color: str) -> None:
    """Basit PNG thumbnail. Offscreen render yoksa düz renkli placeholder yazar."""
    try:
        colored = mesh.copy()
        rgba = trimesh.visual.color.hex_to_rgba(hex_color)
        colored.visual = trimesh.visual.ColorVisuals(mesh=colored, face_colors=rgba)
        scene = trimesh.Scene(colored)
        png = scene.save_image(resolution=(256, 256), visible=True)
        out_png.write_bytes(png)
    except Exception:
        # pyglet/OpenGL yoksa: 1x1 renkli PNG placeholder (frontend yine de gösterir)
        _write_solid_png(out_png, hex_color)


def _write_solid_png(out_png: Path, hex_color: str) -> None:
    import struct
    import zlib

    r, g, b, _ = trimesh.visual.color.hex_to_rgba(hex_color)
    size = 64
    raw = bytearray()
    for _y in range(size):
        raw.append(0)  # filter type 0
        for _x in range(size):
            raw += bytes((int(r), int(g), int(b)))

    def chunk(tag: bytes, data: bytes) -> bytes:
        c = tag + data
        return struct.pack(">I", len(data)) + c + struct.pack(">I", zlib.crc32(c) & 0xFFFFFFFF)

    ihdr = struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0)  # 8-bit RGB
    png = b"\x89PNG\r\n\x1a\n"
    png += chunk(b"IHDR", ihdr)
    png += chunk(b"IDAT", zlib.compress(bytes(raw), 9))
    png += chunk(b"IEND", b"")
    out_png.write_bytes(png)


def main() -> None:
    settings = get_settings()
    root = Path(settings.templates_dir)
    root.mkdir(parents=True, exist_ok=True)

    for gtype in GARMENT_TYPES:
        (root / gtype).mkdir(parents=True, exist_ok=True)
        for i in range(PER_TYPE):
            tid = f"{gtype}-{i + 1:02d}"
            mesh = build_garment(gtype, variant=i)
            glb_path = root / gtype / f"{tid}.glb"
            # include_normals=True şart: aksi halde GLB'de NORMAL accessor olmaz,
            # frontend'de drei <Decal> -> DecalGeometry normal okuyup patlar ve
            # aydınlatma düz/yanlış görünür.
            mesh.export(glb_path, file_type="glb", include_normals=True)
            _render_thumbnail(mesh, root / gtype / f"{tid}.png", _SWATCHES[i % len(_SWATCHES)])
            print(f"  yazıldı: {glb_path.name}")

    manifest = build_manifest(per_type=PER_TYPE)
    (root / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"manifest.json yazıldı: {root / 'manifest.json'}")
    print(f"Toplam: {len(GARMENT_TYPES) * PER_TYPE} GLB")


if __name__ == "__main__":
    main()
