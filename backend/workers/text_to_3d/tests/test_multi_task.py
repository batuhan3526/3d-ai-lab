import types

import fakeredis
import text_to_3d.trellis_worker as w
from common.jobs import JobStore


def test_multi_task_resolves_names_and_calls_generate_multi(monkeypatch, tmp_path):
    calls = {}

    class _Eng:
        def generate_multi(self, paths, gt, params, out):
            calls["paths"] = paths
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(b"glb")
            return out

    monkeypatch.setattr(w, "_get_engine", lambda eid: _Eng())
    store = JobStore(fakeredis.FakeStrictRedis(decode_responses=True))
    store.create("j", {"project_id": "p"})
    monkeypatch.setattr(w, "JobStore", lambda *a, **k: store)
    monkeypatch.setattr(w, "_set_mesh_path", lambda *a, **k: None)
    monkeypatch.setattr(w, "get_settings", lambda: types.SimpleNamespace(
        projects_dir=str(tmp_path / "projects"),
        uploads_dir=str(tmp_path / "uploads"),
        database_url="sqlite:///x"))
    r = w.generate_multi_image_to_3d.run(
        job_id="j", project_id="p", image_names=["a.png", "b.png"],
        garment_type="boots", engine_id="trellis-image", quality="fast")
    assert r["project_id"] == "p"
    # worker uploads_dir + filename ile cozer
    assert calls["paths"][0].endswith("a.png")
    assert calls["paths"][1].endswith("b.png")
    assert (tmp_path / "uploads") .as_posix() in calls["paths"][0].replace("\\", "/")
    assert store.get("j")["state"] == "SUCCESS"
