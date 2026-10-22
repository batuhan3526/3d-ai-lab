"""Şablon manifest modeli ve builder.

Manifest, frontend galerisinin tek doğruluk kaynağıdır:
{ "garments": [ { "type", "label", "templates": [ {id,name,glb,thumbnail,license,source} ] } ] }
glb/thumbnail yolları data/templates köküne göreceli.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass

from templates_tool.garments import GARMENT_TYPES


@dataclass
class TemplateEntry:
    id: str
    name: str
    glb: str
    thumbnail: str
    license: str
    source: str  # "generated" | "polypizza"

    def to_dict(self) -> dict:
        return asdict(self)


def build_manifest(per_type: int = 5) -> dict:
    """Tüm prosedürel slotlar için varsayılan manifest üret.

    download.py daha sonra bazı slotları gerçek CC0 modellerle güncelleyebilir.
    """
    garments = []
    for gtype, label in GARMENT_TYPES.items():
        templates = []
        for i in range(per_type):
            tid = f"{gtype}-{i + 1:02d}"
            templates.append(
                TemplateEntry(
                    id=tid,
                    name=f"{label} {i + 1}",
                    glb=f"{gtype}/{tid}.glb",
                    thumbnail=f"{gtype}/{tid}.png",
                    license="CC0 (procedural)",
                    source="generated",
                ).to_dict()
            )
        garments.append({"type": gtype, "label": label, "templates": templates})
    return {"garments": garments}
