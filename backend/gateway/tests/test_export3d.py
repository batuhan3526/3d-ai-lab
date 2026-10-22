"""FBX/OBJ dışa-aktarma testleri — POST /projects/{id}/export3d + GET export3d.{fmt}.

Hermetik: her test tmp_path SQLite + PROJECTS_DIR (gerçek data/ dizinine yazmaz),
env monkeypatch + get_settings.cache_clear + db.reset_engine (test_print_prep/retopo
deseni). OBJ yolu gerçek trimesh ile koşar (kutu mesh). FBX yolu subprocess.run
monkeypatch'lenir (Blender binary'si gerçekten koşmaz) ve binary yolu var-görünen
bir dummy dosyaya monkeypatch'lenir; missing-binary testi var-olmayan yola işaret eder.
"""
from __future__ import annotations

import io
import zipfile
from pathlib import Path

import pytest
import trimesh
from fastapi.testclient import TestClient

AUTH = {"Authorization": "Bearer test-token-bootstrap"}


@pytest.fixture
def ctx(tmp_path, monkeypatch):
    db_path = str(tmp_path / "export3d.db").replace("\\", "/")
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
        "name": "Export Tasarımı", "garment_type": "tshirt", "template_id": "tshirt-01",
        "customizations": {"color": "#ffffff", "decals": []},
    }, headers=AUTH).json()["id"]


def _write_mesh(projects_dir: Path, pid: str) -> Path:
    """Basit kutu = geçerli dışa-aktarma girdisi."""
    box = trimesh.creation.box(extents=(2.0, 3.0, 4.0))
    path = projects_dir / "default" / pid / "mesh.glb"
    path.parent.mkdir(parents=True, exist_ok=True)
    box.export(str(path))
    return path


def _install_fake_blender(monkeypatch, tmp_path: Path) -> Path:
    """Var-görünen dummy Blender binary'si + subprocess.run sahtesi.

    Sahte run, `--` ayıracından sonraki ikinci argümanı (çıktı FBX) bulur ve oraya
    küçük bir dosya yazar (Blender'ın FBX ürettiği gibi), returncode=0 döner.
    """
    from gateway.routes import export3d

    fake_bin = tmp_path / "blender"
    fake_bin.write_text("#!/bin/sh\n")
    monkeypatch.setattr(export3d, "_blender_bin", lambda: str(fake_bin))

    class _Proc:
        returncode = 0
        stdout = ""
        stderr = ""

    def _fake_run(cmd, *args, **kwargs):
        sep = cmd.index("--")
        out_fbx = Path(cmd[sep + 2])
        out_fbx.write_bytes(b"Kaydav FBX\x00fake-fbx-bytes")
        return _Proc()

    monkeypatch.setattr(export3d.subprocess, "run", _fake_run)
    return fake_bin


# --- auth ----------------------------------------------------------------------
def test_requires_auth(ctx):
    client, _, _ = ctx
    pid = _make(client)
    assert client.post(f"/projects/{pid}/export3d",
                       json={"format": "obj"}).status_code == 401


# --- OBJ (gerçek trimesh) ------------------------------------------------------
def test_obj_returns_url_and_size(ctx):
    client, projects_dir, _ = ctx
    pid = _make(client)
    _write_mesh(projects_dir, pid)

    r = client.post(f"/projects/{pid}/export3d", json={"format": "obj"}, headers=AUTH)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["url"] == f"/projects/{pid}/export3d.obj"
    assert body["size_bytes"] > 0

    # Diskte ZIP olarak yazıldı.
    out = projects_dir / "default" / pid / "export.obj.zip"
    assert out.exists()


def test_obj_zip_contains_obj(ctx):
    client, projects_dir, _ = ctx
    pid = _make(client)
    _write_mesh(projects_dir, pid)
    client.post(f"/projects/{pid}/export3d", json={"format": "obj"}, headers=AUTH)

    out = projects_dir / "default" / pid / "export.obj.zip"
    with zipfile.ZipFile(out) as zf:
        names = zf.namelist()
        assert "model.obj" in names
        # OBJ içeriği yüklenebilir (geçerli mesh).
        obj_bytes = zf.read("model.obj")
    reloaded = trimesh.load(io.BytesIO(obj_bytes), file_type="obj", force="mesh")
    assert len(reloaded.faces) > 0


def test_obj_download_serves_zip(ctx):
    client, projects_dir, _ = ctx
    pid = _make(client)
    _write_mesh(projects_dir, pid)
    client.post(f"/projects/{pid}/export3d", json={"format": "obj"}, headers=AUTH)

    r = client.get(f"/projects/{pid}/export3d.obj", headers=AUTH)
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/zip"
    # İçerik geçerli bir ZIP.
    with zipfile.ZipFile(io.BytesIO(r.content)) as zf:
        assert "model.obj" in zf.namelist()


