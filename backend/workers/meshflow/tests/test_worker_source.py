"""Gateway yeni proje açıp kaynağı source_project_id ile gönderir: mesh kaynaktan okunmalı,
sonuç yeni projeye yazılmalı, kaynak değişmemeli."""
from __future__ import annotations

import pathlib
import sys

import fakeredis

_SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))


def test_refine_reads_source_writes_new_project(tmp_path, monkeypatch):
    monkeypatch.setenv("PROJECTS_DIR", str(tmp_path))
    from common.config import get_settings
    get_settings.cache_clear()
    from common.jobs import JobStore
    from meshflow_worker import worker
    r = fakeredis.FakeStrictRedis(decode_responses=True)
    monkeypatch.setattr(worker, "JobStore", lambda: JobStore(r))
    monkeypatch.setattr(worker, "_set_mesh_path", lambda db, pid, path: None)
    src = tmp_path / "default" / "src1"
    src.mkdir(parents=True)
    (src / "mesh.glb").write_bytes(b"SOURCE")
    seen = {}

    class Fake:
        def generate(self, mesh_in, img, params, out):
            seen["in"] = mesh_in
            pathlib.Path(out).write_bytes(b"REFINED")
    monkeypatch.setattr(worker, "_refine", lambda: Fake())
    worker.mesh_refine.run(job_id="j", project_id="new1", source_project_id="src1")
    assert seen["in"] == str(src / "mesh.glb")
    assert (tmp_path / "default" / "new1" / "mesh.glb").read_bytes() == b"REFINED"
    assert (src / "mesh.glb").read_bytes() == b"SOURCE"
    assert r.hgetall("job:j")["state"] == "SUCCESS"
    get_settings.cache_clear()
