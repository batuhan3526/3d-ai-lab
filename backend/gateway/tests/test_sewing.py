"""Dikiş kalıbı testleri — POST /projects/{id}/sewing-pattern + GET svg/pdf.

Hermetik: her test tmp_path SQLite + PROJECTS_DIR kullanır (gerçek data/ dizinine
yazmaz), env monkeypatch + get_settings.cache_clear + db.reset_engine ile izole
edilir (test_print_prep.py deseni). Test mesh gerçek trimesh çağrılarıyla üretilir
(monkeypatch yok — trimesh/xatlas gateway venv'inde kurulu). Basit silindir kullanılır.
"""
from __future__ import annotations

import time
from pathlib import Path

import numpy as np
import pytest
import trimesh
from fastapi.testclient import TestClient

AUTH = {"Authorization": "Bearer test-token-bootstrap"}


@pytest.fixture
def ctx(tmp_path, monkeypatch):
    db_path = str(tmp_path / "sewing.db").replace("\\", "/")
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
        "name": "Dikiş Tasarımı", "garment_type": "tshirt", "template_id": "tshirt-01",
        "customizations": {"color": "#ffffff", "decals": []},
    }, headers=AUTH).json()["id"]


def _write_cylinder(projects_dir: Path, pid: str) -> Path:
    """Basit kapalı silindir (Y-boyu 3 birim) — açıldığında ≥1 chart üretir."""
    cyl = trimesh.creation.cylinder(radius=1.0, height=3.0, sections=24)
    path = projects_dir / "default" / pid / "mesh.glb"
    path.parent.mkdir(parents=True, exist_ok=True)
    cyl.export(str(path))
    return path


# --- auth ----------------------------------------------------------------------
def test_requires_auth(ctx):
    client, _ = ctx
    pid = _make(client)
    assert client.post(f"/projects/{pid}/sewing-pattern", json={}).status_code == 401


# --- happy path ----------------------------------------------------------------
def test_charts_svg_pdf_and_scale(ctx):
    client, projects_dir = ctx
    pid = _make(client)
    _write_cylinder(projects_dir, pid)

    r = client.post(f"/projects/{pid}/sewing-pattern",
                    json={"height_cm": 60.0}, headers=AUTH)
    assert r.status_code == 200, r.text
    body = r.json()
    for key in ("svg_url", "pdf_url", "charts", "note"):
        assert key in body, f"eksik alan: {key}"

    assert body["note"] == "deneysel"
    assert body["svg_url"] == f"/projects/{pid}/sewing-pattern.svg"
    assert body["pdf_url"] == f"/projects/{pid}/sewing-pattern.pdf"

    charts = body["charts"]
    assert isinstance(charts, list) and len(charts) >= 1
    c0 = charts[0]
    # Chart sözleşmesi: polygon + seam_allowance + area_cm2.
    assert len(c0["polygon"]) >= 3
    assert len(c0["seam_allowance"]) == len(c0["polygon"])
    assert c0["area_cm2"] > 0

    # SVG + PDF diske yazıldı.
    svg = projects_dir / "default" / pid / "sewing-pattern.svg"
    pdf = projects_dir / "default" / pid / "sewing-pattern.pdf"
    assert svg.exists() and pdf.exists()
    # SVG mm birimindedir (1:1 ölçek) ve ölçek çubuğu notunu içerir.
    text = svg.read_text(encoding="utf-8")
    assert 'mm"' in text                     # width/height mm cinsinden
    assert "5 cm" in text and "dikiş payı" in text  # ölçek satırı
    assert text.count("<path") >= 2          # her chart: kesim + dikiş payı


def test_scale_absolute_area(ctx):
    """Ölçek doğru: toplam chart alanı diske yazılan mesh'in gerçek yüzey alanına
    (route'un Y-extent tabanlı mm ölçeğiyle) yakın olmalı. Route mantığını birebir
    yansıtmak için GLB'yi yeniden yükleyip aynı ölçeği hesaplarız (GLB export/reload
    birim/eksen dönüşümü uygulayabilir)."""
    client, projects_dir = ctx
    pid = _make(client)
    src = _write_cylinder(projects_dir, pid)
    reloaded = trimesh.load(str(src), force="mesh")
    scale_mm_per_unit = 600.0 / float(reloaded.extents[1])  # height_cm=60 → 600mm / Y-extent
    expected_cm2 = reloaded.area * (scale_mm_per_unit ** 2) / 100.0

    r = client.post(f"/projects/{pid}/sewing-pattern",
                    json={"height_cm": 60.0}, headers=AUTH)
    total = sum(c["area_cm2"] for c in r.json()["charts"])
    assert total == pytest.approx(expected_cm2, rel=0.05)