# --- FBX (subprocess mock) -----------------------------------------------------
def test_fbx_returns_url_and_size(ctx, monkeypatch):
    client, projects_dir, tmp_path = ctx
    pid = _make(client)
    _write_mesh(projects_dir, pid)
    _install_fake_blender(monkeypatch, tmp_path)

    r = client.post(f"/projects/{pid}/export3d", json={"format": "fbx"}, headers=AUTH)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["url"] == f"/projects/{pid}/export3d.fbx"
    assert body["size_bytes"] > 0

    out = projects_dir / "default" / pid / "export.fbx"
    assert out.exists()


def test_fbx_cmd_shape(ctx, monkeypatch):
    """Blender başsız argümanları doğru sırada geçilir: -b -P <script> -- in out."""
    client, projects_dir, tmp_path = ctx
    pid = _make(client)
    _write_mesh(projects_dir, pid)
    from gateway.routes import export3d

    fake_bin = tmp_path / "blender"
    fake_bin.write_text("")
    monkeypatch.setattr(export3d, "_blender_bin", lambda: str(fake_bin))

    captured = {}

    class _Proc:
        returncode = 0
        stdout = ""
        stderr = ""

    def _fake_run(cmd, *args, **kwargs):
        captured["cmd"] = cmd
        Path(cmd[cmd.index("--") + 2]).write_bytes(b"fbx")
        return _Proc()

    monkeypatch.setattr(export3d.subprocess, "run", _fake_run)
    client.post(f"/projects/{pid}/export3d", json={"format": "fbx"}, headers=AUTH)
    cmd = captured["cmd"]
    assert cmd[0] == str(fake_bin)
    assert cmd[1] == "-b"
    assert cmd[2] == "-P"
    assert cmd[3].endswith("blender_export.py")
    sep = cmd.index("--")
    assert cmd[sep + 1].endswith("mesh.glb")   # girdi GLB
    assert cmd[sep + 2].endswith("export.fbx")  # çıktı FBX


def test_fbx_download_serves_file(ctx, monkeypatch):
    client, projects_dir, tmp_path = ctx
    pid = _make(client)
    _write_mesh(projects_dir, pid)
    _install_fake_blender(monkeypatch, tmp_path)
    client.post(f"/projects/{pid}/export3d", json={"format": "fbx"}, headers=AUTH)

    r = client.get(f"/projects/{pid}/export3d.fbx", headers=AUTH)
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/octet-stream"
    assert len(r.content) > 0


# --- graceful degradation ------------------------------------------------------
def test_missing_blender_422(ctx, monkeypatch):
    client, projects_dir, tmp_path = ctx
    pid = _make(client)
    _write_mesh(projects_dir, pid)
    from gateway.routes import export3d
    # Binary yolu var-olmayan bir dosyaya işaret eder → 422.
    monkeypatch.setattr(export3d, "_blender_bin",
                        lambda: str(tmp_path / "nope" / "blender"))
    r = client.post(f"/projects/{pid}/export3d", json={"format": "fbx"}, headers=AUTH)
    assert r.status_code == 422
    assert "blender" in r.json()["detail"].lower()


def test_fbx_subprocess_failure_422(ctx, monkeypatch):
    client, projects_dir, tmp_path = ctx
    pid = _make(client)
    _write_mesh(projects_dir, pid)
    from gateway.routes import export3d

    fake_bin = tmp_path / "blender"
    fake_bin.write_text("")
    monkeypatch.setattr(export3d, "_blender_bin", lambda: str(fake_bin))

    class _Proc:
        returncode = 1
        stdout = ""
        stderr = "boom"

    # Çıktı FBX yazılmaz + returncode!=0 → 422.
    monkeypatch.setattr(export3d.subprocess, "run", lambda *a, **k: _Proc())
    r = client.post(f"/projects/{pid}/export3d", json={"format": "fbx"}, headers=AUTH)
    assert r.status_code == 422


# --- validation / missing ------------------------------------------------------
def test_bad_format_422(ctx):
    client, projects_dir, _ = ctx
    pid = _make(client)
    _write_mesh(projects_dir, pid)
    # Literal['fbx','obj'] dışı → pydantic 422.
    r = client.post(f"/projects/{pid}/export3d", json={"format": "stl"}, headers=AUTH)
    assert r.status_code == 422


def test_missing_project_404(ctx):
    client, _, _ = ctx
    r = client.post("/projects/does-not-exist/export3d",
                    json={"format": "obj"}, headers=AUTH)
    assert r.status_code == 404


def test_missing_mesh_404(ctx):
    client, _, _ = ctx
    pid = _make(client)  # proje var ama mesh üretilmemiş
    r = client.post(f"/projects/{pid}/export3d", json={"format": "obj"}, headers=AUTH)
    assert r.status_code == 404


def test_download_before_export_404(ctx):
    client, _, _ = ctx
    pid = _make(client)
    assert client.get(f"/projects/{pid}/export3d.obj", headers=AUTH).status_code == 404


def test_download_bad_format_422(ctx):
    client, projects_dir, _ = ctx
    pid = _make(client)
    _write_mesh(projects_dir, pid)
    r = client.get(f"/projects/{pid}/export3d.stl", headers=AUTH)
    assert r.status_code == 422
