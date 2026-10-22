"""Manifest builder testleri."""
import json

from templates_tool.manifest import TemplateEntry, build_manifest


def test_template_entry_shape():
    e = TemplateEntry(
        id="tshirt-01", name="Tişört 1",
        glb="tshirt/tshirt-01.glb", thumbnail="tshirt/tshirt-01.png",
        license="CC0 (procedural)", source="generated",
    )
    d = e.to_dict()
    assert d["id"] == "tshirt-01"
    assert d["glb"] == "tshirt/tshirt-01.glb"
    assert d["source"] == "generated"


def test_build_manifest_six_types_five_each():
    manifest = build_manifest(per_type=5)
    assert len(manifest["garments"]) == 6
    for g in manifest["garments"]:
        assert set(g.keys()) == {"type", "label", "templates"}
        assert len(g["templates"]) == 5
        ids = [t["id"] for t in g["templates"]]
        assert len(set(ids)) == 5  # benzersiz


def test_build_manifest_is_json_serializable():
    manifest = build_manifest(per_type=5)
    json.dumps(manifest)  # raise etmemeli
