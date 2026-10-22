"""Poly Pizza CC0 indirme overlay testleri (mocked HTTP).

Not: structlog test izolasyonu kök conftest.py'deki autouse fixture ile sağlanır.
"""
import json

from templates_tool import download


def test_parse_search_results():
    payload = {
        "results": [
            {"Title": "Cool Tee", "Download": "https://cdn.poly.pizza/a.glb",
             "Attribution": "by X (CC0)", "Creator": {"Username": "x"}},
            {"Title": "No URL"},  # Download yok -> atlanır
        ]
    }
    models = download.parse_search_results(payload)
    assert len(models) == 1
    assert models[0].title == "Cool Tee"
    assert models[0].download_url == "https://cdn.poly.pizza/a.glb"


def test_apply_downloads_skips_without_key(tmp_path, monkeypatch):
    """Key yoksa manifest hiç değişmez, hiç HTTP yapılmaz."""
    manifest = {"garments": [{"type": "tshirt", "label": "Tişört",
                              "templates": [{"id": "tshirt-01", "name": "x",
                                             "glb": "tshirt/tshirt-01.glb",
                                             "thumbnail": "tshirt/tshirt-01.png",
                                             "license": "CC0 (procedural)",
                                             "source": "generated"}]}]}
    mpath = tmp_path / "manifest.json"
    mpath.write_text(json.dumps(manifest), encoding="utf-8")

    changed = download.apply_downloads(
        templates_dir=tmp_path, manifest_path=mpath, api_key="", per_type=1
    )
    assert changed == 0
    after = json.loads(mpath.read_text(encoding="utf-8"))
    assert after["garments"][0]["templates"][0]["source"] == "generated"


def test_apply_downloads_updates_slot(tmp_path, monkeypatch):
    """Başarılı indirmede slot GLB değişir ve manifest entry güncellenir."""
    (tmp_path / "tshirt").mkdir()
    manifest = {"garments": [{"type": "tshirt", "label": "Tişört",
                              "templates": [{"id": "tshirt-01", "name": "x",
                                             "glb": "tshirt/tshirt-01.glb",
                                             "thumbnail": "tshirt/tshirt-01.png",
                                             "license": "CC0 (procedural)",
                                             "source": "generated"}]}]}
    mpath = tmp_path / "manifest.json"
    mpath.write_text(json.dumps(manifest), encoding="utf-8")

    def fake_search(query, api_key, limit):
        return [download.PolyModel(title="Real Tee",
                                   download_url="https://cdn/x.glb",
                                   attribution="by Y (CC0)")]

    def fake_fetch(url):
        return b"GLB-BYTES"

    monkeypatch.setattr(download, "search_cc0", fake_search)
    monkeypatch.setattr(download, "_fetch_bytes", fake_fetch)

    changed = download.apply_downloads(
        templates_dir=tmp_path, manifest_path=mpath, api_key="KEY", per_type=1
    )
    assert changed == 1
    glb = tmp_path / "tshirt" / "tshirt-01.glb"
    assert glb.read_bytes() == b"GLB-BYTES"
    after = json.loads(mpath.read_text(encoding="utf-8"))
    entry = after["garments"][0]["templates"][0]
    assert entry["source"] == "polypizza"
    assert "CC0" in entry["license"]