# --- serve svg / pdf -----------------------------------------------------------
def test_get_svg_and_pdf_public(ctx):
    client, projects_dir = ctx
    pid = _make(client)
    _write_cylinder(projects_dir, pid)
    client.post(f"/projects/{pid}/sewing-pattern", json={"height_cm": 60.0}, headers=AUTH)

    # GET public: Authorization header'sız erişilebilmeli (mesh servis deseni).
    rs = client.get(f"/projects/{pid}/sewing-pattern.svg")
    assert rs.status_code == 200
    assert rs.headers["content-type"] == "image/svg+xml"
    assert len(rs.content) > 0

    rp = client.get(f"/projects/{pid}/sewing-pattern.pdf")
    assert rp.status_code == 200
    assert rp.headers["content-type"] == "application/pdf"
    assert rp.content[:5] == b"%PDF-"


def test_get_before_build_404(ctx):
    client, _ = ctx
    pid = _make(client)
    assert client.get(f"/projects/{pid}/sewing-pattern.svg").status_code == 404
    assert client.get(f"/projects/{pid}/sewing-pattern.pdf").status_code == 404


# --- missing project / mesh ----------------------------------------------------
def test_missing_project_404(ctx):
    client, _ = ctx
    r = client.post("/projects/does-not-exist/sewing-pattern", json={}, headers=AUTH)
    assert r.status_code == 404


def test_missing_mesh_404(ctx):
    client, _ = ctx
    pid = _make(client)  # proje var ama mesh üretilmemiş
    r = client.post(f"/projects/{pid}/sewing-pattern", json={}, headers=AUTH)
    assert r.status_code == 404


# --- common.sewing birim: unfold ölçek doğrusallığı ----------------------------
def test_unfold_scale_linear(tmp_path):
    from common.sewing import unfold_to_charts
    cyl = trimesh.creation.cylinder(radius=1.0, height=3.0, sections=24)
    mp = tmp_path / "c.glb"
    cyl.export(str(mp))
    a = sum(c["area_cm2"] for c in unfold_to_charts(str(mp), 100.0))
    b = sum(c["area_cm2"] for c in unfold_to_charts(str(mp), 200.0))
    # Ölçek 2x → alan 4x (alan ölçekle karesel).
    assert b == pytest.approx(4.0 * a, rel=0.02)


# --- F5: büyük mesh decimation (perf) ------------------------------------------
def test_large_mesh_is_decimated_before_unfold(tmp_path):
    """>50k yüzlü mesh xatlas ÖNCESİ decimate edilmeli: faces_used <= MAX_UNFOLD_FACES,
    yüz sayıları raporlanmalı, chart'lar boş olmamalı. (İkosfer sub=6 ≈ 81920 yüz —
    decimation olmadan xatlas dakikalar sürer / segfault eder; bu test onu önler.)"""
    from common.sewing import MAX_UNFOLD_FACES, unfold_to_charts
    sphere = trimesh.creation.icosphere(subdivisions=6)
    assert len(sphere.faces) > MAX_UNFOLD_FACES  # ön koşul: decimation tetiklenmeli
    mp = tmp_path / "big.glb"
    sphere.export(str(mp))

    stats: dict = {}
    charts = unfold_to_charts(str(mp), 100.0, stats)
    assert stats["faces_in"] == len(sphere.faces)
    assert stats["faces_used"] <= MAX_UNFOLD_FACES
    assert stats["faces_used"] < stats["faces_in"]  # gerçekten küçüldü
    assert len(charts) >= 1
    assert all(len(c["polygon"]) >= 3 for c in charts)


def test_route_reports_face_counts(ctx):
    """Route yanıtı dürüstlük için faces_in/faces_used taşır (küçük mesh: eşit)."""
    client, projects_dir = ctx
    pid = _make(client)
    _write_cylinder(projects_dir, pid)
    r = client.post(f"/projects/{pid}/sewing-pattern",
                    json={"height_cm": 60.0}, headers=AUTH)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["faces_used"] is not None and body["faces_used"] > 0
    assert body["faces_in"] == body["faces_used"]  # silindir < 10k → decimation yok
    # Chart sayısı istatistikleri route yanıtında taşınır (modal için).
    assert body["charts_total"] is not None and body["charts_total"] >= 1
    assert body["charts_drawn"] == len(body["charts"])
    assert body["charts_dropped"] == body["charts_total"] - body["charts_drawn"]


