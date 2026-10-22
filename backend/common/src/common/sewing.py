"""Dikiş kalıbı (sewing pattern) — mesh'i xatlas ile açıp SVG/PDF üretir. Task BATCH-G.

Boru hattı (deneysel, "terzi kalıbı yaklaşığı"):
1. `unfold_to_charts`: trimesh ile mesh yükle → xatlas ile parametrize (seam + chart
   unwrap) → her chart'ın 2D sınır poligonunu GERÇEK ÖLÇEKTE (mm) çıkar. xatlas
   atlas'ı eşit texel-yoğunluğuyla paketler; bu yüzden UV(piksel) mesafeleri 3B
   mesafelerle orantılıdır. Global bir kalibrasyonla (toplam 3B alan / toplam UV
   alanı) piksel→mesh-birimi ölçeği bulunur, `scale_mm_per_unit` ile mm'ye çevrilir.
   Böylece chart'lar HEM birbirine göre HEM mutlak ölçekte doğru olur.
2. `charts_to_svg`: chart'ları gerçek mm ölçeğinde tek SVG'ye çizer — kesim çizgisi
   DÜZ, dikiş payı (1 cm offset) KESİKLİ. SVG width/height mm cinsindendir → 1:1 basar.
3. `svg_to_pdf_tiles`: SVG'yi svglib+reportlab ile A4 karolara böler, hizalama
   artıları (köşe çarpıları) + karo etiketi ekler ki kağıtlar birleştirilebilsin.

Dürüst sınır: bu, izometrik/geliştirici bir açımdır (xatlas görsel-doku amaçlı
parametrize eder), gerçek terzi kalıbı çözücüsü (LSCM/ARAP + darts) değildir. Alanlar
ve oranlar yaklaşıktır; UI "deneysel" etiketi taşır.
"""
from __future__ import annotations

import logging
import math
from pathlib import Path
from typing import TypedDict

import numpy as np

_log = logging.getLogger(__name__)

# Dikiş payı: 1 cm (spec SEAM_ALLOWANCE_CM=1).
SEAM_ALLOWANCE_MM = 10.0

# Performans tavanı: xatlas unfold tam-çözünürlük mesh'te çok yavaştır
# (154k yüz ≈ 24 s, daha büyükleri dakikalar / segfault). Bu eşiğin üstündeki
# mesh'ler xatlas ÖNCESİ decimate edilir. Ölçek kalibrasyonu decimated mesh'in
# kendi alanından türediği için oranlar tutarlı kalır (alan ~korunur).
# Motif-bake edilmiş mesh'lerde (parçalı üçgen çorbası) 50k bile xatlas'ı 2.5 dk
# sürükler; ölçülü reçete kaynak+bileşen-filtresi sonrası 10k'da ~1 s'de biter.
MAX_UNFOLD_FACES = 10000

# Bileşen filtresi: kaynaştırma sonrası toplam yüzün en az bu oranına sahip
# bağlı bileşenler tutulur (küçük kopuk artıklar atılır).
MIN_COMPONENT_FRAC = 0.02

# Mikro-chart filtresi: toplam kumaş alanının bu oranından küçük chart'lar
# SVG/PDF çıktısından düşülür (xatlas artığı minik parçalar).
MICRO_CHART_AREA_FRAC = 0.005


class Chart(TypedDict):
    polygon: list[tuple[float, float]]         # kesim çizgisi (mm), paylaşılan çerçeve
    seam_allowance: list[tuple[float, float]]  # dikiş payı offset (mm)
    area_cm2: float                            # gerçek 3B yüzey alanı (cm²)


# --- geometri yardımcıları -----------------------------------------------------
def _tri_area3(tris: np.ndarray) -> np.ndarray:
    """(N,3,3) üçgenlerin 3B alanları."""
    a = tris[:, 1] - tris[:, 0]
    b = tris[:, 2] - tris[:, 0]
    return 0.5 * np.linalg.norm(np.cross(a, b), axis=1)


def _tri_area2(tris: np.ndarray) -> np.ndarray:
    """(N,3,2) üçgenlerin 2B (mutlak) alanları."""
    a = tris[:, 1] - tris[:, 0]
    b = tris[:, 2] - tris[:, 0]
    return 0.5 * np.abs(a[:, 0] * b[:, 1] - a[:, 1] * b[:, 0])


def _signed_area(poly: np.ndarray) -> float:
    x, y = poly[:, 0], poly[:, 1]
    return 0.5 * float(np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1)))


