"""Kumaş simülasyonu worker. `clothsim.drape` ve `clothsim.sew3d`'yi `clothsim-cpu`
kuyruğunda dinler (sew3d = F2: 2D kalıbı mankene dikip yeni proje mesh'i üretir).

Blender headless'ı bir subprocess olarak çağırır (`blender -b -P blender_drape.py
-- <in.glb> <out.glb> <frames> [collider.glb] [--fabric <json>]`), kaynak mesh'i manken/yer üstüne fizik-tabanlı
düşürür ve sonucu YENİ VARYANT GLB'si olarak proje dizinine yazar. Sonuç job'ında
`decal_path` (proje-göreli) döner → mevcut /variations reconcile onu result_path'e
yazar (varyasyon deseni).

GPU YOK (CPU-only) — tek-GPU sözleşmesi ETKİLENMEZ. Blender binary PATH'te (ya da
`BLENDER_BIN`) bulunamazsa task FAILURE(error="blender-missing") verir; kurulum
README'de (apt install blender).
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
import threading
import uuid
from collections import deque
from pathlib import Path

from common.celery_app import celery_app  # noqa: E402
from common.config import get_settings  # noqa: E402
from common.db_write import set_mesh_path as _set_mesh_path  # noqa: E402
from common.db_write import set_thumbnail_path as _set_thumbnail_path  # noqa: E402
from common.fabrics import blender_params  # noqa: E402
from common.jobs import JobStore  # noqa: E402

# Blender binary adı/ yolu (override edilebilir). Yoksa task "blender-missing".
BLENDER_BIN = os.getenv("BLENDER_BIN", "blender")
# Sim tek bir mesh için CPU'da dakikalar sürebilir; makul üst sınır.
_TIMEOUT_S = int(os.getenv("CLOTHSIM_TIMEOUT_S", "1800"))


def _find_blender() -> str | None:
    """PATH'te (ya da mutlak BLENDER_BIN yolunda) blender binary'sini bul."""
    p = Path(BLENDER_BIN)
    if p.is_absolute():
        return str(p) if p.exists() and os.access(p, os.X_OK) else None
    return shutil.which(BLENDER_BIN)


def _script_path() -> Path:
    return Path(__file__).with_name("blender_drape.py")


@celery_app.task(name="clothsim.drape", bind=True)
def drape(self, job_id: str, project_id: str, mannequin_id: str | None = None,
          frames: int = 60, fabric_id: str | None = None) -> dict:
    """fabric_id (opsiyonel, common.fabrics): verilirse o kumaşın Blender ayarları
    geçici JSON'a yazılıp script'e `--fabric <json>` ile geçer; None → eski
    (denim) davranış, bayrak hiç eklenmez (geriye uyum)."""
    store = JobStore()
    settings = get_settings()
    fabric_json: str | None = None
    try:
        store.set_state(job_id, "STARTED")
        blender = _find_blender()
        if not blender:
            # Kurulum yoksa BEST-EFFORT sözleşmesi gereği net hata (raise değil):
            # kullanıcı README'deki `apt install blender` adımına yönlendirilir.
            store.fail(job_id, "blender-missing")
            return {"error": "blender-missing"}

        base = Path(settings.projects_dir) / "default"
        src = base / project_id / "mesh_view.glb"
        if not src.exists():
            src = base / project_id / "mesh.glb"
        if not src.exists():
            raise RuntimeError(f"Kaynak mesh yok: {src}")

        store.set_progress(job_id, "drape", 20)
        rel = f"variations/drape_{uuid.uuid4().hex}.glb"
        out = base / project_id / rel
        out.parent.mkdir(parents=True, exist_ok=True)

        cmd = [blender, "-b", "-P", str(_script_path()), "--",
               str(src), str(out), str(int(frames))]
        # Manken GLB'si varsa collider olarak Blender script'ine geçir (opsiyonel).
        if mannequin_id:
            mann = (Path(settings.templates_dir) / "mannequins" / f"{mannequin_id}.glb")
            if mann.exists():
                cmd.append(str(mann))
        if fabric_id:
            try:
                params = blender_params(fabric_id)
            except KeyError as exc:
                raise RuntimeError(str(exc.args[0])) from None
            fd, fabric_json = tempfile.mkstemp(prefix="fabric_", suffix=".json")
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(params, fh)
            cmd += ["--fabric", fabric_json]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=_TIMEOUT_S)
        if proc.returncode != 0 or not out.exists():
            tail = (proc.stderr or proc.stdout or "")[-800:]
            raise RuntimeError(f"Blender drape başarısız (rc={proc.returncode}): {tail}")

        store.set_progress(job_id, "pack", 95)
        # decal_path anahtarı → mevcut /variations reconcile'ı sonucu result_path'e
        # yazar; drape_path da açıkça verilir (semantik netlik).
        result = {"project_id": project_id, "drape_path": rel, "decal_path": rel}
        if fabric_id:
            result["fabric_id"] = fabric_id
        store.succeed(job_id, result)
        return result
    except Exception as exc:  # noqa: BLE001
        store.fail(job_id, str(exc))
        raise
    finally:
        if fabric_json:
            try:
                os.unlink(fabric_json)
            except OSError:
                pass


def _apply_dress(proj_dir: Path, fitted: Path, side: dict, meas: dict, database_url: str) -> None:
    """Otomatik akış: giydirilmiş kıyafeti projeye uygula (gateway apply_variant ile aynı
    sözleşme: mesh.glb yedeklenir, görüntüleyici kopyaları silinir) + manken ayarı ve
    ölçü tablosu customizations'a yazılır."""
    import time

    from common.db_write import merge_customizations
    mesh = proj_dir / "mesh.glb"
    if mesh.exists():
        shutil.copy2(mesh, proj_dir / f"mesh.glb.bak-{int(time.time())}")
    shutil.copy2(fitted, mesh)
    for view in proj_dir.glob("mesh_view*.glb"):
        try:
            view.unlink()
        except OSError:
            pass
    _set_mesh_path(database_url, proj_dir.name, str(mesh))
    merge_customizations(database_url, proj_dir.name, {
        "mannequin": {"id": side["mannequin_id"], "visible": True, "opacity": 0.7,
                      "transform": side["transform"], "fitted": True, "posed": side["posed"]},
        "measurements": meas,
    })