# --- S1: parçalı mesh (motif-bake çorbası) — kaynak+bileşen+mikro-chart reçetesi ---
def _write_fragmented(projects_dir: Path, pid: str) -> Path:
    """Motif-bake mesh'ini taklit et: her yüz kendi 3 köşesine sahip (UV/normal
    dikişi köşe kopyalar) → yüzler kopuk → yüklendiğinde binlerce bileşen. Kaynak
    (merge_tex+merge_norm) bunları tek bileşene indirmeli."""
    base = trimesh.creation.icosphere(subdivisions=3)  # 1280 yüz, kaynaklı
    v = base.vertices[base.faces].reshape(-1, 3)        # her yüz kendi köşeleri
    f = np.arange(len(v)).reshape(-1, 3)
    frag = trimesh.Trimesh(vertices=v, faces=f, process=False)
    path = projects_dir / "default" / pid / "mesh.glb"
    path.parent.mkdir(parents=True, exist_ok=True)
    frag.export(str(path))
    return path


def test_fragmented_mesh_merged_and_sane(tmp_path):
    """Parçalı mesh: kaynaştırma bileşenleri düşürmeli, chart'lar makul (< 500),
    ve reçete hızlı bitmeli (< 30 s — kaynak olmadan xatlas dakikalarca sürer)."""
    from common.sewing import unfold_to_charts

    src = tmp_path / "frag.glb"
    base = trimesh.creation.icosphere(subdivisions=3)
    v = base.vertices[base.faces].reshape(-1, 3)
    f = np.arange(len(v)).reshape(-1, 3)
    trimesh.Trimesh(vertices=v, faces=f, process=False).export(str(src))

    # Ön koşul: unfold'un yüklediği gibi yükle → çorba (yüzlerce+ kopuk bileşen).
    loaded = trimesh.load(str(src), force="mesh")
    before = len(loaded.split(only_watertight=False))
    assert before > 500  # gerçekten parçalı (1280 yüz → 1280 bileşen)

    stats: dict = {}
    t0 = time.time()
    charts = unfold_to_charts(str(src), 100.0, stats)
    elapsed = time.time() - t0

    assert elapsed < 30.0, f"reçete çok yavaş: {elapsed:.1f}s"
    assert stats["components_total"] < before  # kaynaştırma bileşenleri indirdi
    assert stats["components_total"] <= 2       # tek katı topolojiye çöktü
    assert stats["charts_total"] < 500          # xatlas çöp chart üretmedi
    assert 1 <= stats["charts_drawn"] <= stats["charts_total"]
    assert stats["charts_dropped"] == stats["charts_total"] - stats["charts_drawn"]
    assert len(charts) == stats["charts_drawn"]
    assert all(len(c["polygon"]) >= 3 for c in charts)


def test_micro_charts_dropped_from_output(tmp_path):
    """Mikro-chart filtresi: toplam alanın < %0.5'i chart'lar çizilenden düşülür,
    stats charts_total > charts_drawn olur. Küçük bir üçgeni büyük bir kutuya
    ekleyerek minik-chart üretiriz."""
    from common.sewing import MICRO_CHART_AREA_FRAC, unfold_to_charts

    box = trimesh.creation.box(extents=(4.0, 4.0, 4.0))
    tiny = trimesh.creation.box(extents=(0.02, 0.02, 0.02))
    tiny.apply_translation([10.0, 0.0, 0.0])
    combo = trimesh.util.concatenate([box, tiny])
    src = tmp_path / "combo.glb"
    combo.export(str(src))

    stats: dict = {}
    charts = unfold_to_charts(str(src), 100.0, stats)
    # Minik kutu chart'ları (< toplam alanın %0.5'i) çizilenden düşülmeli.
    assert stats["charts_dropped"] >= 1
    assert stats["charts_drawn"] < stats["charts_total"]
    assert len(charts) == stats["charts_drawn"]
    # Çizilen chart'ların hepsi eşik üstünde (mikro-chart kalmadı).
    drawn_total = sum(c["area_cm2"] for c in charts)
    assert all(c["area_cm2"] >= MICRO_CHART_AREA_FRAC * drawn_total for c in charts)