def _boundary_loop(tri: np.ndarray, pts: np.ndarray) -> np.ndarray | None:
    """Bir chart'ın (disk-topolojili yüz kümesi) dış sınır poligonunu döndür.

    Yönlü kenarlardan yalnız BİR yönde görünenler = sınır (ters yönü yoksa açık
    kenar). Sınır kenarlarını halkalara ördürüp en büyük alanlıyı seçer (xatlas
    chart'ları diskti → tek halka; en büyük seçimi deliksiz olanı garantiler).
    """
    edges: dict[tuple[int, int], int] = {}
    for a, b, c in tri:
        for u, v in ((int(a), int(b)), (int(b), int(c)), (int(c), int(a))):
            edges[(u, v)] = edges.get((u, v), 0) + 1
    # Sınır: ters yönü bulunmayan yönlü kenarlar.
    nxt: dict[int, list[int]] = {}
    for (u, v) in edges:
        if (v, u) not in edges:
            nxt.setdefault(u, []).append(v)
    if not nxt:
        return None

    used: set[tuple[int, int]] = set()
    loops: list[list[int]] = []
    for start in list(nxt):
        for first in nxt[start]:
            if (start, first) in used:
                continue
            loop = [start]
            u, v = start, first
            while True:
                used.add((u, v))
                loop.append(v)
                if v == start:
                    break
                outs = nxt.get(v)
                if not outs:
                    break
                pick = next((c for c in outs if (v, c) not in used), None)
                if pick is None:
                    break
                u, v = v, pick
            if len(loop) >= 4 and loop[0] == loop[-1]:
                loops.append(loop[:-1])
    if not loops:
        return None
    best = max(loops, key=lambda idxs: abs(_signed_area(pts[idxs])))
    return pts[best]


def _offset_polygon(poly: np.ndarray, dist: float) -> np.ndarray:
    """Poligonu `dist` mm DIŞARI ötele (dikiş payı). Miter köşe, 2x cap'li."""
    p = np.asarray(poly, dtype=np.float64)
    if _signed_area(p) < 0:            # CCW'ye zorla (dış normal tutarlılığı)
        p = p[::-1].copy()
    n = len(p)

    def edge_normal(d: np.ndarray) -> np.ndarray:
        # CCW poligonda kenar yönü d için dış (sağ) normal = (dy, -dx).
        nx, ny = d[1], -d[0]
        L = math.hypot(nx, ny)
        return np.array([nx / L, ny / L]) if L > 1e-9 else np.array([0.0, 0.0])

    out = np.zeros_like(p)
    for i in range(n):
        n_prev = edge_normal(p[i] - p[i - 1])
        n_next = edge_normal(p[(i + 1) % n] - p[i])
        bis = n_prev + n_next
        L = math.hypot(bis[0], bis[1])
        if L < 1e-9:
            out[i] = p[i]
            continue
        bis = bis / L
        # Miter uzunluk düzeltmesi: cos(yarı-açı) = bis·n_next; sivri köşede 2x cap.
        cos_half = max(float(np.dot(bis, n_next)), 0.5)
        out[i] = p[i] + bis * (dist / cos_half)
    return out


