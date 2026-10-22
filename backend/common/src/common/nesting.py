"""Kalıp parçalarını kumaş topuna yerleştirme (nesting / pastal planı) — F5.

Girdi: ORTAK SÖZLEŞME'deki `pieces.json` (parçaların `cut_line` poligonları, mm).
Çıktı: her kesilecek kopya için kumaş üzerindeki yer + kullanılan kumaş boyu +
verim yüzdesi; ayrıca 1:1 ölçekli `nest.svg` ve `nest.json`.

Koordinat sistemi (kumaş)
-------------------------
- x ekseni = kumaşın BOYU (top açılma yönü, kenar/selvage'a paralel, düz boy).
- y ekseni = kumaşın ENİ, 0 … `fabric_width_mm` (bir kenardan diğer kenara).
- Birim mm. SVG'de x yatay, y dikey çizilir.

Düz boy (grain) kuralı
----------------------
Her parçanın `grain_deg` yönü (parça koordinatında x eksenine göre derece) kumaşın
x eksenine (boy) hizalanır. Bu yüzden izin verilen dönüşler YALNIZ 0° ve 180°'dir
(`allow_rotate_180`). Serbest dönüş yoktur — düz boy her zaman korunur.

Kopya sayısı ve ters çevirme kuralları (kesilecek toplam kopya)
---------------------------------------------------------------
Kumaş TEK KAT, açık serilmiş varsayılır.

1. `mirror=false` → `quantity` adet kopya, hepsi kalıp yüzü yukarı (flipped=false).
2. `mirror=true` + katlama kenarı VAR (`fold_edge` bir edge id) → parça simetrik bir
   YARIMdır ve katlı kesilir. Tek kat açık kumaşta katlama kenarı etrafında aynalanıp
   TAM parçaya açılır (`unfolded=true`); `quantity` adet tam kopya kesilir.
3. `mirror=true` + `fold_edge` null/yok → parça bir sağ/sol ÇİFTin bir tekidir
   (ör. kol, yarım arka). Her biri için bir de aynalı ikiz gerekir:
   toplam `2 × quantity` kopya; ikizler `flipped=true` (kağıt kalıp TERS çevrilerek
   kesilir), `mirror_twin=true`.

`allow_flip`:
- false → yalnız 3. kuraldaki zorunlu ikizler ters çevrilir (yüzü olan kumaş).
- true  → kumaşın iki yüzü aynı kabul edilir; yerleştirici her kopyayı daha iyi
  sığması için ters de çevirebilir (çıktıdaki `flipped` gerçek çizim yönünü söyler).
  Tek yüzlü (desenli/tüylü) kumaşta false verin.

Dönüşüm (placement → kumaş koordinatı)
---------------------------------------
Parça koordinatındaki p noktası için:
    p' = F(p)              (flipped ise y → -y, değilse aynı)
    p'' = R(rot_deg) · p'  (orijin etrafında saat-yönü-tersi dönüş)
    q = p'' + (x_mm, y_mm)
`polygon_mm` alanı bu dönüşümün uygulanmış halini zaten taşır (frontend ayrıca
hesaplamak zorunda değildir). `unfolded` parçalarda p, açılmış TAM poligonun
(`full_cut_line`) noktalarıdır.

Algoritma
---------
Raster tabanlı bottom-left-fill (yeni bağımlılık yok, yalnız numpy):
- Kumaş `grid_mm` hücrelik ızgaraya bölünür.
- Her parça/yön için hücre maskesi: hücre merkezinin poligona uzaklığı
  ≤ gap/2 + grid·√2/2 ise dolu. Bu MUHAFAZAKÂR rasterlemedir: iki maske ayrık ise
  gerçek poligonlar arası mesafe ≥ gap olduğu ispatlanabilir (bkz. `_piece_mask`).
- Büyük alanlı kopyalar önce; her kopya için tüm konumlardaki çakışma sayısı FFT
  korelasyonu ile tek seferde hesaplanır; en küçük (sağ uç x, x, y) seçilir.
- Yerleşim sonunda kesin geometri ile (poligon-mesafe) yeniden doğrulanır.
"""
from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

import numpy as np

# Varsayılanlar (route ile aynı).
DEFAULT_FABRIC_WIDTH_CM = 150.0
DEFAULT_GAP_MM = 5.0
DEFAULT_GRID_MM = 5.0
MIN_GRID_MM = 1.0
MAX_GRID_MM = 20.0

_EPS = 1e-6


class NestingError(ValueError):
    """Yerleştirme yapılamadı — mesaj Türkçe ve kullanıcıya gösterilebilir."""


# ---------------------------------------------------------------------------
# Temel geometri
# ---------------------------------------------------------------------------
def polygon_area(poly: np.ndarray) -> float:
    """İşaretli alan (shoelace). CCW → pozitif."""
    p = np.asarray(poly, dtype=float)
    x, y = p[:, 0], p[:, 1]
    return 0.5 * float(np.dot(x, np.roll(y, -1)) - np.dot(np.roll(x, -1), y))