def _sewn_transform(report: Path, base_glb: str) -> dict | None:
    """Atölyede dikilmiş kıyafet: dikildiği mankenin boyu + mesh normalize bilgisi
    (sew_report.json) bilinir → manken hizası TAHMİNSİZ, birebir hesaplanır."""
    try:
        rep = json.loads(report.read_text(encoding="utf-8"))
        k = float(rep["normalize"]["scale"])
        center = [float(c) for c in rep["normalize"]["center_m"]]
        hm = float(rep["mannequin"]["height_m"])
    except (OSError, ValueError, KeyError, TypeError):
        return None
    import trimesh
    v = trimesh.load(base_glb, force="mesh", process=False).vertices
    lo, hi = v.min(axis=0), v.max(axis=0)
    unit = hm / float(hi[1] - lo[1])              # yerel birim → metre
    anchor = [0.5 * (lo[0] + hi[0]), lo[1], 0.5 * (lo[2] + hi[2])]  # ayak tabanı, XZ merkez
    pos = [(-anchor[i] * unit - center[i]) * k for i in range(3)]
    return {"position": pos, "rotation": [0, 0, 0], "scale": unit * k, "anchor": "sew_report"}


@celery_app.task(name="clothsim.fit", bind=True)
def fit(self, job_id: str, project_id: str, mannequin_id: str, transform: dict | None = None,
        margin: float = 0.012, garment_type: str = "shirt", auto_apply: bool = False) -> dict:
    """Mankene giydir (dress.py): otomatik hiza (transform None) + kolları kolluklara
    pozla + kolluk ince hizası + beden içinde kalan kumaşı dışarı it. Blender gerekmez.
    Çıktı: varyant kıyafet GLB'si + projeye özel pozlu manken GLB'si + yan bilgi JSON'u
    (apply_variant bunu okuyup projenin manken ayarını günceller)."""
    store = JobStore()
    settings = get_settings()
    try:
        store.set_state(job_id, "STARTED")
        base = Path(settings.projects_dir) / "default"
        src = base / project_id / "mesh.glb"
        if not src.exists():
            raise RuntimeError("Projede mesh yok.")
        mann = Path(settings.templates_dir) / "mannequins" / f"{mannequin_id}.glb"
        if not mann.exists():
            raise RuntimeError(f"Manken bulunamadı: {mannequin_id}")
        store.set_progress(job_id, "fit", 30)
        tag = uuid.uuid4().hex
        rel = f"variations/fit_{tag}.glb"
        posed = f"mannequin_{tag}.glb"
        out = base / project_id / rel
        out.parent.mkdir(parents=True, exist_ok=True)
        from clothsim_worker.dress import dress_glb, tpose_base
        if transform is None:
            transform = _sewn_transform(base / project_id / "sew_report.json", tpose_base(str(mann)))
        rep = dress_glb(str(src), str(mann), garment_type, str(out),
                        str(out.parent / posed), transform=transform, margin=float(margin))
        meas = rep.get("measurements") or {}
        meas_doc = {**meas, "mannequin_id": mannequin_id, "garment_type": garment_type}
        side = {"mannequin_id": mannequin_id, "transform": rep["transform"], "posed": posed,
                "measurements": meas_doc}
        out.with_suffix(".json").write_text(json.dumps(side, ensure_ascii=False), encoding="utf-8")
        (base / project_id / "measurements.json").write_text(
            json.dumps(meas_doc, ensure_ascii=False, indent=1), encoding="utf-8")
        if auto_apply:
            _apply_dress(base / project_id, out, side, meas_doc, settings.database_url)
        store.set_progress(job_id, "pack", 95)
        result = {"project_id": project_id, "drape_path": rel, "decal_path": rel,
                  "posed": posed, "transform": json.dumps(rep["transform"]),
                  "anchor": rep.get("anchor", "")}
        store.succeed(job_id, result)
        return result
    except Exception as exc:  # noqa: BLE001
        store.fail(job_id, str(exc))
        raise


