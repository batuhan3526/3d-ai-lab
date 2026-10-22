"""Instant Meshes retopoloji testleri — POST /projects/{id}/retopo.

Hermetik: her test tmp_path SQLite + PROJECTS_DIR (gerçek data/ dizinine yazmaz),
env monkeypatch + get_settings.cache_clear + db.reset_engine (test_print_prep deseni).
Instant Meshes binary'si YOK — subprocess.run monkeypatch'lenir (çıktı OBJ'yi sahte
üretir) ve binary yolu var-görünen bir dummy dosyaya monkeypatch'lenir. Fixture mesh
gerçek trimesh çağrılarıyla üretilir (trimesh gateway venv'inde kurulu).
"""
from __future__ import annotations

from pathlib import Path

import pytest
import trimesh
from fastapi.testclient import TestClient

AUTH = {"Authorization": "Bearer test-token-bootstrap"}


@pytest.fixture
def ctx(tmp_path, monkeypatch):
    db_path = str(tmp_path / "retopo.db").replace("\\", "/")
    projects_dir = tmp_path / "projects"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    monkeypatch.setenv("APP_TOKEN", "test-token-bootstrap")
    monkeypatch.setenv("PROJECTS_DIR", str(projects_dir).replace("\\", "/"))
    from common.config import get_settings
    get_settings.cache_clear()
    from gateway import db
    db.reset_engine()
    db.init_db()
    from gateway.main import app
    yield TestClient(app), projects_dir, tmp_path
    db.reset_engine()
    get_settings.cache_clear()


def _make(client) -> str:
    return client.post("/projects", json={
        "name": "Retopo Tasarımı", "garment_type": "tshirt", "template_id": "tshirt-01",
        "customizations": {"color": "#ffffff", "decals": []},
    }, headers=AUTH).json()["id"]


def _write_mesh(projects_dir: Path, pid: str, subdivisions: int = 3) -> Path:
    """Yoğun bir küre (çok yüzlü) = retopolojiye anlamlı girdi."""
    sphere = trimesh.creation.icosphere(subdivisions=subdivisions)
    path = projects_dir / "default" / pid / "mesh.glb"
    path.parent.mkdir(parents=True, exist_ok=True)
    sphere.export(str(path))
    return path


def _install_fake_bin(monkeypatch, tmp_path: Path) -> Path:
    """Var-görünen dummy Instant Meshes binary'si + subprocess.run sahtesi.

    Sahte run, `-o <out>` argümanından çıktı yolunu bulur ve oraya küçük bir kutu
    OBJ'si yazar (retopoloji çıktısı gibi), returncode=0 döner.
    """
    from gateway.routes import retopo

    fake_bin = tmp_path / "InstantMeshes"
    fake_bin.write_text("#!/bin/sh\n")
    monkeypatch.setattr(retopo, "_instant_meshes_bin", lambda: str(fake_bin))

    class _Proc:
        returncode = 0
        stdout = ""
        stderr = ""

    def _fake_run(cmd, *args, **kwargs):
        out_path = Path(cmd[cmd.index("-o") + 1])
        # Basit kutu = "yeniden ağlanmış" düşük-yüzlü çıktı.
        trimesh.creation.box(extents=(1, 1, 1)).export(str(out_path))
        return _Proc()

    monkeypatch.setattr(retopo.subprocess, "run", _fake_run)
    return fake_bin


# --- auth ----------------------------------------------------------------------
def test_requires_auth(ctx):
    client, _, _ = ctx
    pid = _make(client)
    assert client.post(f"/projects/{pid}/retopo", json={}).status_code == 401


# --- happy path ----------------------------------------------------------------
def test_retopo_writes_glb_and_returns_report(ctx, monkeypatch):
    client, projects_dir, tmp_path = ctx
    pid = _make(client)
    _write_mesh(projects_dir, pid)
    _install_fake_bin(monkeypatch, tmp_path)

    r = client.post(f"/projects/{pid}/retopo",
                    json={"target_faces": 500}, headers=AUTH)
    assert r.status_code == 200, r.text
    body = r.json()
    for key in ("variation_id", "faces_before", "faces_after", "glb_url"):
        assert key in body, f"eksik alan: {key}"

    # icosphere(3) = 1280 yüz; kutu = 12 yüz.
    assert body["faces_before"] == 1280
    assert body["faces_after"] == 12
    assert body["glb_url"].startswith(f"/projects/{pid}/variations/retopo_")
    assert body["glb_url"].endswith(".glb")

    # GLB diske yazıldı ve yüklenebilir.
    rel = body["glb_url"].split(f"/projects/{pid}/", 1)[1]
    glb = projects_dir / "default" / pid / rel
    assert glb.exists()
    reloaded = trimesh.load(str(glb), force="mesh")
    assert len(reloaded.faces) == 12


