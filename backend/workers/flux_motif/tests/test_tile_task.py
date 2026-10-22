from pathlib import Path


def test_tile_bake_calls_baker_and_succeeds(tmp_path, monkeypatch):
    monkeypatch.setenv("PROJECTS_DIR", str(tmp_path / "projects"))
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{str(tmp_path / 't.db').replace(chr(92), '/')}")
    from common.config import get_settings
    get_settings.cache_clear()
    import flux_motif_worker.worker as w

    # sahte JobStore (redis yok)
    events = {}
    class FakeStore:
        def set_state(self, j, s): events["state"] = s
        def set_progress(self, j, st, p): events.setdefault("prog", []).append((st, p))
        def succeed(self, j, r): events["ok"] = r
        def fail(self, j, e): events["fail"] = e
    monkeypatch.setattr(w, "JobStore", FakeStore)
    monkeypatch.setattr(w, "_set_mesh_path", lambda *a, **k: None)

    called = {}
    def fake_bake(mesh, motif, out, *, repeat, bg_color, **k):
        called.update(mesh=mesh, motif=motif, out=out, repeat=repeat, bg=bg_color)
        Path(out).parent.mkdir(parents=True, exist_ok=True)
        Path(out).write_bytes(b"glb")
    monkeypatch.setattr("flux_motif_worker.tile.bake_tiled_texture", fake_bake)

    base = Path(tmp_path / "projects" / "default")
    src = base / "src1"; src.mkdir(parents=True)
    (src / "mesh_view.glb").write_bytes(b"glb")
    (src / "decals").mkdir()
    (src / "decals" / "m.png").write_bytes(b"png")

    out = w.tile_bake.run("job1", "proj2", "src1", "decals/m.png", 4, "#ffffff")
    assert out == {"project_id": "proj2"}
    assert events["ok"] == {"project_id": "proj2"}
    assert called["repeat"] == 4 and called["bg"] == (255, 255, 255)
    assert called["motif"].endswith("decals/m.png")
