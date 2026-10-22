"""3D baskı hazırlama testleri — POST /projects/{id}/print-prep + GET print.stl.

Hermetik: her test tmp_path SQLite + PROJECTS_DIR kullanır (gerçek data/ dizinine
yazmaz), env monkeypatch + get_settings.cache_clear + db.reset_engine ile izole
edilir (test_ar.py deseni). Fixture mesh gerçek trimesh çağrılarıyla üretilir
(monkeypatch yok — trimesh gateway venv'inde kurulu).
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import trimesh
from fastapi.testclient import TestClient

AUTH = {"Authorization": "Bearer test-token-bootstrap"}


@pytest.fixture
def ctx(tmp_path, monkeypatch):
    db_path = str(tmp_path / "print.db").replace("\\", "/")
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
    yield TestClient(app), projects_dir
    db.reset_engine()
    get_settings.cache_clear()


def _make(client) -> str:
    return client.post("/projects", json={
        "name": "Baskı Tasarımı", "garment_type": "tshirt", "template_id": "tshirt-01",
        "customizations": {"color": "#ffffff", "decals": []},
    }, headers=AUTH).json()["id"]


def _write_holed_cube(projects_dir: Path, pid: str) -> Path:
    """Bir yüzü (2 üçgen) eksik küp = tek delikli, watertight-olmayan mesh."""
    box = trimesh.creation.box(extents=(2.0, 4.0, 2.0))
    holed = trimesh.Trimesh(vertices=box.vertices.copy(),
                            faces=box.faces[:-2].copy(), process=False)
    assert not holed.is_watertight  # fixture gerçekten delikli
    path = projects_dir / "default" / pid / "mesh.glb"
    path.parent.mkdir(parents=True, exist_ok=True)
    holed.export(str(path))
    return path


# --- auth ----------------------------------------------------------------------
def test_requires_auth(ctx):
    client, _ = ctx
    pid = _make(client)
    assert client.post(f"/projects/{pid}/print-prep", json={}).status_code == 401


# --- report --------------------------------------------------------------------
def test_report_fields_and_stl_written(ctx):
    client, projects_dir = ctx
    pid = _make(client)
    _write_holed_cube(projects_dir, pid)

    r = client.post(f"/projects/{pid}/print-prep", json={}, headers=AUTH)
    assert r.status_code == 200, r.text
    body = r.json()
    # Tüm sözleşme alanları mevcut.
    for key in ("watertight_before", "watertight_after", "holes_filled",
                "dims_mm", "volume_cm3", "stl_url"):
        assert key in body, f"eksik alan: {key}"

    assert body["watertight_before"] is False
    assert body["watertight_after"] is True   # delik dolduruldu
    assert body["holes_filled"] >= 1
    assert body["stl_url"] == f"/projects/{pid}/print.stl"
    assert isinstance(body["dims_mm"], list) and len(body["dims_mm"]) == 3

    # STL diske yazıldı ve yüklenebilir.
    stl = projects_dir / "default" / pid / "print.stl"
    assert stl.exists()
    reloaded = trimesh.load(str(stl), force="mesh")
    assert len(reloaded.faces) > 0


def test_target_height_scales_mesh(ctx):
    client, projects_dir = ctx
    pid = _make(client)
    _write_holed_cube(projects_dir, pid)  # Y-boyu 4 birim

    r = client.post(f"/projects/{pid}/print-prep",
                    json={"target_height_mm": 200.0}, headers=AUTH)
    assert r.status_code == 200, r.text
    dims = r.json()["dims_mm"]
    # Y ekseni (yükseklik) tam hedefe ölçeklenir.
    assert dims[1] == pytest.approx(200.0, abs=1e-2)
    # Üniform ölçek: X/Z de 2/4 oranında (100mm).
    assert dims[0] == pytest.approx(100.0, abs=1e-2)
    assert dims[2] == pytest.approx(100.0, abs=1e-2)


def test_volume_positive_after_fill(ctx):
    client, projects_dir = ctx
    pid = _make(client)
    _write_holed_cube(projects_dir, pid)
    r = client.post(f"/projects/{pid}/print-prep", json={}, headers=AUTH)
    assert r.json()["volume_cm3"] > 0


# --- serve stl -----------------------------------------------------------------
def test_get_stl_after_prep(ctx):
    client, projects_dir = ctx
    pid = _make(client)
    _write_holed_cube(projects_dir, pid)
    client.post(f"/projects/{pid}/print-prep", json={}, headers=AUTH)
    # GET public: Authorization header'sız erişilebilmeli (mesh servis deseni).
    r = client.get(f"/projects/{pid}/print.stl")
    assert r.status_code == 200
    assert r.headers["content-type"] == "model/stl"
    assert len(r.content) > 0


def test_get_stl_before_prep_404(ctx):
    client, _ = ctx
    pid = _make(client)
    assert client.get(f"/projects/{pid}/print.stl").status_code == 404


# --- missing project / mesh ----------------------------------------------------
def test_missing_project_404(ctx):
    client, _ = ctx
    r = client.post("/projects/does-not-exist/print-prep", json={}, headers=AUTH)
    assert r.status_code == 404


def test_missing_mesh_404(ctx):
    client, _ = ctx
    pid = _make(client)  # proje var ama mesh üretilmemiş
    r = client.post(f"/projects/{pid}/print-prep", json={}, headers=AUTH)
    assert r.status_code == 404


# --- boundary loop counter -----------------------------------------------------
def test_boundary_loop_counter():
    from gateway.routes.print_prep import _count_boundary_loops
    closed = trimesh.creation.box()
    assert _count_boundary_loops(closed) == 0
    holed = trimesh.Trimesh(vertices=closed.vertices.copy(),
                            faces=closed.faces[:-2].copy(), process=False)
    assert _count_boundary_loops(holed) == 1