# --- 1) unfold -----------------------------------------------------------------
def unfold_to_charts(mesh_path: str, scale_mm_per_unit: float,
                     stats: dict | None = None) -> list[Chart]:
    """Mesh'i xatlas ile aç; her chart için gerçek-ölçek (mm) poligon + dikiş payı.

    Ölçülü reçete (motif-bake mesh'ler parçalı üçgen çorbasıdır — UV dikişleri
    köşeleri kopyalar → binlerce kopuk bileşen → xatlas dakikalarca sürüp çöp
    chart üretir):
      1) `merge_vertices(merge_tex=True, merge_norm=True)` ile köşeleri kaynaştır.
      2) bağlı bileşenlere ayır; toplam yüzün < %2'sini tutan kopuk artıkları at.
      3) hedef 10k yüze decimate et.
      4) xatlas ile parametrize et.
    Ek olarak mikro-chart filtresi: toplam alanın < %0.5'i chart'lar düşülür.

    `stats` verilirse doldurulan alanlar: `faces_in` (yüklenen), `faces_used`
    (kaynaştırma+bileşen-filtresi+decimation sonrası xatlas'a giren), bileşen
    sayıları (`components_total`/`components_dropped`) ve chart sayıları
    (`charts_total`/`charts_drawn`/`charts_dropped`) — route yanıtına dürüstlük için.
    """
    import trimesh
    import xatlas

    mesh = trimesh.load(str(mesh_path), force="mesh")
    if not isinstance(mesh, trimesh.Trimesh) or len(mesh.faces) == 0:
        raise ValueError("Mesh yüklenemedi ya da boş")

    faces_in = int(len(mesh.faces))

    # 1) Köşe kaynaştırma — motif-bake mesh'lerinde UV/normal dikişlerinde kopyalanan
    # köşeleri birleştir. Bu OLMADAN mesh yüzleri kopuktur (binlerce bileşen) ve
    # xatlas hem çok yavaş hem de binlerce çöp chart üretir.
    try:
        mesh.merge_vertices(merge_tex=True, merge_norm=True)
    except TypeError:  # eski trimesh imzası — argümansız kaynaştır
        mesh.merge_vertices()

    # 2) Bağlı bileşenler — kaynaştırma sonrası küçük kopuk artıkları at (>= %2 tut).
    components_total = 1
    components_dropped = 0
    try:
        comps = mesh.split(only_watertight=False)
    except Exception as exc:  # noqa: BLE001 — ayrım başarısızsa tüm mesh'le devam
        _log.warning("dikiş kalıbı bileşen ayrımı başarısız (%s); tüm mesh kullanılıyor", exc)
        comps = []
    if len(comps) > 1:
        components_total = len(comps)
        total_faces = sum(len(c.faces) for c in comps)
        thresh = MIN_COMPONENT_FRAC * total_faces
        kept = [c for c in comps if len(c.faces) >= thresh]
        if not kept:  # hepsi eşikaltıysa en büyüğü tut (asla boşa düşme)
            kept = [max(comps, key=lambda c: len(c.faces))]
        components_dropped = components_total - len(kept)
        merged = trimesh.util.concatenate(kept)
        if isinstance(merged, trimesh.Trimesh) and len(merged.faces) > 0:
            mesh = merged

    faces_used = int(len(mesh.faces))
    # 3) Büyük mesh'i xatlas'tan ÖNCE decimate et (trimesh quadric). Kütüphane yoksa
    # ya da başarısızsa (fast_simplification eksik vb.) uyarı loglayıp tam mesh'le
    # devam ederiz — açım yavaş olur ama sonuç doğru kalır.
    if len(mesh.faces) > MAX_UNFOLD_FACES:
        try:
            dec = mesh.simplify_quadric_decimation(face_count=MAX_UNFOLD_FACES)
            if isinstance(dec, trimesh.Trimesh) and len(dec.faces) > 0:
                mesh = dec
                faces_used = int(len(dec.faces))
            else:
                _log.warning("dikiş kalıbı decimation boş mesh döndü; tam mesh kullanılıyor")
        except Exception as exc:  # noqa: BLE001 — herhangi bir decimation hatasında güvenli düş
            _log.warning("dikiş kalıbı decimation başarısız (%s); tam mesh kullanılıyor", exc)
    if stats is not None:
        stats["faces_in"] = faces_in
        stats["faces_used"] = faces_used
        stats["components_total"] = components_total
        stats["components_dropped"] = components_dropped

    verts = np.asarray(mesh.vertices, dtype=np.float64)
    faces = np.asarray(mesh.faces, dtype=np.uint32)

    atlas = xatlas.Atlas()
    atlas.add_mesh(verts, faces)
    atlas.generate()
    vmapping, indices, uvs = atlas[0]
    indices = np.asarray(indices, dtype=np.int64)
    width, height = int(atlas.width), int(atlas.height)
    if width <= 0 or height <= 0:
        raise ValueError("xatlas atlas boyutu geçersiz")

    # UV → atlas pikseli; çıkış-vertex'i → orijinal 3B konum.
    px = np.asarray(uvs, dtype=np.float64) * np.array([float(width), float(height)])
    orig = verts[np.asarray(vmapping, dtype=np.int64)]

    # Global kalibrasyon: piksel → mesh-birimi (eşit texel yoğunluğu sayesinde geçerli).
    area3d = _tri_area3(orig[indices])
    area_uv = _tri_area2(px[indices])
    if area3d.sum() <= 0 or area_uv.sum() <= 0:
        raise ValueError("Parametrizasyon alanı sıfır")
    units_per_px = math.sqrt(area3d.sum() / area_uv.sum())
    mm_per_px = units_per_px * float(scale_mm_per_unit)
    pts_mm = px * mm_per_px  # tüm chart'lar için PAYLAŞILAN mm çerçevesi (atlas düzeni)

    charts: list[Chart] = []
    for ci in range(atlas.get_mesh_chart_count(0)):
        chart = atlas.get_mesh_chart(0, ci)
        cfaces = np.asarray(chart.faces, dtype=np.int64)
        if len(cfaces) == 0:
            continue
        loop = _boundary_loop(indices[cfaces], pts_mm)
        if loop is None or len(loop) < 3:
            continue
        area_cm2 = float(area3d[cfaces].sum()) * (float(scale_mm_per_unit) ** 2) / 100.0
        seam = _offset_polygon(loop, SEAM_ALLOWANCE_MM)
        charts.append({
            "polygon": [(round(float(x), 3), round(float(y), 3)) for x, y in loop],
            "seam_allowance": [(round(float(x), 3), round(float(y), 3)) for x, y in seam],
            "area_cm2": round(area_cm2, 2),
        })
    if not charts:
        raise ValueError("Hiç chart üretilemedi")

    # Mikro-chart filtresi: toplam kumaş alanının < %0.5'i olan minik xatlas
    # artıklarını SVG/PDF çıktısından düş (dikilemeyecek kadar küçük parçalar).
    charts_total = len(charts)
    total_area = sum(c["area_cm2"] for c in charts)
    if total_area > 0 and charts_total > 1:
        thresh = MICRO_CHART_AREA_FRAC * total_area
        filtered = [c for c in charts if c["area_cm2"] >= thresh]
        if filtered:  # asla hepsini düşürme
            charts = filtered
    charts_drawn = len(charts)
    if stats is not None:
        stats["charts_total"] = charts_total
        stats["charts_drawn"] = charts_drawn
        stats["charts_dropped"] = charts_total - charts_drawn
    return charts


