"""Terzi ölçü tablosu (cm doğruluğu) + otomatik uygulama (mesh yedeği, DB customizations)."""
from __future__ import annotations

import json
import math
import pathlib
import sqlite3
import sys

import numpy as np
import pytest
import trimesh

_SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from clothsim_worker import dress as D  # noqa: E402
from clothsim_worker.measure import measure  # noqa: E402

MQ = pathlib.Path(__file__).resolve().parents[4] / "data/templates/mannequins/female-a.glb"


@pytest.mark.skipif(not MQ.exists(), reason="manken GLB yok")
def test_measure_circumference_in_cm():
    b = trimesh.load(MQ, force="mesh", process=False)
    v, f = np.asarray(b.vertices, float), np.asarray(b.faces)
    lm = D.body_landmarks(v, f)
    s, pos = 2.0, np.array([0.0, -0.4, 0.0])
    body = v * s + pos
    arm = D.arm_vertices(v, lm)
    # Gövdeyi saran silindir kıyafet: yarıçap r → çevre 2πr (kıyafet birimi).
    r = 0.25
    th = np.linspace(0, 2 * math.pi, 64, endpoint=False)
    ys = np.linspace(lm["levels"]["hip"] * s + pos[1], lm["shoulder_y"] * s + pos[1], 40)
    g = np.array([[r * math.cos(t), y, r * math.sin(t)] for y in ys for t in th])
    out = measure(g, body, arm, lm, s, pos, 1.65, "tshirt", {})
    cm = out["cm_per_unit"]
    assert abs(cm - 165.0 / (lm["H"] * s)) < 1e-4   # rapor 4 basamağa yuvarlar
    rows = {r_["key"]: r_ for r_ in out["rows"]}
    expected = 2 * math.pi * r * cm
    assert abs(rows["chest"]["garment_cm"] - expected) / expected < 0.02
    assert rows["chest"]["body_cm"] > 0 and rows["chest"]["ease_cm"] > 0
    assert abs(rows["length"]["garment_cm"] - (ys[-1] - ys[0]) * cm) < 1.0


def test_apply_dress_backs_up_and_writes_db(tmp_path, monkeypatch):
    from clothsim_worker import worker as W
    db = tmp_path / "t.db"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE projects (id TEXT PRIMARY KEY, mesh_path TEXT, customizations TEXT)")
    con.execute("INSERT INTO projects VALUES ('p1', NULL, ?)", (json.dumps({"color": "#fff", "decals": []}),))
    con.commit()
    con.close()
    monkeypatch.setenv("PROJECTS_DIR", str(tmp_path / "projects"))
    from common.config import get_settings
    get_settings.cache_clear()
    proj = tmp_path / "projects" / "default" / "p1"
    proj.mkdir(parents=True)
    (proj / "mesh.glb").write_bytes(b"old")
    (proj / "mesh_view.glb").write_bytes(b"view")
    fitted = proj / "variations" / "fit_x.glb"
    fitted.parent.mkdir()
    fitted.write_bytes(b"new")
    side = {"mannequin_id": "custom-1", "transform": {"scale": 2.0}, "posed": "mannequin_x.glb"}
    W._apply_dress(proj, fitted, side, {"rows": [{"key": "chest", "garment_cm": 100}]}, f"sqlite:///{db}")
    assert (proj / "mesh.glb").read_bytes() == b"new"
    assert any(p.read_bytes() == b"old" for p in proj.glob("mesh.glb.bak-*"))
    assert not (proj / "mesh_view.glb").exists()
    con = sqlite3.connect(db)
    mesh_path, cust = con.execute("SELECT mesh_path, customizations FROM projects WHERE id='p1'").fetchone()
    c = json.loads(cust)
    assert c["color"] == "#fff" and c["mannequin"]["posed"] == "mannequin_x.glb"
    assert c["measurements"]["rows"][0]["garment_cm"] == 100 and mesh_path
    get_settings.cache_clear()