def _ensure_ccw(poly: np.ndarray) -> np.ndarray:
    return poly if polygon_area(poly) >= 0 else poly[::-1].copy()


def _clean_ring(points: Any) -> np.ndarray:
    """Liste → (N,2) dizi; kapanış tekrarı ve ardışık kopya noktalar atılır."""
    p = np.asarray(points, dtype=float).reshape(-1, 2)
    if len(p) >= 2 and np.allclose(p[0], p[-1]):
        p = p[:-1]
    keep = [0]
    for i in range(1, len(p)):
        if not np.allclose(p[i], p[keep[-1]], atol=1e-9):
            keep.append(i)
    return p[keep]


def _points_in_polygon(pts: np.ndarray, poly: np.ndarray) -> np.ndarray:
    """Çift-tek (ray casting) içerde-mi testi, vektörel. pts (M,2) → bool (M,)."""
    x = pts[:, 0][:, None]
    y = pts[:, 1][:, None]
    x1, y1 = poly[:, 0][None, :], poly[:, 1][None, :]
    x2, y2 = np.roll(poly[:, 0], -1)[None, :], np.roll(poly[:, 1], -1)[None, :]
    cond = (y1 > y) != (y2 > y)
    with np.errstate(divide="ignore", invalid="ignore"):
        xint = x1 + (y - y1) * (x2 - x1) / (y2 - y1)
    cross = cond & (x < xint)
    return (np.count_nonzero(cross, axis=1) % 2) == 1


def _points_to_segments_dist(pts: np.ndarray, poly: np.ndarray) -> np.ndarray:
    """Her noktanın poligon KENARLARINA en kısa uzaklığı. (M,) döner."""
    a = poly
    b = np.roll(poly, -1, axis=0)
    ab = b - a                                     # (S,2)
    ab2 = np.maximum((ab ** 2).sum(axis=1), 1e-18)  # (S,)
    ap = pts[:, None, :] - a[None, :, :]           # (M,S,2)
    t = np.clip((ap * ab[None]).sum(axis=2) / ab2[None], 0.0, 1.0)
    proj = a[None] + t[..., None] * ab[None]
    d2 = ((pts[:, None, :] - proj) ** 2).sum(axis=2)
    return np.sqrt(d2.min(axis=1))


def _segments_intersect_any(p: np.ndarray, q: np.ndarray) -> bool:
    """İki poligonun kenarlarından herhangi bir çift kesişiyor/dokunuyor mu?"""
    a1, a2 = p, np.roll(p, -1, axis=0)
    b1, b2 = q, np.roll(q, -1, axis=0)

    def orient(o, a, b):
        return ((a[..., 0] - o[..., 0]) * (b[..., 1] - o[..., 1])
                - (a[..., 1] - o[..., 1]) * (b[..., 0] - o[..., 0]))

    A1, A2 = a1[:, None, :], a2[:, None, :]
    B1, B2 = b1[None, :, :], b2[None, :, :]
    d1 = orient(A1, A2, B1)
    d2 = orient(A1, A2, B2)
    d3 = orient(B1, B2, A1)
    d4 = orient(B1, B2, A2)
    proper = (d1 * d2 <= 0) & (d3 * d4 <= 0)
    if not proper.any():
        return False
    # Eşdoğrusal-ama-ayrık segmentler (dört orient de 0) yanlış pozitif verir;
    # onları bbox örtüşmesiyle ele.
    col = (np.abs(d1) < 1e-12) & (np.abs(d2) < 1e-12)
    if not col.any():
        return True
    bx = (np.maximum(A1[..., 0], A2[..., 0]) >= np.minimum(B1[..., 0], B2[..., 0])) & \
         (np.maximum(B1[..., 0], B2[..., 0]) >= np.minimum(A1[..., 0], A2[..., 0])) & \
         (np.maximum(A1[..., 1], A2[..., 1]) >= np.minimum(B1[..., 1], B2[..., 1])) & \
         (np.maximum(B1[..., 1], B2[..., 1]) >= np.minimum(A1[..., 1], A2[..., 1]))
    real = proper & (~col | bx)
    return bool(real.any())


def polygon_distance(p: Any, q: Any) -> float:
    """İki basit poligon arasındaki KESİN en kısa mesafe (mm).

    Kesişiyor, dokunuyor ya da biri diğerinin içindeyse 0 döner. Aksi halde
    en kısa mesafe bir köşe ile bir kenar arasındadır → köşe-kenar uzaklıklarının
    minimumu (iki yönde).
    """
    p = np.asarray(p, dtype=float)
    q = np.asarray(q, dtype=float)
    if _segments_intersect_any(p, q):
        return 0.0
    if _points_in_polygon(p[:1], q)[0] or _points_in_polygon(q[:1], p)[0]:
        return 0.0
    return float(min(_points_to_segments_dist(p, q).min(),
                     _points_to_segments_dist(q, p).min()))


