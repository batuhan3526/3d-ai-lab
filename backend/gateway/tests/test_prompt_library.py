"""Prompt/seed kütüphanesi CRUD testleri (Task C2).

Hermetik: templates_dir'i modülün `get_settings`'ini monkeypatch'leyerek
tmp_path'e bağlarız (env/cache_clear yok). Auth token conftest autouse'dan gelir.
"""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

_AUTH = {"Authorization": "Bearer test-token-bootstrap"}


@pytest.fixture
def client(tmp_path, monkeypatch):
    """templates_dir'i tmp_path'e bağlayan hermetik client."""
    import gateway.routes.prompt_library as pl

    monkeypatch.setattr(pl, "get_settings", lambda: SimpleNamespace(templates_dir=tmp_path))
    from gateway.main import app

    c = TestClient(app)
    c.lib_file = tmp_path / "prompt_library.json"  # type: ignore[attr-defined]
    return c


def test_list_empty_when_no_file(client):
    """Dosya yoksa boş liste (kırılmaz)."""
    r = client.get("/library/prompts", headers=_AUTH)
    assert r.status_code == 200
    assert r.json() == []
    assert not client.lib_file.exists()  # okuma dosya oluşturmaz


def test_requires_auth(client):
    assert client.get("/library/prompts").status_code == 401


def test_create_returns_entry_with_id_and_timestamp(client):
    r = client.post(
        "/library/prompts",
        headers=_AUTH,
        json={"title": "Kırmızı gül", "prompt": "a red rose motif",
              "engine_id": "trellis", "params": {"steps": 30}, "seed": 42},
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["id"]
    assert body["title"] == "Kırmızı gül"
    assert body["prompt"] == "a red rose motif"
    assert body["engine_id"] == "trellis"
    assert body["params"] == {"steps": 30}
    assert body["seed"] == 42
    assert body["created_at"]
    # dosyaya yazıldı
    on_disk = json.loads(client.lib_file.read_text(encoding="utf-8"))
    assert len(on_disk) == 1 and on_disk[0]["id"] == body["id"]


def test_create_minimal_optional_fields_none(client):
    r = client.post("/library/prompts", headers=_AUTH,
                    json={"title": "min", "prompt": "just a prompt"})
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["engine_id"] is None
    assert body["params"] is None
    assert body["seed"] is None


def test_create_rejects_empty_title(client):
    r = client.post("/library/prompts", headers=_AUTH,
                    json={"title": "", "prompt": "x"})
    assert r.status_code == 422


def test_list_returns_newest_first(client):
    for t in ("first", "second", "third"):
        assert client.post("/library/prompts", headers=_AUTH,
                           json={"title": t, "prompt": t}).status_code == 201
    rows = client.get("/library/prompts", headers=_AUTH).json()
    assert [row["title"] for row in rows] == ["third", "second", "first"]


def test_delete_removes_entry(client):
    created = client.post("/library/prompts", headers=_AUTH,
                          json={"title": "sil beni", "prompt": "x"}).json()
    r = client.delete(f"/library/prompts/{created['id']}", headers=_AUTH)
    assert r.status_code == 204
    assert client.get("/library/prompts", headers=_AUTH).json() == []


def test_delete_missing_returns_404(client):
    r = client.delete("/library/prompts/nonexistent-id", headers=_AUTH)
    assert r.status_code == 404


def test_delete_keeps_other_entries(client):
    a = client.post("/library/prompts", headers=_AUTH,
                    json={"title": "a", "prompt": "a"}).json()
    b = client.post("/library/prompts", headers=_AUTH,
                    json={"title": "b", "prompt": "b"}).json()
    assert client.delete(f"/library/prompts/{a['id']}", headers=_AUTH).status_code == 204
    rows = client.get("/library/prompts", headers=_AUTH).json()
    assert [row["id"] for row in rows] == [b["id"]]


def test_corrupt_file_yields_empty_list(client):
    client.lib_file.write_text("{ not json", encoding="utf-8")
    assert client.get("/library/prompts", headers=_AUTH).json() == []