# --- 2) SVG --------------------------------------------------------------------
def _bounds(charts: list[Chart]) -> tuple[float, float, float, float]:
    pts = []
    for c in charts:
        pts.extend(c["seam_allowance"])
        pts.extend(c["polygon"])
    arr = np.asarray(pts, dtype=np.float64)
    return float(arr[:, 0].min()), float(arr[:, 1].min()), float(arr[:, 0].max()), float(arr[:, 1].max())


def charts_to_svg(charts: list[Chart], out_svg: str) -> None:
    """Chart'ları gerçek mm ölçeğinde SVG'ye yaz (kesim=düz, dikiş payı=kesikli).

    width/height mm birimindedir → tarayıcı/yazıcı 1:1 basar. Alt kenara 50 mm'lik
    (5 cm) ölçek çubuğu + not eklenir.
    """
    minx, miny, maxx, maxy = _bounds(charts)
    margin = 15.0
    legend_h = 22.0
    w = (maxx - minx) + 2 * margin
    h = (maxy - miny) + 2 * margin + legend_h

    def tx(x: float) -> float:
        return x - minx + margin

    def ty(y: float) -> float:
        # SVG y aşağı; mm çerçevesinde y yukarı → çevir.
        return (maxy - y) + margin

    def path_d(poly: list[tuple[float, float]]) -> str:
        pts = " ".join(f"{tx(x):.3f},{ty(y):.3f}" for x, y in poly)
        return f"M {pts} Z"

    parts: list[str] = []
    parts.append(
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{w:.2f}mm" height="{h:.2f}mm" '
        f'viewBox="0 0 {w:.2f} {h:.2f}">'
    )
    parts.append(f'<rect x="0" y="0" width="{w:.2f}" height="{h:.2f}" fill="white"/>')
    for i, c in enumerate(charts, 1):
        # Dikiş payı — kesikli, ince.
        parts.append(
            f'<path d="{path_d(c["seam_allowance"])}" fill="none" stroke="#c0392b" '
            f'stroke-width="0.3" stroke-dasharray="3,2"/>'
        )
        # Kesim çizgisi — düz, kalın.
        parts.append(
            f'<path d="{path_d(c["polygon"])}" fill="none" stroke="#111111" stroke-width="0.5"/>'
        )
        cx = sum(tx(x) for x, _ in c["polygon"]) / len(c["polygon"])
        cy = sum(ty(y) for _, y in c["polygon"]) / len(c["polygon"])
        parts.append(
            f'<text x="{cx:.2f}" y="{cy:.2f}" font-size="4" fill="#555" '
            f'text-anchor="middle">#{i} · {c["area_cm2"]:.0f} cm²</text>'
        )
    # Ölçek çubuğu (50 mm) + not — alt sol köşe.
    bar_y = h - 8.0
    bar_x = margin
    parts.append(
        f'<line x1="{bar_x:.2f}" y1="{bar_y:.2f}" x2="{bar_x + 50:.2f}" y2="{bar_y:.2f}" '
        f'stroke="#111" stroke-width="0.6"/>'
    )
    parts.append(
        f'<text x="{bar_x:.2f}" y="{bar_y - 2:.2f}" font-size="4" fill="#111">5 cm '
        f'(ölçek 1:1) — düz: kesim · kesikli: 1 cm dikiş payı — deneysel</text>'
    )
    parts.append("</svg>")

    out = Path(out_svg)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(parts), encoding="utf-8")


