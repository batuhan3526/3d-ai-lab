"""common.paths testleri: resolve_mesh_path / to_stored_mesh_path —
göreli↔mutlak dönüşümü + geriye-uyum."""
from __future__ import annotations

from pathlib import Path

import pytest

_PROJECTS_DIR = "D:/studio/data/projects"


@pytest.fixture
def paths_mod(monkeypatch):
    """common.paths'i sabit PROJECTS_DIR ile taze yükle."""
    monkeypatch.setenv("APP_TOKEN", "test-token")
    monkeypatch.setenv("PROJECTS_DIR", _PROJECTS_DIR)
    from common.config import get_settings
    get_settings.cache_clear()
    import common.paths as paths
    yield paths
    get_settings.cache_clear()



# --- resolve_mesh_path ------------------------------------------------------

def test_resolve_relative_joins_projects_dir(paths_mod):
    got = paths_mod.resolve_mesh_path("default/abc/mesh.glb")
    assert got == Path(_PROJECTS_DIR) / "default/abc/mesh.glb"


def test_resolve_absolute_posix_unchanged(paths_mod):
    abs_p = "/srv/studio/data/projects/default/abc/mesh.glb"
    assert paths_mod.resolve_mesh_path(abs_p) == Path(abs_p)


def test_resolve_absolute_windows_unchanged(paths_mod):
    got = paths_mod.resolve_mesh_path("D:/studio/data/projects/default/abc/mesh.glb")
    assert got == Path("D:/studio/data/projects/default/abc/mesh.glb")


def test_resolve_windows_backslashes_normalized(paths_mod):
    got = paths_mod.resolve_mesh_path("D:\\studio\\data\\projects\\default\\abc\\mesh.glb")
    assert got == Path("D:/studio/data/projects/default/abc/mesh.glb")


# --- to_stored_mesh_path ----------------------------------------------------

def test_to_stored_relativizes_under_projects(paths_mod):
    p = f"{_PROJECTS_DIR}/default/abc/mesh.glb"
    assert paths_mod.to_stored_mesh_path(p) == "default/abc/mesh.glb"


def test_to_stored_outside_projects_stays_absolute(paths_mod):
    p = "/opt/elsewhere/mesh.glb"
    assert paths_mod.to_stored_mesh_path(p) == "/opt/elsewhere/mesh.glb"


def test_round_trip_stored_then_resolve(paths_mod):
    original = Path(_PROJECTS_DIR) / "default/xyz/mesh.glb"
    stored = paths_mod.to_stored_mesh_path(original)
    assert stored == "default/xyz/mesh.glb"
    assert paths_mod.resolve_mesh_path(stored) == original
