"""Statik manken manifest + servis testleri (Task D1).

- GET /templates/mannequins şema uyumluluğu (id, label, file, pose∈{T,A}, license, source_url)
- Manifest yoksa boş liste (kırılmaz — panel "indirilmemiş" uyarısını gösterir)
- GLB dosyası /template-assets/mannequins/<file> altında servis edilir
- Repoya işlenmiş data/templates/mannequins/manifest.json şemaya uyar
"""
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

_REQUIRED_KEYS = {"id", "label", "file", "pose", "license", "source_url"}
_VALID_POSES = {"T", "A"}


def _assert_valid_entry(entry: dict) -> None:
    assert _REQUIRED_KEYS <= set(entry.keys()), f"eksik anahtar: {entry}"
    assert isinstance(entry["id"], str) and entry["id"]
    assert isinstance(entry["label"], str) and entry["label"]
    assert isinstance(entry["file"], str) and entry["file"].endswith(".glb")
    assert entry["pose"] in _VALID_POSES, f"geçersiz pose: {entry['pose']}"
    assert entry["license"] == "CC0", f"CC0 dışı lisans: {entry['license']}"
    assert isinstance(entry["source_url"], str) and entry["source_url"].startswith("http")


@pytest.fixture
def mannequins_dir(tmp_path, monkeypatch):
    """Geçici templates dizini + mannequins/manifest.json + bir sahte GLB."""
    monkeypatch.setenv("TEMPLATES_DIR", str(tmp_path).replace("\\", "/"))
    from common.config import get_settings
    get_settings.cache_clear()

    mdir = tmp_path / "mannequins"
    mdir.mkdir()
    (mdir / "male-a.glb").write_bytes(b"GLB-MANNEQUIN")
    manifest = [
        {"id": "male-a", "label": "Erkek (A-pose)", "file": "mannequins/male-a.glb",
         "pose": "A", "license": "CC0", "source_url": "https://quaternius.com/x"},
        {"id": "neutral-t", "label": "Nötr (T-pose)", "file": "mannequins/neutral-t.glb",
         "pose": "T", "license": "CC0", "source_url": "https://polyhaven.com/models"},
    ]
    (mdir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    yield tmp_path
    get_settings.cache_clear()


@pytest.fixture
def client(mannequins_dir):
    from gateway.main import app
    return TestClient(app)


def test_manifest_public_no_auth(client):
    resp = client.get("/templates/mannequins")
    assert resp.status_code == 200
    body = resp.json()
    assert isinstance(body, list)
    assert len(body) == 2
    for entry in body:
        _assert_valid_entry(entry)


def test_available_flag_reflects_disk(client):
    """T6: her entry canlı 'available' bool taşır — GLB diskte varsa True, yoksa False.

    Fixture'da male-a.glb yazılı (mevcut), neutral-t.glb yok → sırasıyla True/False.
    """
    body = client.get("/templates/mannequins").json()
    by_id = {e["id"]: e for e in body}
    assert "available" in by_id["male-a"] and by_id["male-a"]["available"] is True
    assert "available" in by_id["neutral-t"] and by_id["neutral-t"]["available"] is False


def test_available_recomputed_live_when_file_lands(client, mannequins_dir):
    """T6: availability önbelleksiz — eksik GLB diske düşünce sonraki istekte True olur."""
    # Başta neutral-t yok → False
    first = {e["id"]: e for e in client.get("/templates/mannequins").json()}
    assert first["neutral-t"]["available"] is False
    # Ev-içi üretim GLB'yi diske yazar (orkestratör senaryosu)
    (mannequins_dir / "mannequins" / "neutral-t.glb").write_bytes(b"GLB-LANDED")
    second = {e["id"]: e for e in client.get("/templates/mannequins").json()}
    assert second["neutral-t"]["available"] is True


def test_glb_served_via_template_assets(client):
    resp = client.get("/template-assets/mannequins/male-a.glb")
    assert resp.status_code == 200
    assert resp.content == b"GLB-MANNEQUIN"


def test_missing_glb_returns_404(client):
    resp = client.get("/template-assets/mannequins/nope.glb")
    assert resp.status_code == 404


def test_missing_manifest_returns_empty_list(tmp_path, monkeypatch):
    """Manifest yoksa 200 + [] (kırılmaz — panel indirilmemiş uyarısı gösterir)."""
    monkeypatch.setenv("TEMPLATES_DIR", str(tmp_path / "empty").replace("\\", "/"))
    from common.config import get_settings
    get_settings.cache_clear()
    from gateway.main import app
    c = TestClient(app)
    resp = c.get("/templates/mannequins")
    assert resp.status_code == 200
    assert resp.json() == []
    get_settings.cache_clear()


def test_non_list_manifest_returns_empty_list(tmp_path, monkeypatch):
    """Bozuk/eski format (dict) → boş liste (kırılmaz)."""
    monkeypatch.setenv("TEMPLATES_DIR", str(tmp_path).replace("\\", "/"))
    from common.config import get_settings
    get_settings.cache_clear()
    mdir = tmp_path / "mannequins"
    mdir.mkdir()
    (mdir / "manifest.json").write_text(json.dumps({"oops": 1}), encoding="utf-8")
    from gateway.main import app
    c = TestClient(app)
    resp = c.get("/templates/mannequins")
    assert resp.status_code == 200
    assert resp.json() == []
    get_settings.cache_clear()


def test_committed_manifest_conforms_to_schema():
    """Repoya işlenmiş data/templates/mannequins/manifest.json şemaya uyar."""
    repo_root = Path(__file__).resolve().parents[3]
    manifest_path = repo_root / "data" / "templates" / "mannequins" / "manifest.json"
    assert manifest_path.exists(), f"işlenmiş manifest yok: {manifest_path}"
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert isinstance(data, list) and len(data) >= 2
    ids = set()
    for entry in data:
        _assert_valid_entry(entry)
        ids.add(entry["id"])
    assert len(ids) == len(data), "manken id'leri benzersiz olmalı"