def _clip_halfplane(poly: np.ndarray, a: np.ndarray, n: np.ndarray) -> np.ndarray:
    """Sutherland–Hodgman: poligonun (x-a)·n ≥ 0 tarafını tut."""
    out: list[np.ndarray] = []
    m = len(poly)
    for i in range(m):
        cur, nxt = poly[i], poly[(i + 1) % m]
        dc = float(np.dot(cur - a, n))
        dn = float(np.dot(nxt - a, n))
        if dc >= -_EPS:
            out.append(cur)
        if (dc > _EPS and dn < -_EPS) or (dc < -_EPS and dn > _EPS):
            t = dc / (dc - dn)
            out.append(cur + t * (nxt - cur))
    if not out:
        return np.zeros((0, 2))
    return _clean_ring(np.array(out))


def _reflect(points: np.ndarray, a: np.ndarray, u: np.ndarray) -> np.ndarray:
    """Noktaları a'dan geçen, birim yönü u olan doğruya göre aynala."""
    d = points - a
    along = (d @ u)[:, None] * u[None, :]
    return a + 2 * along - d


def unfold_on_fold(cut: np.ndarray, seam: np.ndarray, fa: np.ndarray,
                   fb: np.ndarray) -> np.ndarray | None:
    """Katlı kesilen yarım parçayı katlama doğrusu (fa→fb) etrafında TAM parçaya aç.

    Kesim çizgisi katlama doğrusunu aşıyorsa (katlama kenarına pay verilmişse)
    önce doğrunun iç tarafına kırpılır (iç taraf = dikiş çizgisi ağırlık merkezinin
    olduğu taraf). Kırpılmış yarım P'nin katlama doğrusu üzerinde TEK bir kenarı
    olmalıdır; P ile aynası bu kenar boyunca birleştirilir. Döner: CCW tam poligon,
    ya da birleşim güvenli kurulamazsa None.
    """
    u = fb - fa
    ln = float(np.hypot(*u))
    if ln < 1e-9:
        return None
    u = u / ln
    n = np.array([-u[1], u[0]])
    if float(np.dot(seam.mean(axis=0) - fa, n)) < 0:
        n = -n
    half = _clip_halfplane(_ensure_ccw(cut), fa, n)
    if len(half) < 3:
        return None
    half = _ensure_ccw(half)
    on = np.abs((half - fa) @ n) < 1e-6
    # Katlama doğrusu üzerindeki ara noktaları (FreeSewing cf/cb'de çentik vb.
    # noktalar bırakır) at: iki komşusu da doğrudaysa nokta tek kenarı böler.
    m = len(half)
    keep = [not (on[i] and on[i - 1] and on[(i + 1) % m]) for i in range(m)]
    half, on = half[keep], on[keep]
    if len(half) < 3:
        return None
    m = len(half)
    fold_edges = [i for i in range(m) if on[i] and on[(i + 1) % m]]
    if len(fold_edges) != 1:
        return None
    i = fold_edges[0]
    # half[i] → half[i+1] katlama kenarı (a→b). Listeyi b'den başlayıp a'da bitir.
    order = [(i + 1 + k) % m for k in range(m)]
    p_list = half[order]                     # b, …, a
    refl = _reflect(p_list, fa, u)[::-1]     # a, …, b (aynalı, CCW'ye çevrilmiş)
    full = np.vstack([p_list, refl[1:-1]])
    full = _clean_ring(full)
    if abs(polygon_area(full) - 2 * polygon_area(half)) > 1e-3 * max(1.0, polygon_area(half)):
        return None
    return _ensure_ccw(full)


# ---------------------------------------------------------------------------
# Kopya listesi
# ---------------------------------------------------------------------------
def _fold_edge_for(piece: dict, meta: dict | None) -> str | None:
    """Parçanın katlama kenarı (edge id) — önce parçada, sonra meta.json'da arar.

    Kabul edilen biçimler: piece["fold_edge"]; meta["fold_edges"][name];
    meta["fold_edge"] (dict ise name→id, str ise "<name>." önekli id);
    meta["pieces"] listesinde {"name", "fold_edge"}.
    """
    name = piece.get("name")
    if "fold_edge" in piece:
        return piece.get("fold_edge") or None
    if not meta:
        return None
    fe = meta.get("fold_edges")
    if isinstance(fe, dict) and name in fe:
        return fe.get(name) or None
    fe = meta.get("fold_edge")
    if isinstance(fe, dict) and name in fe:
        return fe.get(name) or None
    if isinstance(fe, str) and fe.startswith(f"{name}."):
        return fe
    if isinstance(fe, list):
        for e in fe:
            if isinstance(e, str) and e.startswith(f"{name}."):
                return e
    for mp in meta.get("pieces") or []:
        if isinstance(mp, dict) and mp.get("name") == name and mp.get("fold_edge"):
            return mp["fold_edge"]
    return None