# --- F2: 2D kalıbı 3D'de mankene dikme ---------------------------------------------
# Dikiş simülasyonu drape'ten uzun sürer (CPU, ~1-3 dk + önizleme render'ı).
_SEW_TIMEOUT_S = int(os.getenv("CLOTHSIM_SEW_TIMEOUT_S", "2400"))
_FRAME_RE = re.compile(r"\[sew\] kare (\d+)/(\d+)")


def _sew_script_path() -> Path:
    return Path(__file__).with_name("blender_sew.py")


def _normalize_glb(path: Path) -> dict:
    """GLB'yi kanonik görüntüleme çerçevesine al (merkez orijin, en büyük kenar 1 →
    [-0.5, 0.5]; diğer motorların mesh.glb'leri gibi). Tasarımcı mesh'i olduğu gibi
    gösterir; metre ölçekli manken uzayındaki kıyafet kameranın dışında kalıyordu.

    Mesh/malzeme ikili verisine dokunulmaz: sahnenin köklerinin üstüne ölçek+öteleme
    taşıyan tek bir düğüm eklenir. Döner: {scale, center_m} (metre = norm/scale + center).
    """
    import struct

    import numpy as np
    import trimesh

    lo, hi = trimesh.load(path).bounds
    center = (lo + hi) / 2.0
    ext = float((hi - lo).max())
    if ext <= 0:
        raise RuntimeError("Dikilen kıyafet boş çıktı (sınır kutusu yok).")
    scale = 1.0 / ext

    raw = path.read_bytes()
    jlen = struct.unpack_from("<I", raw, 12)[0]
    gltf = json.loads(raw[20:20 + jlen])
    rest = raw[20 + jlen:]
    scene = gltf["scenes"][gltf.get("scene", 0)]
    gltf.setdefault("nodes", []).append({
        "name": "normalize", "children": list(scene.get("nodes", [])),
        "scale": [scale] * 3, "translation": [float(-c * scale) for c in center],
    })
    scene["nodes"] = [len(gltf["nodes"]) - 1]
    js = json.dumps(gltf, separators=(",", ":")).encode("utf-8")
    js += b" " * (-len(js) % 4)
    total = 12 + 8 + len(js) + len(rest)
    path.write_bytes(struct.pack("<4sII", b"glTF", 2, total)
                     + struct.pack("<I4s", len(js), b"JSON") + js + rest)
    return {"scale": round(scale, 6), "center_m": [round(float(c), 6) for c in np.asarray(center)]}