def test_registers_variation_row(ctx, monkeypatch):
    client, projects_dir, tmp_path = ctx
    pid = _make(client)
    _write_mesh(projects_dir, pid)
    _install_fake_bin(monkeypatch, tmp_path)

    r = client.post(f"/projects/{pid}/retopo",
                    json={"target_faces": 2000}, headers=AUTH)
    vid = r.json()["variation_id"]

    # Varyasyon galerisinde SUCCESS + result_path ile görünür.
    variations = client.get("/variations", headers=AUTH).json()
    match = [v for v in variations if v["id"] == vid]
    assert len(match) == 1
    v = match[0]
    assert v["kind"] == "retopo"
    assert v["status"] == "SUCCESS"
    assert v["result_path"].startswith("variations/retopo_")
    assert v["seed"] == 2000          # hedef yüz sayısı seed'de saklanır
    assert v["size_bytes"] and v["size_bytes"] > 0


def test_default_target_faces(ctx, monkeypatch):
    client, projects_dir, tmp_path = ctx
    pid = _make(client)
    _write_mesh(projects_dir, pid)
    _install_fake_bin(monkeypatch, tmp_path)
    # target_faces verilmez → varsayılan 8000; seed=8000 kaydedilir.
    r = client.post(f"/projects/{pid}/retopo", json={}, headers=AUTH)
    assert r.status_code == 200, r.text
    vid = r.json()["variation_id"]
    variations = client.get("/variations", headers=AUTH).json()
    v = [x for x in variations if x["id"] == vid][0]
    assert v["seed"] == 8000


def test_target_faces_passed_to_cli(ctx, monkeypatch):
    """CLI'ya doğru `-f <target_faces>` argümanı geçilir."""
    client, projects_dir, tmp_path = ctx
    pid = _make(client)
    _write_mesh(projects_dir, pid)
    from gateway.routes import retopo

    fake_bin = tmp_path / "InstantMeshes"
    fake_bin.write_text("")
    monkeypatch.setattr(retopo, "_instant_meshes_bin", lambda: str(fake_bin))

    captured = {}

    class _Proc:
        returncode = 0
        stdout = ""
        stderr = ""

    def _fake_run(cmd, *args, **kwargs):
        captured["cmd"] = cmd
        trimesh.creation.box().export(cmd[cmd.index("-o") + 1])
        return _Proc()

    monkeypatch.setattr(retopo.subprocess, "run", _fake_run)
    client.post(f"/projects/{pid}/retopo", json={"target_faces": 1234}, headers=AUTH)
    cmd = captured["cmd"]
    assert cmd[0] == str(fake_bin)
    # Ampirik ~7× kompanzasyonu: kullanıcı hedefi 1234 → CLI'ya 1234//7 geçer
    # (Instant Meshes üçgenlenmiş çıktısı istenen -f'in ~7 katı; canlı ölçüm 2026-07-06).
    assert "-f" in cmd and cmd[cmd.index("-f") + 1] == str(max(100, 1234 // 7))
    assert "-d" in cmd
    # Söz dizimi "[options] <input>": input EN SONDA (başta verilince -f etkisizdi).
    assert cmd[-1].endswith("in.obj")


# --- graceful degradation ------------------------------------------------------
def test_missing_binary_422(ctx, monkeypatch):
    client, projects_dir, tmp_path = ctx
    pid = _make(client)
    _write_mesh(projects_dir, pid)
    from gateway.routes import retopo
    # Binary yolu var-olmayan bir dosyaya işaret eder → 422.
    monkeypatch.setattr(retopo, "_instant_meshes_bin",
                        lambda: str(tmp_path / "nope" / "Instant Meshes"))
    r = client.post(f"/projects/{pid}/retopo", json={}, headers=AUTH)
    assert r.status_code == 422
    assert "instant-meshes" in r.json()["detail"].lower()


def test_cli_failure_422(ctx, monkeypatch):
    client, projects_dir, tmp_path = ctx
    pid = _make(client)
    _write_mesh(projects_dir, pid)
    from gateway.routes import retopo

    fake_bin = tmp_path / "InstantMeshes"
    fake_bin.write_text("")
    monkeypatch.setattr(retopo, "_instant_meshes_bin", lambda: str(fake_bin))

    class _Proc:
        returncode = 1
        stdout = ""
        stderr = "boom"

    # Çıktı OBJ yazılmaz + returncode!=0 → 422.
    monkeypatch.setattr(retopo.subprocess, "run", lambda *a, **k: _Proc())
    r = client.post(f"/projects/{pid}/retopo", json={}, headers=AUTH)
    assert r.status_code == 422


# --- missing project / mesh ----------------------------------------------------
def test_missing_project_404(ctx):
    client, _, _ = ctx
    r = client.post("/projects/does-not-exist/retopo", json={}, headers=AUTH)
    assert r.status_code == 404


def test_missing_mesh_404(ctx, monkeypatch):
    client, projects_dir, tmp_path = ctx
    pid = _make(client)  # proje var ama mesh üretilmemiş
    _install_fake_bin(monkeypatch, tmp_path)
    r = client.post(f"/projects/{pid}/retopo", json={}, headers=AUTH)
    assert r.status_code == 404