# --- 3) PDF karolama -----------------------------------------------------------
_PAGES_MM = {"A4": (210.0, 297.0), "A3": (297.0, 420.0), "A0": (841.0, 1189.0)}


def _pdf_font() -> str:
    """Türkçe karakterli (ı, ş, ğ) başlık için DejaVuSans; yoksa Helvetica."""
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont

    if "DejaVuSans" in pdfmetrics.getRegisteredFontNames():
        return "DejaVuSans"
    for cand in ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
                 "/usr/share/fonts/TTF/DejaVuSans.ttf"):
        if Path(cand).is_file():
            try:
                pdfmetrics.registerFont(TTFont("DejaVuSans", cand))
                return "DejaVuSans"
            except Exception:  # noqa: BLE001 — font yoksa varsayılana düş
                break
    return "Helvetica"


def svg_to_pdf_tiles(svg_path: str, out_pdf: str, page: str = "A4",
                     label: str = "deneysel dikiş kalıbı") -> None:
    """SVG'yi 1:1 ölçekte sayfa karolarına böl; köşe hizalama artıları + etiket ekle.

    svglib SVG'yi (mm→punto) gerçek ölçekte bir Drawing'e çevirir. Drawing punto
    cinsinden gerçek boyuttadır; sayfa yazılabilir alanına göre karo sayısı
    hesaplanır ve her karo, clip + kaydırma ile ayrı sayfaya basılır.
    """
    from reportlab.lib.units import mm
    from reportlab.pdfgen import canvas as pdfcanvas
    from svglib.svglib import svg2rlg

    drawing = svg2rlg(str(svg_path))
    if drawing is None:
        raise ValueError("SVG okunamadı")

    dw, dh = float(drawing.width), float(drawing.height)  # punto
    pw_mm, ph_mm = _PAGES_MM.get(page.upper(), _PAGES_MM["A4"])
    page_w, page_h = pw_mm * mm, ph_mm * mm
    margin = 10.0 * mm
    printable_w = page_w - 2 * margin
    printable_h = page_h - 2 * margin

    cols = max(1, math.ceil(dw / printable_w))
    rows = max(1, math.ceil(dh / printable_h))

    out = Path(out_pdf)
    out.parent.mkdir(parents=True, exist_ok=True)
    c = pdfcanvas.Canvas(str(out), pagesize=(page_w, page_h))

    font = _pdf_font()

    def crosshair(x: float, y: float) -> None:
        s = 4 * mm
        c.line(x - s, y, x + s, y)
        c.line(x, y - s, x, y + s)

    for r in range(rows):
        for col in range(cols):
            c.saveState()
            # Karo bölgesini (yazılabilir alan) clip'le.
            path = c.beginPath()
            path.rect(margin, margin, printable_w, printable_h)
            c.clipPath(path, stroke=0, fill=0)
            # Drawing'i, bu karonun sol-üst köşesi sayfa yazılabilir köşesine gelecek
            # şekilde kaydır. reportlab kökeni sol-alt; SVG üstten aşağı okunur.
            ox = margin - col * printable_w
            oy = margin - (dh - (r + 1) * printable_h)
            drawing.drawOn(c, ox, oy)
            c.restoreState()
            # Hizalama artıları — clip köşeleri (birleştirme rehberi).
            c.setLineWidth(0.4)
            for cx in (margin, margin + printable_w):
                for cy in (margin, margin + printable_h):
                    crosshair(cx, cy)
            c.setFont(font, 8)
            c.drawString(margin, page_h - margin + 3,
                         f"Sıra {r + 1} · Sütun {col + 1}  ({label}) — sayfa {r * cols + col + 1}/{rows * cols}")
            c.showPage()
    c.save()