def _run_blender_sew(cmd: list[str], job_id: str, store: JobStore) -> tuple[int, str]:
    """Blender'ı çalıştır; '[sew] kare f/N' satırlarından ilerlemeyi (20→85) yayınla.
    Zaman aşımında süreç öldürülür. Döner: (returncode, çıktının son satırları)."""
    tail: deque[str] = deque(maxlen=60)
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True, bufsize=1)
    timed_out = threading.Event()

    def _kill() -> None:
        timed_out.set()
        proc.kill()

    timer = threading.Timer(_SEW_TIMEOUT_S, _kill)
    timer.start()
    try:
        assert proc.stdout is not None
        for line in proc.stdout:
            tail.append(line)
            m = _FRAME_RE.search(line)
            if m:
                f, n = int(m.group(1)), max(1, int(m.group(2)))
                store.set_progress(job_id, "sim", 20 + int(65 * f / n))
        proc.wait()
    finally:
        timer.cancel()
    if timed_out.is_set():
        raise RuntimeError(f"Dikiş simülasyonu {_SEW_TIMEOUT_S} sn içinde bitmedi (zaman aşımı).")
    return proc.returncode, "".join(tail)


@celery_app.task(name="clothsim.sew3d", bind=True)
def sew3d(self, job_id: str, project_id: str, pattern_id: str, mannequin_id: str,
          fabric_id: str = "cotton", frames: int = 120) -> dict:
    """F1 kalıbını (data/patterns/<id>/pieces.json) mankene diker → projenin kanonik
    `mesh.glb`'si + önizleme `thumbnail.png`'si (mankenli, ön görünüş).

    Geometri hazırlığı saf Python'da (`sew_prep`), simülasyon Blender'da
    (`blender_sew.py`). Taban mankenler (female-a/male-a/neutral-t) kalıbın ölçülerine
    morflanır; özel (custom-*) mankenler olduğu gibi kullanılır. GPU YOK."""
    store = JobStore()
    settings = get_settings()
    work: str | None = None
    try:
        store.set_state(job_id, "STARTED")
        blender = _find_blender()
        if not blender:
            store.fail(job_id, "blender-missing")
            return {"error": "blender-missing"}

        from common.fabrics import get_fabric
        from common.patterns import PatternError, pattern_path

        from clothsim_worker.sew_prep import SewPrepError, build_sew_input, prepare_mannequin

        try:
            pdir = pattern_path(pattern_id)
        except PatternError:
            raise RuntimeError("Kalıp bulunamadı.") from None
        pieces_file = pdir / "pieces.json"
        if not pieces_file.is_file():
            raise RuntimeError("Kalıp bulunamadı (pieces.json yok).")
        pieces = json.loads(pieces_file.read_text(encoding="utf-8"))
        meta_file = pdir / "meta.json"
        meta = json.loads(meta_file.read_text(encoding="utf-8")) if meta_file.is_file() else {}
        mann = Path(settings.templates_dir) / "mannequins" / f"{mannequin_id}.glb"
        if not mann.is_file():
            raise RuntimeError(f"Manken bulunamadı: {mannequin_id}")
        try:
            params = blender_params(fabric_id)
        except KeyError as exc:
            raise RuntimeError(str(exc.args[0])) from None
        fabric = get_fabric(fabric_id) or {}

        store.set_progress(job_id, "prep", 8)
        bv, bf, minfo = prepare_mannequin(str(mann), mannequin_id, meta.get("body"))
        try:
            data = build_sew_input(pieces, bv, bf, params, int(frames), meta=meta)
        except SewPrepError as exc:
            raise RuntimeError(str(exc)) from None
        data["pbr"] = fabric.get("pbr") or {}
        data["sim"] = {}

        work = tempfile.mkdtemp(prefix="sew3d_")
        in_json = Path(work) / "input.json"
        in_json.write_text(json.dumps(data), encoding="utf-8")
        tmp_glb = Path(work) / "mesh.glb"
        report = Path(work) / "report.json"
        prefix = Path(work) / "preview"
        store.set_progress(job_id, "sim", 20)
        cmd = [blender, "-b", "-P", str(_sew_script_path()), "--", str(in_json), str(tmp_glb),
               "--preview", str(prefix), "--report", str(report)]
        rc, tail = _run_blender_sew(cmd, job_id, store)
        if rc != 0 or not tmp_glb.is_file():
            raise RuntimeError(f"Dikiş simülasyonu başarısız (Blender rc={rc}): {tail[-800:]}")

        store.set_progress(job_id, "pack", 90)
        proj_dir = Path(settings.projects_dir) / "default" / project_id
        proj_dir.mkdir(parents=True, exist_ok=True)
        mesh_file = proj_dir / "mesh.glb"
        shutil.move(str(tmp_glb), str(mesh_file))
        # Manken uzayındaki metre ölçekli kopya saklanır; mesh.glb kanonik çerçeveye alınır.
        shutil.copyfile(mesh_file, proj_dir / "mesh_metric.glb")
        norm = _normalize_glb(mesh_file)
        rep = json.loads(report.read_text(encoding="utf-8")) if report.is_file() else {}
        rep["normalize"] = norm
        thumb = None
        for view in ("front", "side"):
            src = Path(f"{prefix}_{view}.png")
            if src.is_file():
                shutil.copyfile(src, proj_dir / f"sew_preview_{view}.png")
                if view == "front":
                    thumb = proj_dir / "thumbnail.png"
                    shutil.copyfile(src, thumb)
        rep.pop("coords_gltf", None)
        rep["previews"] = [p.name for p in proj_dir.glob("sew_preview_*.png")]
        rep.update({"pattern_id": pattern_id, "design": pieces.get("design"),
                    "mannequin_id": mannequin_id, "mannequin": minfo, "fabric_id": fabric_id,
                    "warnings": data.get("warnings", []), "placement": data.get("placement")})
        (proj_dir / "sew_report.json").write_text(json.dumps(rep, ensure_ascii=False, indent=1),
                                                  encoding="utf-8")
        _set_mesh_path(settings.database_url, project_id, str(mesh_file))
        if thumb is not None:
            _set_thumbnail_path(settings.database_url, project_id, str(thumb))
        gap = rep.get("seam_gap_mm") or {}
        stretch = rep.get("edge_stretch") or {}
        result = {
            "project_id": project_id,
            "pattern_id": pattern_id,
            "mannequin_id": mannequin_id,
            "fabric_id": fabric_id,
            "frames": int(frames),
            "metrics": {
                "seam_gap_max_mm": round(float(gap.get("max", 0.0)), 1),
                "seam_gap_median_mm": round(float(gap.get("median", 0.0)), 2),
                "edge_stretch_median": round(float(stretch.get("median", 1.0)), 3),
                "sim_seconds": rep.get("sim_seconds"),
            },
            "warnings": data.get("warnings", []),
        }
        store.succeed(job_id, result)
        return result
    except Exception as exc:  # noqa: BLE001
        store.fail(job_id, str(exc))
        raise
    finally:
        if work:
            shutil.rmtree(work, ignore_errors=True)


@celery_app.task(name="engine.status")
def engine_status() -> dict:
    """CPU worker — GPU raporu yok; katalog/durum paneliyle uyumlu boş rapor."""
    return {"gpu": "", "loaded": [], "reserved_mb": 0, "allocated_mb": 0}


@celery_app.task(name="engine.release")
def engine_release(mode: str = "cache") -> dict:
    # CPU worker; boşaltılacak model resident değil.
    return {"mode": mode, "unloaded": []}
