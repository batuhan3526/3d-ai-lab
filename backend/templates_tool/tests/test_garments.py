"""Prosedürel garment mesh testleri."""
import trimesh
from templates_tool.garments import GARMENT_TYPES, build_garment


def test_garment_types_are_six():
    assert set(GARMENT_TYPES.keys()) == {
        "tshirt", "shirt", "pants", "skirt", "hat", "boots"
    }
    # Her tür için Türkçe etiket var
    for label in GARMENT_TYPES.values():
        assert isinstance(label, str) and label


def test_build_garment_returns_nonempty_mesh():
    for gtype in GARMENT_TYPES:
        mesh = build_garment(gtype, variant=0)
        assert isinstance(mesh, trimesh.Trimesh)
        assert len(mesh.vertices) > 0
        assert len(mesh.faces) > 0


def test_variants_differ():
    """Aynı türün iki varyantı farklı geometri üretmeli."""
    a = build_garment("tshirt", variant=0)
    b = build_garment("tshirt", variant=1)
    assert a.vertices.shape != b.vertices.shape or not (a.vertices == b.vertices).all()


def test_unknown_type_raises():
    import pytest

    with pytest.raises(ValueError):
        build_garment("dress", variant=0)


def test_export_glb_roundtrip(tmp_path):
    """build_garment çıktısı geçerli GLB'ye export edilip geri okunabilmeli."""
    mesh = build_garment("hat", variant=2)
    out = tmp_path / "hat.glb"
    mesh.export(out, file_type="glb")
    assert out.exists() and out.stat().st_size > 0
    reloaded = trimesh.load(out, force="mesh")
    assert len(reloaded.vertices) > 0


def _glb_mesh_attributes(path) -> set[str]:
    """GLB JSON chunk'ından mesh primitive attribute adlarını çıkar."""
    import json
    import struct

    data = path.read_bytes()
    json_len = struct.unpack("<I", data[12:16])[0]
    gltf = json.loads(data[20 : 20 + json_len].decode("utf-8"))
    attrs: set[str] = set()
    for mesh in gltf.get("meshes", []):
        for prim in mesh.get("primitives", []):
            attrs |= set(prim.get("attributes", {}).keys())
    return attrs


def test_export_glb_includes_normals(tmp_path):
    """generate.py include_normals=True ile export eder: GLB NORMAL içermeli.

    NORMAL olmadan frontend drei <Decal> -> DecalGeometry normal okuyup patlar
    (undefined.getX) ve aydınlatma bozulur. Bu regresyonu kaynakta yakalar.
    """
    for gtype in ("tshirt", "skirt", "boots"):
        mesh = build_garment(gtype, variant=0)
        out = tmp_path / f"{gtype}.glb"
        mesh.export(out, file_type="glb", include_normals=True)
        attrs = _glb_mesh_attributes(out)
        assert "POSITION" in attrs, f"{gtype}: POSITION yok"
        assert "NORMAL" in attrs, f"{gtype}: NORMAL yok ({sorted(attrs)})"
