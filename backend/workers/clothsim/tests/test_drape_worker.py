"""clothsim worker testleri: import-smoke + Blender'sız FAILURE yolu.

Hermetik: worker src'i PYTHONPATH'e eklenir (bpy YOKTUR, blender_drape.py IMPORT
EDİLMEZ); JobStore fakeredis'e bağlanır; blender bulunamadığı simüle edilir. Gerçek
sim (bpy/blender) canlı doğrulamaya bırakılır.
"""
import json
import math
import pathlib
import shutil
import subprocess
import sys

import fakeredis
import pytest

# Worker src'ini import edilebilir yap (common venv'de kurulu; clothsim_worker değil).
_SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

# Bilinen yerel Blender kurulumu (CPU); yoksa PATH'e düş.
import os as _os, shutil as _shutil
_BLENDER = _os.getenv("BLENDER_BIN") or _shutil.which("blender") or _os.path.join(_os.getenv("ENGINES_DIR", str(pathlib.Path(__file__).resolve().parents[4] / "engines")), "blender", "blender")


def _blender_bin() -> str | None:
    if pathlib.Path(_BLENDER).exists():
        return _BLENDER
    return shutil.which("blender")


def test_import_smoke_registers_task():
    """Worker modülü import edilebilir + task doğru isimle kayıtlı."""
    from clothsim_worker import worker
    assert worker.drape.name == "clothsim.drape"
    # blender_drape.py bpy'siz IMPORT EDİLMEZ; ama script yol yardımcısı onu gösterir.
    assert worker._script_path().name == "blender_drape.py"


def test_drape_fails_blender_missing(monkeypatch):
    """Blender binary yoksa task FAILURE(error='blender-missing') verir (raise etmez)."""
    from clothsim_worker import worker
    fake = fakeredis.FakeStrictRedis(decode_responses=True)
    from common.jobs import JobStore
    store = JobStore(fake)
    monkeypatch.setattr(worker, "JobStore", lambda: store)
    # PATH'te blender yok gibi davran.
    monkeypatch.setattr(worker.shutil, "which", lambda name: None)
    monkeypatch.setattr(worker, "BLENDER_BIN", "blender")

    result = worker.drape(job_id="j1", project_id="p1", frames=40)
    assert result == {"error": "blender-missing"}
    hash_ = fake.hgetall("job:j1")
    assert hash_["state"] == "FAILURE"
    assert hash_["error"] == "blender-missing"


def test_find_blender_uses_which(monkeypatch):
    from clothsim_worker import worker
    monkeypatch.setattr(worker.shutil, "which", lambda name: "/usr/bin/blender")
    monkeypatch.setattr(worker, "BLENDER_BIN", "blender")
    assert worker._find_blender() == "/usr/bin/blender"


def _make_cloth_glb(path: str) -> None:
    """Alt-bölünmüş, 3B'de eğik bir düzlem-ızgara üret ve GLB olarak yaz.

    Kumaş gibi kıvrılabilmesi için yeterli çözünürlük (21x21 vertex = 800 üçgen)
    ve sıfır-olmayan Z-aralığı (eğim) gerekir → askı pini üst %12'yi yakalar,
    yerçekimi alt kısmı sarkıtır.
    """
    import numpy as np
    import trimesh

    n = 21
    lin = np.linspace(-1.0, 1.0, n)
    gx, gy = np.meshgrid(lin, lin)
    verts = np.column_stack([gx.ravel(), gy.ravel(), np.zeros(n * n)])
    # X ve Y eksenleri etrafında eğ → her eksende varyasyon + belirgin bir üst köşe.
    ax, ay = math.radians(70.0), math.radians(20.0)
    rx = np.array([[1, 0, 0],
                   [0, math.cos(ax), -math.sin(ax)],
                   [0, math.sin(ax), math.cos(ax)]])
    ry = np.array([[math.cos(ay), 0, math.sin(ay)],
                   [0, 1, 0],
                   [-math.sin(ay), 0, math.cos(ay)]])
    verts = verts @ rx.T @ ry.T
    faces = []
    for i in range(n - 1):
        for j in range(n - 1):
            a = i * n + j
            b = i * n + (j + 1)
            c = (i + 1) * n + j
            d = (i + 1) * n + (j + 1)
            faces.append([a, b, d])
            faces.append([a, d, c])
    mesh = trimesh.Trimesh(vertices=verts, faces=np.array(faces), process=False)
    mesh.export(path)


