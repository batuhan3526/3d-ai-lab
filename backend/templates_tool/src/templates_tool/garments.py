"""Prosedürel (primitive-tabanlı) garment mesh üretimi.

Faz 1 backbone: dış kaynağa bağımlı olmadan, deterministik, tutarlı topolojili
basit kıyafet meshleri. Görsel olarak kutumsu ama renk/decal/export pipeline'ını
kanıtlamak için yeterli. Gerçek-görünüşlü meshler Faz 2+ AI'dan gelir.
"""
from __future__ import annotations

import numpy as np
import trimesh

GARMENT_TYPES: dict[str, str] = {
    "tshirt": "Tişört",
    "shirt": "Gömlek",
    "pants": "Pantolon",
    "skirt": "Etek",
    "hat": "Şapka",
    "boots": "Bot",
}


def _box(extents, translate=(0.0, 0.0, 0.0)) -> trimesh.Trimesh:
    m = trimesh.creation.box(extents=extents)
    m.apply_translation(translate)
    return m


def _cyl(radius, height, translate=(0.0, 0.0, 0.0), sections=24) -> trimesh.Trimesh:
    m = trimesh.creation.cylinder(radius=radius, height=height, sections=sections)
    m.apply_translation(translate)
    return m


def _scale(v: float, variant: int, step: float = 0.12) -> float:
    """variant 0..4 -> ~0.76x..1.24x deterministik ölçek."""
    return v * (1.0 + (variant - 2) * step)


def _tshirt(variant: int) -> trimesh.Trimesh:
    w = _scale(0.42, variant)
    torso = _box([w, 0.55, 0.18])
    sleeve_l = _cyl(0.09, 0.26, translate=(-(w / 2 + 0.10), 0.18, 0.0))
    sleeve_l.apply_transform(trimesh.transformations.rotation_matrix(np.pi / 2, [0, 0, 1]))
    sleeve_l.apply_translation((-(w / 2 + 0.05), 0.18, 0.0))
    sleeve_r = _cyl(0.09, 0.26, translate=((w / 2 + 0.10), 0.18, 0.0))
    sleeve_r.apply_transform(trimesh.transformations.rotation_matrix(np.pi / 2, [0, 0, 1]))
    sleeve_r.apply_translation(((w / 2 + 0.05), 0.18, 0.0))
    return trimesh.util.concatenate([torso, sleeve_l, sleeve_r])


def _shirt(variant: int) -> trimesh.Trimesh:
    base = _tshirt(variant)
    collar = _box([0.18, 0.06, 0.20], translate=(0.0, 0.30, 0.0))
    placket = _box([0.04, 0.55, 0.19], translate=(0.0, 0.0, 0.005))
    return trimesh.util.concatenate([base, collar, placket])


def _pants(variant: int) -> trimesh.Trimesh:
    sep = _scale(0.12, variant)
    waist = _box([0.40, 0.12, 0.18], translate=(0.0, 0.30, 0.0))
    leg_l = _cyl(0.10, 0.62, translate=(-sep, -0.05, 0.0))
    leg_r = _cyl(0.10, 0.62, translate=(sep, -0.05, 0.0))
    return trimesh.util.concatenate([waist, leg_l, leg_r])


def _skirt(variant: int) -> trimesh.Trimesh:
    top_r = _scale(0.18, variant)
    bot_r = top_r * 1.9
    height = 0.46
    # iki halkalı frustum: alt geniş, üst dar
    sections = 32
    ang = np.linspace(0, 2 * np.pi, sections, endpoint=False)
    top = np.c_[top_r * np.cos(ang), np.full(sections, height / 2), top_r * np.sin(ang)]
    bot = np.c_[bot_r * np.cos(ang), np.full(sections, -height / 2), bot_r * np.sin(ang)]
    verts = np.vstack([top, bot])
    faces = []
    for i in range(sections):
        a, b = i, (i + 1) % sections
        t_a, t_b, b_a, b_b = a, b, a + sections, b + sections
        faces.append([t_a, b_a, b_b])
        faces.append([t_a, b_b, t_b])
    return trimesh.Trimesh(vertices=verts, faces=np.array(faces), process=True)


def _hat(variant: int) -> trimesh.Trimesh:
    brim_r = _scale(0.30, variant)
    brim = _cyl(brim_r, 0.04, translate=(0.0, 0.0, 0.0))
    crown = _cyl(brim_r * 0.55, 0.22, translate=(0.0, 0.13, 0.0))
    return trimesh.util.concatenate([brim, crown])


def _boots(variant: int) -> trimesh.Trimesh:
    h = _scale(0.40, variant)
    shaft = _box([0.16, h, 0.16], translate=(0.0, h / 2, 0.0))
    foot = _box([0.16, 0.12, 0.34], translate=(0.0, 0.06, 0.10))
    return trimesh.util.concatenate([shaft, foot])


_BUILDERS = {
    "tshirt": _tshirt,
    "shirt": _shirt,
    "pants": _pants,
    "skirt": _skirt,
    "hat": _hat,
    "boots": _boots,
}


def build_garment(garment_type: str, variant: int) -> trimesh.Trimesh:
    """Verilen tür ve varyant (0..4) için prosedürel garment mesh üret.

    Raises:
        ValueError: bilinmeyen garment_type.
    """
    if garment_type not in _BUILDERS:
        raise ValueError(f"Bilinmeyen garment_type: {garment_type}")
    mesh = _BUILDERS[garment_type](variant)
    # Açık gri varsayılan PBR materyal — frontend recolor edecek
    mesh.visual = trimesh.visual.TextureVisuals(
        material=trimesh.visual.material.PBRMaterial(
            name="main",
            baseColorFactor=[200, 200, 200, 255],
            metallicFactor=0.0,
            roughnessFactor=0.8,
        )
    )
    return mesh
