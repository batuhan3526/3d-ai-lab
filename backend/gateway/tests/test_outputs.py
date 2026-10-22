"""Sonuçlar API'si: face4d/gaussian_scene çıktılarının manifest'i + medya servisi."""
import pathlib

import pytest
from fastapi.testclient import TestClient

TOKEN = {"Authorization": "Bearer test-token-bootstrap"}


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("APP_TOKEN", "test-token-bootstrap")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{str(tmp_path / 't.db').replace(chr(92), '/')}")
    monkeypatch.setenv("PROJECTS_DIR", str(tmp_path / "projects").replace(chr(92), "/"))
    from common.config import get_settings
    get_settings.cache_clear()
    from gateway import db as gdb
    gdb.reset_engine()
    gdb.init_db()
    from gateway.db import get_sessionmaker
    from gateway.models.orm import Project
    with get_sessionmaker()() as s:
        p = Project(user_id="default", name="yuz4d", garment_type="boots",
                    template_id="face4d", customizations={"color": "#ccc", "decals": []})
        s.add(p)
        s.commit()
        s.refresh(p)
        pid = p.id
    from gateway.main import app
    c = TestClient(app)
    c.pid = pid
    c.proj_dir = pathlib.Path(str(tmp_path / "projects" / "default" / pid))
    return c


def _seed_outputs(proj_dir: pathlib.Path) -> None:
    (proj_dir / "face4d" / "videos").mkdir(parents=True)
    (proj_dir / "face4d" / "videos" / "grand_tour.mp4").write_bytes(b"\x00" * 32)
    (proj_dir / "face4d" / "ply" / "canonical").mkdir(parents=True)
    (proj_dir / "face4d" / "ply" / "canonical" / "frame_0000.ply").write_bytes(b"ply")
    (proj_dir / "gaussian_scene" / "gif").mkdir(parents=True)
    (proj_dir / "gaussian_scene" / "gif" / "sample_0000.gif").write_bytes(b"GIF89a")
    # Listelenmemesi gerekenler:
    (proj_dir / "gaussian_scene" / "samples").mkdir(parents=True)
    (proj_dir / "gaussian_scene" / "samples" / "sample_0000.pt").write_bytes(b"pt")
    (proj_dir / "face4d" / "maps").mkdir(parents=True)
    (proj_dir / "face4d" / "maps" / "depth.png").write_bytes(b"png")


def test_manifest_lists_whitelisted_kinds(client):
    _seed_outputs(client.proj_dir)
    r = client.get(f"/projects/{client.pid}/outputs", headers=TOKEN)
    assert r.status_code == 200
    items = r.json()
    by_path = {i["path"]: i for i in items}
    assert by_path["face4d/videos/grand_tour.mp4"]["kind"] == "video"
    assert by_path["face4d/videos/grand_tour.mp4"]["size"] == 32
    assert by_path["face4d/videos/grand_tour.mp4"]["name"] == "grand_tour.mp4"
    assert by_path["face4d/ply/canonical/frame_0000.ply"]["kind"] == "ply"
    assert by_path["gaussian_scene/gif/sample_0000.gif"]["kind"] == "gif"
    # .pt ve .png beyaz-liste dışı → yok
    assert all(not p.endswith((".pt", ".png")) for p in by_path)


def test_manifest_empty_when_no_output_dirs(client):
    r = client.get(f"/projects/{client.pid}/outputs", headers=TOKEN)
    assert r.status_code == 200
    assert r.json() == []


def test_manifest_404_unknown_project(client):
    r = client.get("/projects/yok123/outputs", headers=TOKEN)
    assert r.status_code == 404


def test_manifest_requires_token(client):
    r = client.get(f"/projects/{client.pid}/outputs")
    assert r.status_code == 401


def test_media_served_with_content_type(client):
    _seed_outputs(client.proj_dir)
    r = client.get(f"/projects/{client.pid}/outputs/face4d/videos/grand_tour.mp4")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("video/mp4")
    r = client.get(f"/projects/{client.pid}/outputs/gaussian_scene/gif/sample_0000.gif")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("image/gif")
    r = client.get(f"/projects/{client.pid}/outputs/face4d/ply/canonical/frame_0000.ply")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/octet-stream")


@pytest.mark.parametrize("bad", [
    "..%2F..%2Fsecret.mp4",                  # traversal (URL-encoded; düz ../ istemcide normalize olur)
    "face4d/../../../etc/passwd",            # traversal (kök içinden)
    "uploads/x.mp4",                         # beyaz-liste dışı kök
    "face4d/maps/depth.png",                 # beyaz-liste dışı uzantı
    "gaussian_scene/samples/sample_0000.pt", # beyaz-liste dışı uzantı
])
def test_media_rejects_bad_paths(client, bad):
    _seed_outputs(client.proj_dir)
    r = client.get(f"/projects/{client.pid}/outputs/{bad}")
    assert r.status_code == 404


def test_media_404_missing_file(client):
    r = client.get(f"/projects/{client.pid}/outputs/face4d/videos/yok.mp4")
    assert r.status_code == 404