@pytest.mark.skipif(_blender_bin() is None, reason="blender binary yok")
def test_drape_deforms_cloth_real_blender(tmp_path):
    """Gerçek Blender ile: askılı sim çıktısı GİRDİDEN farklı bbox üretir (deformasyon).

    Regresyon koruması: pin OLMADAN kumaş bir bütün olarak düşer (yalnız öteleme,
    bbox aynı) → viewer'da "hiçbir şey olmadı". Pin ile omuzdan asılıp sarkar →
    bbox uzanımları değişir. Ayrıca zemin/collider düzlemi çıktıya SIZMAMALI (1 mesh).
    """
    import trimesh

    blender = _blender_bin()
    src = str(tmp_path / "in.glb")
    out = str(tmp_path / "out.glb")
    _make_cloth_glb(src)

    script = _SRC / "clothsim_worker" / "blender_drape.py"
    cmd = [blender, "-b", "-P", str(script), "--", src, out, "30"]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=110)
    assert proc.returncode == 0, f"blender rc={proc.returncode}\n{proc.stderr[-1500:]}"
    assert pathlib.Path(out).exists(), "çıktı GLB yazılmadı"

    # Çıktıda TAM 1 mesh geometrisi olmalı (zemin/collider düzlemi sızmamalı).
    scene = trimesh.load(out, force="scene")
    geoms = [g for g in scene.geometry.values()
             if isinstance(g, trimesh.Trimesh) and len(g.faces) > 0]
    assert len(geoms) == 1, f"çıktıda {len(geoms)} mesh (1 bekleniyordu)"

    ext_in = sorted(trimesh.load(src, force="mesh").extents.tolist())
    ext_out = sorted(trimesh.load(out, force="mesh").extents.tolist())
    # En az bir eksende >%1 fark = gerçek deformasyon (yalnız öteleme DEĞİL).
    rel = [abs(a - b) / max(a, 1e-9) for a, b in zip(ext_in, ext_out)]
    assert max(rel) > 0.01, f"bbox uzanımları neredeyse aynı: in={ext_in} out={ext_out}"


# --- Kumaş (fabric_id) entegrasyonu ---------------------------------------------
def _fake_run_env(monkeypatch, tmp_path):
    """Worker'ı sahte proje dizini + sahte blender + yakalanan subprocess ile kur."""
    from clothsim_worker import worker
    from common.jobs import JobStore
    fake = fakeredis.FakeStrictRedis(decode_responses=True)
    store = JobStore(fake)
    monkeypatch.setattr(worker, "JobStore", lambda: store)
    proj = tmp_path / "projects" / "default" / "p1"
    proj.mkdir(parents=True)
    (proj / "mesh_view.glb").write_bytes(b"glb")

    class _S:
        projects_dir = str(tmp_path / "projects")
        templates_dir = str(tmp_path / "templates")
    monkeypatch.setattr(worker, "get_settings", lambda: _S())
    monkeypatch.setattr(worker, "_find_blender", lambda: "/fake/blender")
    seen = {}

    def fake_run(cmd, **_):
        seen["cmd"] = list(cmd)
        if "--fabric" in cmd:
            p = cmd[cmd.index("--fabric") + 1]
            with open(p, encoding="utf-8") as fh:
                seen["fabric"] = json.load(fh)
        pathlib.Path(cmd[cmd.index("--") + 2]).write_bytes(b"out")
        return subprocess.CompletedProcess(cmd, 0, "", "")
    monkeypatch.setattr(worker.subprocess, "run", fake_run)
    return worker, fake, seen