def expand_copies(pieces_doc: dict, meta: dict | None = None) -> tuple[list[dict], list[str]]:
    """pieces.json → kesilecek kopya listesi (modül docstring'indeki kurallar).

    Her kopya: {piece, label_tr, copy (1-tabanlı), total, poly (parça koord. CCW
    kesim poligonu, açılmışsa tam), grain_deg, flipped (zorunlu), mirror_twin,
    unfolded, area_mm2}. İkinci dönüş: Türkçe uyarılar.
    """
    warnings: list[str] = []
    copies: list[dict] = []
    for piece in pieces_doc.get("pieces") or []:
        name = str(piece.get("name") or "parca")
        label = str(piece.get("label_tr") or name)
        raw = piece.get("cut_line") or piece.get("seam_line")
        if not raw:
            warnings.append(f"'{label}' parçasının kesim çizgisi yok, atlandı.")
            continue
        cut = _clean_ring(raw)
        if len(cut) < 3 or abs(polygon_area(cut)) < 1.0:
            warnings.append(f"'{label}' parçası geçersiz (alanı yok), atlandı.")
            continue
        cut = _ensure_ccw(cut)
        qty = max(1, int(piece.get("quantity") or 1))
        mirror = bool(piece.get("mirror"))
        grain = float(piece.get("grain_deg", 90.0) if piece.get("grain_deg") is not None else 90.0)
        unfolded = False
        twin = False
        if mirror:
            fold_id = _fold_edge_for(piece, meta)
            if fold_id:
                full = None
                seam = _clean_ring(piece.get("seam_line") or raw)
                edge = next((e for e in piece.get("edges") or [] if e.get("id") == fold_id), None)
                if edge is not None:
                    try:
                        fa = seam[int(edge["from"])]
                        fb = seam[int(edge["to"])]
                        full = unfold_on_fold(cut, seam, fa, fb)
                    except (KeyError, IndexError, ValueError, TypeError):
                        full = None
                if full is not None:
                    cut = full
                    unfolded = True
                else:
                    warnings.append(
                        f"'{label}' parçası katlı kesim için açılamadı (katlama kenarı "
                        f"'{fold_id}' bulunamadı ya da düz değil); sağ/sol çift olarak yerleştirildi.")
                    twin = True
            else:
                twin = True
        area = polygon_area(cut)
        total = qty * (2 if twin else 1)
        n = 0
        for _ in range(qty):
            variants = [False, True] if twin else [False]
            for flipped in variants:
                n += 1
                copies.append({
                    "piece": name, "label_tr": label, "copy": n, "total": total,
                    "poly": cut, "grain_deg": grain, "flipped": flipped,
                    "mirror_twin": flipped and twin, "unfolded": unfolded,
                    "area_mm2": area,
                })
    return copies, warnings


# ---------------------------------------------------------------------------
# Dönüşüm + raster
# ---------------------------------------------------------------------------
def _rot(points: np.ndarray, deg: float) -> np.ndarray:
    r = math.radians(deg)
    c, s = math.cos(r), math.sin(r)
    return points @ np.array([[c, s], [-s, c]])


def transform(points: np.ndarray, flipped: bool, rot_deg: float,
              x_mm: float, y_mm: float) -> np.ndarray:
    """Parça koordinatı → kumaş koordinatı (modül docstring'indeki formül)."""
    p = np.asarray(points, dtype=float).copy()
    if flipped:
        p[:, 1] = -p[:, 1]
    p = _rot(p, rot_deg)
    return p + np.array([x_mm, y_mm])


def _orientations(copy: dict, allow_rotate_180: bool, allow_flip: bool) -> list[tuple[bool, float]]:
    """(flipped, rot_deg) adayları — düz boy daima kumaş x eksenine hizalı."""
    g = copy["grain_deg"]
    flips = [copy["flipped"]]
    if allow_flip:
        flips = [copy["flipped"], not copy["flipped"]]
    out = []
    for f in flips:
        base = g if f else -g          # flip y'yi aynalar → grain açısı -g olur
        rots = [base, base + 180.0] if allow_rotate_180 else [base]
        for r in rots:
            out.append((f, ((r + 180.0) % 360.0) - 180.0))
    return out


