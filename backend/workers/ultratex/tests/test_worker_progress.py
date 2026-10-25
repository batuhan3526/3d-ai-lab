"""Hi3D'den devredilen işte UltraTex ilerlemeyi geri düşürmemeli (50 → 30 değil)."""
from __future__ import annotations

import pathlib
import sys

import fakeredis

_SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))


def _run(tmp_path, monkeypatch, start: int | None) -> list[int]:
    monkeypatch.setenv("PROJECTS_DIR", str(tmp_path))
    from common.config import get_settings
    get_settings.cache_clear()
    from common.jobs import JobStore
    from ultratex_worker import worker
    store = JobStore(fakeredis.FakeStrictRedis(decode_responses=True))
    store.create("j", {"kind": "refine"})
    if start is not None:
        store.set_progress("j", "texture", start)
    seen = []
    orig = store.set_progress
    monkeypatch.setattr(store, "set_progress", lambda j, st, pct: (seen.append(pct), orig(j, st, pct)))
    monkeypatch.setattr(worker, "JobStore", lambda: store)
    monkeypatch.setattr(worker, "_set_mesh_path", lambda *a: None)

    class Fake:
        def retexture(self, src, ref, params, out):
            pathlib.Path(out).write_bytes(b"glTF")
    monkeypatch.setattr(worker, "_get", lambda: Fake())
    p = tmp_path / "default" / "p"
    p.mkdir(parents=True)
    (p / "mesh.glb").write_bytes(b"glTF")
    (p / "ref_image.png").write_bytes(b"png")
    worker.generate_texture.run(job_id="j", project_id="p", source_project_id="p")
    get_settings.cache_clear()
    return seen


def test_chained_job_progress_does_not_go_back(tmp_path, monkeypatch):
    assert _run(tmp_path, monkeypatch, 50)[:2] == [50, 95]


def test_fresh_job_starts_at_30(tmp_path, monkeypatch):
    assert _run(tmp_path, monkeypatch, None)[:2] == [30, 95]