def test_drape_without_fabric_keeps_legacy_argv(monkeypatch, tmp_path):
    """fabric_id yok → argv eskisiyle aynı (--fabric bayrağı EKLENMEZ)."""
    worker, fake, seen = _fake_run_env(monkeypatch, tmp_path)
    res = worker.drape(job_id="j2", project_id="p1", frames=12)
    assert "--fabric" not in seen["cmd"]
    assert seen["cmd"][-1] == "12"
    assert "fabric_id" not in res
    assert fake.hgetall("job:j2")["state"] == "SUCCESS"


def test_drape_with_fabric_writes_params_json(monkeypatch, tmp_path):
    from common.fabrics import blender_params
    worker, fake, seen = _fake_run_env(monkeypatch, tmp_path)
    res = worker.drape(job_id="j3", project_id="p1", frames=12, fabric_id="silk")
    assert seen["fabric"] == blender_params("silk")
    # Geçici JSON iş bitince silinir.
    assert not pathlib.Path(seen["cmd"][seen["cmd"].index("--fabric") + 1]).exists()
    assert res["fabric_id"] == "silk"


def test_drape_unknown_fabric_fails_turkish(monkeypatch, tmp_path):
    worker, fake, seen = _fake_run_env(monkeypatch, tmp_path)
    with pytest.raises(RuntimeError, match="Bilinmeyen kumaş"):
        worker.drape(job_id="j4", project_id="p1", frames=12, fabric_id="kadife")
    assert fake.hgetall("job:j4")["state"] == "FAILURE"
    assert "cmd" not in seen  # blender hiç çağrılmadı


def _drape_sheet(blender: str, tmp_path, fabric_id: str) -> "object":
    """Üst kenarından asılı 2x2 m ızgarayı (yerden 1.5 m) verilen kumaşla drape et."""
    import numpy as np
    import trimesh
    from common.fabrics import blender_params
    src = tmp_path / "sheet.glb"
    if not src.exists():
        n = 21
        lin = np.linspace(-1.0, 1.0, n)
        gx, gy = np.meshgrid(lin, lin)
        # glTF Y-up: yükseklik = y; z=-1 kenarı en yüksek → askı pini oraya düşer.
        verts = np.column_stack([gx.ravel(), 1.5 + 0.05 * (gy.ravel() + 1), -gy.ravel()])
        faces = []
        for i in range(n - 1):
            for j in range(n - 1):
                a = i * n + j
                faces += [[a, a + 1, a + n + 1], [a, a + n + 1, a + n]]
        trimesh.Trimesh(verts, np.array(faces), process=False).export(src)
    fj = tmp_path / f"{fabric_id}.json"
    fj.write_text(json.dumps(blender_params(fabric_id)))
    out = tmp_path / f"{fabric_id}.glb"
    script = _SRC / "clothsim_worker" / "blender_drape.py"
    proc = subprocess.run([blender, "-b", "-P", str(script), "--", str(src), str(out),
                           "60", "--fabric", str(fj)], capture_output=True, text=True,
                          timeout=300)
    assert proc.returncode == 0, proc.stderr[-1500:]
    return trimesh.load(out, force="mesh")


@pytest.mark.skipif(_blender_bin() is None, reason="blender binary yok")
def test_fabric_changes_real_drape_silk_vs_leather(tmp_path):
    """Gerçek Blender: aynı kumaş-ızgarası yere değip yığılırken ipek dar ve sıkı
    katlanır (yatay yayılım küçük), deri sert olduğu için geniş kavisle yayılır."""
    blender = _blender_bin()
    silk = _drape_sheet(blender, tmp_path, "silk")
    leather = _drape_sheet(blender, tmp_path, "leather")
    # extents: [x, y(yükseklik), z(yerdeki yayılım)]
    assert silk.extents[2] < 0.85 * leather.extents[2], (silk.extents, leather.extents)