def _piece_mask(local: np.ndarray, grid: float, radius: float) -> tuple[np.ndarray, int, int]:
    """Yerel (min köşesi 0,0) poligonun muhafazakâr hücre maskesi.

    Hücre (k,l) merkezi c=((k+.5)g,(l+.5)g); dist(c, poligon) ≤ radius ise dolu
    (içerideki merkezler dist=0). radius = gap/2 + g·√2/2.

    İspat (ayrık maske ⇒ gerçek mesafe ≥ gap): p∈A, q∈B, |pq| < gap olsun. pq
    üzerinde p'den gap/2 uzaktaki m noktasının hücre merkezi c için
    |cm| ≤ g√2/2 ⇒ dist(c,A) ≤ g√2/2+gap/2 ve dist(c,B) ≤ g√2/2+|pq|-gap/2 <
    radius ⇒ c iki maskede de dolu, çelişki. (Kenar durumları için radius'a küçük
    bir güvenlik payı eklenir.)

    Döner: (maske [kx, ly] bool, k0, l0) — maske[0,0] yerel hücre (k0,l0)'a karşılık.
    """
    w = float(local[:, 0].max())
    h = float(local[:, 1].max())
    pad = int(math.ceil(radius / grid)) + 1
    k0, l0 = -pad, -pad
    nk = int(math.ceil(w / grid)) + 2 * pad + 1
    nl = int(math.ceil(h / grid)) + 2 * pad + 1
    kc = (np.arange(nk) + k0 + 0.5) * grid
    lc = (np.arange(nl) + l0 + 0.5) * grid
    X, Y = np.meshgrid(kc, lc, indexing="ij")
    pts = np.column_stack([X.ravel(), Y.ravel()])
    inside = _points_in_polygon(pts, local)
    mask = inside.copy()
    out_idx = np.nonzero(~inside)[0]
    # Bellek için parça parça uzaklık hesabı.
    step = max(1, 400000 // max(1, len(local)))
    for s in range(0, len(out_idx), step):
        idx = out_idx[s:s + step]
        mask[idx] = _points_to_segments_dist(pts[idx], local) <= radius
    return mask.reshape(nk, nl), k0, l0


def _correlate_overlap(occ: np.ndarray, mask: np.ndarray) -> np.ndarray:
    """Her (i,j) yerleşimi için occ[i+a, j+b]·mask[a,b] toplamı (FFT ile).

    Döner boyut: (occ.shape - mask.shape + 1) — yalnız tamamen içeri düşen konumlar.
    """
    H, W = occ.shape
    h, w = mask.shape
    fh, fw = H + h - 1, W + w - 1
    fa = np.fft.rfft2(occ.astype(np.float32), s=(fh, fw))
    fb = np.fft.rfft2(mask[::-1, ::-1].astype(np.float32), s=(fh, fw))
    full = np.fft.irfft2(fa * fb, s=(fh, fw))
    return full[h - 1:H, w - 1:W]


# ---------------------------------------------------------------------------
# Ana fonksiyon
# ---------------------------------------------------------------------------
def nest_pieces(pieces_doc: dict, fabric_width_cm: float = DEFAULT_FABRIC_WIDTH_CM,
                gap_mm: float = DEFAULT_GAP_MM, allow_rotate_180: bool = True,
                allow_flip: bool = True, grid_mm: float = DEFAULT_GRID_MM,
                meta: dict | None = None) -> dict:
    """Parçaları kumaşa yerleştir (bottom-left-fill, raster + kesin doğrulama).

    Döner: {placements: [{piece, label_tr, copy, total, x_mm, y_mm, rot_deg,
    flipped, mirror_twin, unfolded, polygon_mm, bbox_mm}], used_length_cm,
    used_length_mm, fabric_width_cm, efficiency_pct, pieces_area_cm2,
    gap_mm, grid_mm, verified, min_gap_mm, warnings}.

    Raises:
        NestingError: parça kumaş eninden geniş ya da girdi geçersiz (Türkçe mesaj).
    """
    width = float(fabric_width_cm) * 10.0
    gap = max(0.0, float(gap_mm))
    grid = float(min(MAX_GRID_MM, max(MIN_GRID_MM, grid_mm)))
    if width <= 0:
        raise NestingError("Kumaş eni sıfırdan büyük olmalı.")
    copies, warnings = expand_copies(pieces_doc, meta)
    if not copies:
        raise NestingError("Kalıpta yerleştirilecek parça bulunamadı.")

    radius = gap / 2.0 + grid * math.sqrt(2) / 2.0 + 1e-6
    rows = int(math.floor(width / grid + 1e-9))

    # Her kopya/yön için yerel poligon + maske hazırla; en geçemeyenleri bul.
    too_wide: dict[str, float] = {}
    prepared: list[tuple[dict, list[dict]]] = []
    mask_cache: dict[tuple, dict] = {}
    for c in copies:
        opts = []
        for flipped, rot in _orientations(c, allow_rotate_180, allow_flip):
            key = (c["piece"], flipped, rot)
            if key not in mask_cache:
                pts = transform(c["poly"], flipped, rot, 0.0, 0.0)
                mn = pts.min(axis=0)
                local = pts - mn
                w_l, h_l = float(local[:, 0].max()), float(local[:, 1].max())
                if h_l > width + 1e-6:
                    mask_cache[key] = {"too_wide": True, "h": h_l}
                else:
                    m, k0, l0 = _piece_mask(local, grid, radius)
                    mask_cache[key] = {"too_wide": False, "local": local, "shift": mn,
                                       "w": w_l, "h": h_l, "mask": m, "k0": k0, "l0": l0}
            info = mask_cache[key]
            if info["too_wide"]:
                too_wide[c["label_tr"]] = max(too_wide.get(c["label_tr"], 0.0), info["h"])
                continue
            opts.append({"flipped": flipped, "rot": rot, **info})
        if opts:
            prepared.append((c, opts))
    if too_wide:
        parts = ", ".join(f"{k} (en az {math.ceil(v / 10.0)} cm)" for k, v in too_wide.items())
        raise NestingError(
            f"Bazı parçalar {fabric_width_cm:g} cm kumaş enine sığmıyor: {parts}. "
            "Daha geniş bir kumaş seçin.")

    # Büyük alanlı önce (eşitlikte uzun olan önce) — kararlı sıralama.
    prepared.sort(key=lambda t: (-t[0]["area_mm2"], -max(o["w"] for o in t[1])))

    # Doluluk ızgarası: x (boy) ekseni sütunlar, y (en) satırlar. Kenarlarda maske
    # pad'i taşabilsin diye her iki yanda tampon.
    pad = max(-o["k0"] for _, opts in prepared for o in opts) + 2
    total_len = sum(max(o["w"] for o in opts) + 2 * radius for _, opts in prepared)
    cols = int(math.ceil(total_len / grid)) + 4 * pad + 4
    occ = np.zeros((cols + 2 * pad, rows + 2 * pad), dtype=bool)

    placements: list[dict] = []
    used_cols = 0
    for c, opts in prepared:
        best = None
        for o in opts:
            m = o["mask"]
            # Yalnız şimdiye kadar kullanılan boy + bu parçanın boyu kadar pencerede ara.
            win_cols = min(occ.shape[0], used_cols + m.shape[0] + 2 * pad + 2)
            sub = occ[:win_cols]
            if sub.shape[0] < m.shape[0] or sub.shape[1] < m.shape[1]:
                continue
            ov = _correlate_overlap(sub, m) < 0.5
            # (a,b) dizi konumu → yerel origin hücresi i = a - pad - k0 (x), j = b - pad - l0.
            a_idx = np.arange(ov.shape[0])
            b_idx = np.arange(ov.shape[1])
            # Dizi indeksi = global hücre + pad; maske[0] = yerel hücre k0. Maske a'ya
            # oturursa parçanın yerel (0,0) hücresi global i = a - k0 - pad olur.
            i_vals = a_idx - o["k0"] - pad
            j_vals = b_idx - o["l0"] - pad
            valid_i = i_vals >= 0
            valid_j = (j_vals >= 0) & (j_vals * grid + o["h"] <= width + 1e-6)
            ok = ov & valid_i[:, None] & valid_j[None, :]
            if not ok.any():
                continue
            ai, bj = np.nonzero(ok)
            right = i_vals[ai] * grid + o["w"]
            # Öncelik: sağ uç x (kullanılan boy), sonra sol x, sonra y.
            order = np.lexsort((j_vals[bj], i_vals[ai], np.round(right, 6)))
            k = order[0]
            cand = (float(right[k]), int(i_vals[ai[k]]), int(j_vals[bj[k]]), o, int(ai[k]), int(bj[k]))
            if best is None or cand[:3] < best[:3]:
                best = cand
        if best is None:
            raise NestingError(
                f"'{c['label_tr']}' parçası yerleştirilemedi. Kumaş enini artırmayı deneyin.")
        _, i, j, o, a, b = best
        m = o["mask"]
        occ[a:a + m.shape[0], b:b + m.shape[1]] |= m
        used_cols = max(used_cols, a + m.shape[0])
        # Gerçek dönüşüm: yerel = R F p - shift; kumaş = yerel + (i g, j g).
        tx = i * grid - float(o["shift"][0])
        ty = j * grid - float(o["shift"][1])
        poly = transform(c["poly"], o["flipped"], o["rot"], tx, ty)
        placements.append({
            "piece": c["piece"], "label_tr": c["label_tr"], "copy": c["copy"],
            "total": c["total"], "x_mm": round(tx, 3), "y_mm": round(ty, 3),
            "rot_deg": round(o["rot"], 6), "flipped": bool(o["flipped"]),
            "mirror_twin": bool(c["mirror_twin"]), "unfolded": bool(c["unfolded"]),
            "grain_deg": c["grain_deg"], "area_mm2": round(c["area_mm2"], 2),
            "polygon_mm": [[round(float(x), 3), round(float(y), 3)] for x, y in poly],
            "bbox_mm": [round(float(poly[:, 0].min()), 3), round(float(poly[:, 1].min()), 3),
                        round(float(poly[:, 0].max()), 3), round(float(poly[:, 1].max()), 3)],
        })

    # Kesin doğrulama.
    check = verify_layout(placements, width, gap)
    if not check["ok"]:
        # Muhafazakâr raster ile olmamalı; olursa sessiz geçmeyiz.
        warnings.append("Uyarı: yerleşim doğrulamasında çakışma bulundu: " + "; ".join(check["problems"][:3]))

    used_len = max(p["bbox_mm"][2] for p in placements)
    area_sum = sum(p["area_mm2"] for p in placements)
    eff = 100.0 * area_sum / (width * used_len) if used_len > 0 else 0.0
    if eff < 50.0 and len(placements) > 1:
        warnings.append(f"Kumaş verimi düşük (%{eff:.0f}); daha dar bir kumaş daha az fire verebilir.")
    placements.sort(key=lambda p: (p["bbox_mm"][0], p["bbox_mm"][1]))
    return {
        "placements": placements,
        "used_length_mm": round(used_len, 2),
        "used_length_cm": round(used_len / 10.0, 1),
        "fabric_width_cm": float(fabric_width_cm),
        "efficiency_pct": round(eff, 1),
        "pieces_area_cm2": round(area_sum / 100.0, 1),
        "gap_mm": gap, "grid_mm": grid,
        "allow_rotate_180": bool(allow_rotate_180), "allow_flip": bool(allow_flip),
        "verified": bool(check["ok"]), "min_gap_mm": check["min_gap_mm"],
        "warnings": warnings,
    }


def verify_layout(placements: list[dict], width_mm: float, gap_mm: float,
                  tol: float = 1e-6) -> dict:
    """Kesin geometri ile yerleşim kontrolü: her çift arası mesafe ≥ gap ve hepsi
    kumaş eni (0 ≤ y ≤ width) ve x ≥ 0 içinde. Döner {ok, min_gap_mm, problems}."""
    polys = [np.asarray(p["polygon_mm"], dtype=float) for p in placements]
    problems: list[str] = []
    for p, poly in zip(placements, polys):
        if poly[:, 1].min() < -tol or poly[:, 1].max() > width_mm + tol or poly[:, 0].min() < -tol:
            problems.append(f"{p['label_tr']} #{p['copy']} kumaş dışına taşıyor")
    min_gap = math.inf
    boxes = [(q[:, 0].min(), q[:, 1].min(), q[:, 0].max(), q[:, 1].max()) for q in polys]
    for i in range(len(polys)):
        for j in range(i + 1, len(polys)):
            bi, bj = boxes[i], boxes[j]
            # bbox'lar gap'ten uzaksa kesin mesafeye gerek yok.
            dx = max(bj[0] - bi[2], bi[0] - bj[2], 0.0)
            dy = max(bj[1] - bi[3], bi[1] - bj[3], 0.0)
            if math.hypot(dx, dy) > gap_mm + 1.0:
                min_gap = min(min_gap, math.hypot(dx, dy))
                continue
            d = polygon_distance(polys[i], polys[j])
            min_gap = min(min_gap, d)
            if d < gap_mm - 1e-3:
                problems.append(
                    f"{placements[i]['label_tr']} #{placements[i]['copy']} ile "
                    f"{placements[j]['label_tr']} #{placements[j]['copy']} arası {d:.2f} mm")
    return {"ok": not problems, "min_gap_mm": None if min_gap is math.inf else round(min_gap, 3),
            "problems": problems}


# ---------------------------------------------------------------------------
# SVG / dosyalar
# ---------------------------------------------------------------------------
_COLORS = ["#4f86c6", "#e07a5f", "#81b29a", "#f2cc8f", "#9b72aa",
           "#3d9970", "#ff851b", "#7fdbff", "#b10dc9", "#85144b"]


def _esc(s: str) -> str:
    return (str(s).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


def nest_to_svg(result: dict, out_path: str | Path, title: str = "") -> None:
    """Yerleşimi 1:1 mm SVG'ye çiz: kumaş dikdörtgeni, parçalar (Türkçe etiket +
    kopya no), düz boy okları, üst/sol cetvel (cm çentikleri, 10 cm'de sayı)."""
    width = result["fabric_width_cm"] * 10.0
    length = max(result["used_length_mm"], 10.0)
    margin = 40.0
    vb_w = length + 2 * margin
    vb_h = width + 2 * margin + 20.0
    parts: list[str] = []
    parts.append(
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{vb_w:.1f}mm" height="{vb_h:.1f}mm" '
        f'viewBox="{-margin:.1f} {-margin:.1f} {vb_w:.1f} {vb_h:.1f}">')
    parts.append('<rect x="%.1f" y="%.1f" width="%.1f" height="%.1f" fill="#ffffff"/>'
                 % (-margin, -margin, vb_w, vb_h))
    # Kumaş.
    parts.append(f'<rect x="0" y="0" width="{length:.2f}" height="{width:.2f}" '
                 'fill="#f4efe6" stroke="#555" stroke-width="1"/>')
    # Cetvel: üst (boy) ve sol (en).
    tick = ['<g stroke="#333" stroke-width="0.4" font-family="sans-serif" font-size="8" fill="#333">']
    for cm in range(0, int(length // 10) + 1):
        x = cm * 10.0
        tl = 8.0 if cm % 10 == 0 else (5.0 if cm % 5 == 0 else 3.0)
        tick.append(f'<line x1="{x:.1f}" y1="-2" x2="{x:.1f}" y2="{-2 - tl:.1f}"/>')
        if cm % 10 == 0:
            tick.append(f'<text x="{x + 1:.1f}" y="-14" stroke="none">{cm}</text>')
    for cm in range(0, int(width // 10) + 1):
        y = cm * 10.0
        tl = 8.0 if cm % 10 == 0 else (5.0 if cm % 5 == 0 else 3.0)
        tick.append(f'<line x1="-2" y1="{y:.1f}" x2="{-2 - tl:.1f}" y2="{y:.1f}"/>')
        if cm % 10 == 0 and cm > 0:
            tick.append(f'<text x="-36" y="{y + 3:.1f}" stroke="none">{cm}</text>')
    tick.append('<text x="0" y="-26" stroke="none" font-size="9">cm (boy) →</text>')
    tick.append("</g>")
    parts.extend(tick)
    # Parçalar.
    names = sorted({p["piece"] for p in result["placements"]})
    color = {n: _COLORS[i % len(_COLORS)] for i, n in enumerate(names)}
    for p in result["placements"]:
        poly = np.asarray(p["polygon_mm"], dtype=float)
        d = "M " + " L ".join(f"{x:.2f} {y:.2f}" for x, y in poly) + " Z"
        parts.append(f'<path d="{d}" fill="{color[p["piece"]]}" fill-opacity="0.35" '
                     'stroke="#222" stroke-width="0.8"/>')
        x0, y0, x1, y1 = p["bbox_mm"]
        # Etiket konumu: poligon ağırlık merkezi (köşe ortalaması yerine alan merkezi).
        cx, cy = _centroid(poly)
        label = f'{p["label_tr"]} {p["copy"]}/{p["total"]}'
        if p["flipped"]:
            label += " (ters)"
        # Yazı boyu: parça yüksekliğinin ~1/4'ü ve etiket genişliği parçaya sığacak kadar.
        size = max(6.0, min(28.0, (y1 - y0) / 4.0, (x1 - x0) * 0.8 / (0.6 * max(1, len(label)))))
        parts.append(f'<text x="{cx:.1f}" y="{cy - size * 0.6:.1f}" font-family="sans-serif" '
                     f'font-size="{size:.1f}" text-anchor="middle" fill="#111">{_esc(label)}</text>')
        if p.get("unfolded"):
            parts.append(f'<text x="{cx:.1f}" y="{cy + size * 1.9:.1f}" font-family="sans-serif" '
                         f'font-size="{size * 0.6:.1f}" text-anchor="middle" fill="#333">(açılmış katlı parça)</text>')
        # Düz boy oku — daima kumaş boyuna (x) paralel.
        al = max(20.0, min(200.0, (x1 - x0) * 0.5))
        ay = cy + size * 0.6
        ax0, ax1 = cx - al / 2, cx + al / 2
        h = min(8.0, al / 6)
        parts.append(
            f'<g stroke="#111" stroke-width="0.8" fill="none">'
            f'<line x1="{ax0:.1f}" y1="{ay:.1f}" x2="{ax1:.1f}" y2="{ay:.1f}"/>'
            f'<polyline points="{ax0 + h:.1f},{ay - h / 2:.1f} {ax0:.1f},{ay:.1f} {ax0 + h:.1f},{ay + h / 2:.1f}"/>'
            f'<polyline points="{ax1 - h:.1f},{ay - h / 2:.1f} {ax1:.1f},{ay:.1f} {ax1 - h:.1f},{ay + h / 2:.1f}"/>'
            "</g>")
    footer = (f'Kumaş eni {result["fabric_width_cm"]:g} cm · kullanılan boy '
              f'{result["used_length_cm"]:g} cm · verim %{result["efficiency_pct"]:g} · '
              f'parça arası {result["gap_mm"]:g} mm · ölçek 1:1')
    if title:
        footer = f"{title} — " + footer
    parts.append(f'<text x="0" y="{width + 16:.1f}" font-family="sans-serif" font-size="9" '
                 f'fill="#333">{_esc(footer)}</text>')
    parts.append("</svg>")
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(parts), encoding="utf-8")


def _centroid(poly: np.ndarray) -> tuple[float, float]:
    x, y = poly[:, 0], poly[:, 1]
    x2, y2 = np.roll(x, -1), np.roll(y, -1)
    cr = x * y2 - x2 * y
    a = cr.sum() / 2.0
    if abs(a) < 1e-9:
        return float(x.mean()), float(y.mean())
    return float(((x + x2) * cr).sum() / (6 * a)), float(((y + y2) * cr).sum() / (6 * a))


def nest_pattern_dir(pattern_dir: str | Path, **kwargs: Any) -> dict:
    """data/patterns/<id>/ dizinindeki pieces.json (+ meta.json) için yerleşim
    yap; nest.svg ve nest.json yaz. Sonucu döner (svg/json yolları dahil değil)."""
    d = Path(pattern_dir)
    pieces_doc = json.loads((d / "pieces.json").read_text(encoding="utf-8"))
    meta = None
    if (d / "meta.json").exists():
        try:
            meta = json.loads((d / "meta.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            meta = None
    result = nest_pieces(pieces_doc, meta=meta, **kwargs)
    result["pattern_id"] = pieces_doc.get("pattern_id") or d.name
    title = str((meta or {}).get("name") or pieces_doc.get("design") or "")
    nest_to_svg(result, d / "nest.svg", title=title)
    (d / "nest.json").write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    return result
