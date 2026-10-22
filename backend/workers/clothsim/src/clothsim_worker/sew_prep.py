"""2D kalıp → 3D dikiş simülasyonu girdisi (F2) — SAF PYTHON (bpy YOK).

Blender'a gidecek her şey burada hazırlanır; `blender_sew.py` yalnız bu modülün
ürettiği JSON'u okuyup mesh'i kurar, kumaşı simüle eder ve sonucu yazar. Böylece
geometrinin tamamı (üçgenleme, dikiş eşleme, yerleşim) Blender'sız test edilebilir.

Girdi sözleşmesi: F1 `pieces.json` (mm, y YUKARI, CCW poligon, kenarlar seam_line
indeksleri üzerinde from→to) + manken mesh'i (metre, glTF çerçevesi: Y-yukarı,
ön yüz +Z, ayak tabanı y=0, XZ'de merkezli).

Akış:
1. Kenar örnekleme: her kenar yay-uzunluğu boyunca ~`h` aralıkla örneklenir. Birbirine
   dikilecek kenarlar (seams) AYNI nokta sayısını alır (union-find grupları) → dikiş
   vertexleri parça mesh'inde GERÇEK vertex olur, sonradan en-yakın eşleme yapılmaz.
2. Üçgenleme: sınır noktaları + iç altıgen ızgara → scipy Delaunay; ağırlık merkezi
   poligon dışındaki üçgenler atılır. Bir sınır parçası üçgenlemede yoksa (ince pens
   ucu vb.) o parça ve DİKİŞ EŞİ aynı oranda bölünüp yeniden üçgenlenir (sayılar eşit
   kalır).
3. Örnekler (instance): mirror+fold_edge → katlama çizgisi etrafında aynalanıp tek tam
   parça (yarılar @R/@L kenarları taşır); mirror+fold yok ya da quantity=2 → sağ (@R)
   ve aynalı sol (@L) iki parça; quantity=1 → tek parça (@C).
4. Dikiş çiftleri: a↔b kenar eşleri aynı taraf örnekleri arasında (R↔R, L↔L); a==b ise
   R↔L. reverse=true → a'nın başı b'nin sonuna.
5. Yerleşim (glTF çerçevesi, metre): gövde parçaları gövdeyi saran eliptik silindire
   (ön yarı / arka yarı), kollar kol ekseni etrafında silindire, kloş etek koniye
   İZOMETRİK sarılır; R örnekleri +x, L örnekleri −x tarafına. Manken içine girmesin
   diye boşluk bırakılır, kol kapsülüne giren noktalar dışarı itilir.
6. Dinlenme şekli: düz kalıp yerleşimi (atlas) Blender'da "rest shape key" olur →
   yerleşimdeki küçük bozulmalar kumaşın gerçek ölçüsünü DEĞİŞTİRMEZ; UV = aynı atlas
   (tek tip doku yoğunluğu, [0,1]'e normalize, düz boy = v ekseni).
"""
from __future__ import annotations

import math
from typing import Any

import numpy as np

# Hedef üçgen kenar uzunluğu (mm). 12 mm ≈ tişört için ~6-8k vertex (CPU sim makul).
DEFAULT_EDGE_MM = 12.0
# Serbest (dikilmeyen) sınırda bu açıdan keskin köşeler korunur (derece).
_CORNER_DEG = 25.0
# İç ızgara noktalarının sınıra en yakın mesafesi (h katı).
_INTERIOR_CLEAR = 0.6
# Gövde ile kumaş arası başlangıç boşluğu (m).
DEFAULT_GAP_M = 0.06
# Kol kapsülünden itme boşluğu (m).
_ARM_GAP_M = 0.03

# Tasarıma göre parça rolü (yerleşim stratejisi). Tanımsız tasarımlarda ada göre tahmin.
ROLE_BY_DESIGN: dict[str, dict[str, str]] = {
    "teagan": {"front": "torso_front", "back": "torso_back", "sleeve": "sleeve"},
    "penelope": {"front": "skirt_front", "back": "skirt_back"},
    "sandy": {"skirt": "circle_skirt"},
}


class SewPrepError(Exception):
    """Kullanıcıya gösterilebilir (Türkçe) hazırlık hatası."""


# --- temel 2B geometri -----------------------------------------------------------
def polyline_indices(n: int, i: int, j: int) -> list[int]:
    """seam_line üzerinde i→j (artan, sona gelince başa sararak) indeks listesi."""
    out = [i]
    k = i
    while k != j:
        k = (k + 1) % n
        out.append(k)
        if len(out) > n + 1:
            break
    return out


def polyline_length(pts: np.ndarray) -> float:
    if len(pts) < 2:
        return 0.0
    return float(np.linalg.norm(np.diff(pts, axis=0), axis=1).sum())


def sample_at(pts: np.ndarray, fracs: list[float] | np.ndarray) -> np.ndarray:
    """Polyline'ı yay-uzunluğu oranlarında (0..1) örnekle."""
    pts = np.asarray(pts, dtype=float)
    seg = np.linalg.norm(np.diff(pts, axis=0), axis=1)
    cum = np.concatenate([[0.0], np.cumsum(seg)])
    total = cum[-1]
    if total <= 0:
        return np.repeat(pts[:1], len(fracs), axis=0)
    s = np.clip(np.asarray(fracs, dtype=float), 0.0, 1.0) * total
    x = np.interp(s, cum, pts[:, 0])
    y = np.interp(s, cum, pts[:, 1])
    return np.column_stack([x, y])


def resample(pts: np.ndarray, n: int) -> np.ndarray:
    """Polyline'ı uçlar dahil n+1 eşit aralıklı noktaya yeniden örnekle."""
    return sample_at(pts, np.linspace(0.0, 1.0, max(1, n) + 1))


def points_in_polygon(pts: np.ndarray, poly: np.ndarray) -> np.ndarray:
    """Vektörel ışın-atma (çift-tek) içerme testi."""
    pts = np.asarray(pts, dtype=float)
    poly = np.asarray(poly, dtype=float)
    x, y = pts[:, 0][:, None], pts[:, 1][:, None]
    x1, y1 = poly[:, 0][None, :], poly[:, 1][None, :]
    x2, y2 = np.roll(poly[:, 0], -1)[None, :], np.roll(poly[:, 1], -1)[None, :]
    cond = (y1 > y) != (y2 > y)
    with np.errstate(divide="ignore", invalid="ignore"):
        xint = (x2 - x1) * (y - y1) / (y2 - y1) + x1
    hit = cond & (x < xint)
    return (hit.sum(axis=1) % 2) == 1


def dist_to_segments(pts: np.ndarray, poly: np.ndarray, closed: bool = True) -> np.ndarray:
    """Her noktanın poligon kenarlarına en kısa mesafesi."""
    pts = np.asarray(pts, dtype=float)
    a = np.asarray(poly, dtype=float)
    b = np.roll(a, -1, axis=0) if closed else a[1:]
    if not closed:
        a = a[:-1]
    ab = b - a
    ll = np.maximum((ab ** 2).sum(axis=1), 1e-12)
    out = np.full(len(pts), np.inf)
    # Bellek: nokta x segment matrisini parçalar halinde işle.
    step = max(1, 200_000 // max(1, len(a)))
    for k in range(0, len(pts), step):
        p = pts[k:k + step][:, None, :]
        t = np.clip(((p - a[None]) * ab[None]).sum(axis=2) / ll[None], 0.0, 1.0)
        proj = a[None] + t[..., None] * ab[None]
        d = np.linalg.norm(p - proj, axis=2).min(axis=1)
        out[k:k + step] = d
    return out


def signed_area(poly: np.ndarray) -> float:
    p = np.asarray(poly, dtype=float)
    return 0.5 * float(np.dot(p[:, 0], np.roll(p[:, 1], -1)) - np.dot(np.roll(p[:, 0], -1), p[:, 1]))


def reflect(pts: np.ndarray, p0: np.ndarray, p1: np.ndarray) -> np.ndarray:
    """Noktaları p0-p1 doğrusuna göre aynala."""
    d = np.asarray(p1, float) - np.asarray(p0, float)
    d = d / max(np.linalg.norm(d), 1e-12)
    rel = np.asarray(pts, float) - p0
    along = rel @ d
    return p0 + 2.0 * along[:, None] * d[None, :] - rel


# --- kenar örnekleme (dikiş eşleri eşit sayıda) ---------------------------------
def _corner_breaks(poly: np.ndarray, idx: list[int]) -> list[int]:
    """Serbest sınır parçasında keskin köşe noktaları (iç indeksler, uçlar hariç)."""
    out = []
    n = len(poly)
    for k in idx[1:-1]:
        a, b, c = poly[(k - 1) % n], poly[k], poly[(k + 1) % n]
        v1, v2 = b - a, c - b
        l1, l2 = np.linalg.norm(v1), np.linalg.norm(v2)
        if l1 < 1e-9 or l2 < 1e-9:
            continue
        cosang = float(np.clip(np.dot(v1, v2) / (l1 * l2), -1, 1))
        if math.degrees(math.acos(cosang)) > _CORNER_DEG:
            out.append(k)
    return out


def boundary_segments(piece: dict) -> list[dict]:
    """Parça çevresini sıralı parçalara böl: tanımlı kenarlar + aradaki serbest boşluklar.

    Döner: [{"id": edge_id|None, "idx": [seam_line indeksleri from..to]}] — çevreyi tam,
    bir kez kapsar (ardışık parçalar uç noktayı paylaşır).
    """
    poly = np.asarray(piece["seam_line"], dtype=float)
    n = len(poly)
    edges = sorted(piece.get("edges") or [], key=lambda e: int(e["from"]))
    if not edges:
        segs_raw = [(None, list(range(n)) + [0])]
    else:
        segs_raw = []
        for k, e in enumerate(edges):
            i, j = int(e["from"]) % n, int(e["to"]) % n
            segs_raw.append((e["id"], polyline_indices(n, i, j)))
            nxt = edges[(k + 1) % len(edges)]
            ni = int(nxt["from"]) % n
            if ni != j:
                segs_raw.append((None, polyline_indices(n, j, ni)))
    # Serbest boşlukları keskin köşelerde böl (kalıbın şekli korunsun).
    segs: list[dict] = []
    for eid, idx in segs_raw:
        if eid is None:
            br = _corner_breaks(poly, idx)
            cuts = [idx[0]] + br + [idx[-1]]
            pos = {v: p for p, v in enumerate(idx)}
            for a, b in zip(cuts[:-1], cuts[1:]):
                pa, pb = pos[a], len(idx) - 1 if b == idx[-1] else pos[b]
                segs.append({"id": None, "idx": idx[pa:pb + 1]})
        else:
            segs.append({"id": eid, "idx": idx})
    return segs


class _UF:
    """Kenar grupları için yönlü union-find (eşler arası yön işareti tutar)."""

    def __init__(self) -> None:
        self.parent: dict[str, str] = {}
        self.sign: dict[str, int] = {}  # köke göre yön (+1 aynı, -1 ters)

    def add(self, x: str) -> None:
        if x not in self.parent:
            self.parent[x] = x
            self.sign[x] = 1

    def find(self, x: str) -> tuple[str, int]:
        s = 1
        while self.parent[x] != x:
            s *= self.sign[x]
            x = self.parent[x]
        return x, s

    def union(self, a: str, b: str, rel: int) -> None:
        ra, sa = self.find(a)
        rb, sb = self.find(b)
        if ra == rb:
            return
        # sign(b→a) = rel  ⇒  sign(rb→ra) = sa*rel*sb
        self.parent[rb] = ra
        self.sign[rb] = sa * rel * sb


def edge_sampling(pieces: list[dict], seams: list[dict], h_mm: float) -> tuple[dict, _UF]:
    """Her tanımlı kenar için örnekleme oranları (0..1, uçlar dahil, from→to yönünde).

    Dikiş eşleri aynı sayıda nokta alır; reverse=true eşte oranlar ters (1-f) tutulur.
    Döner: ({edge_id: [f0..fn]}, union-find).
    """
    lengths: dict[str, float] = {}
    for p in pieces:
        poly = np.asarray(p["seam_line"], dtype=float)
        for e in p.get("edges") or []:
            idx = polyline_indices(len(poly), int(e["from"]) % len(poly), int(e["to"]) % len(poly))
            lengths[e["id"]] = polyline_length(poly[idx])
    uf = _UF()
    for eid in lengths:
        uf.add(eid)
    for s in seams:
        a, b = s["a"], s["b"]
        if a in lengths and b in lengths and a != b:
            uf.union(a, b, -1 if s.get("reverse") else 1)
    groups: dict[str, list[str]] = {}
    for eid in lengths:
        r, _ = uf.find(eid)
        groups.setdefault(r, []).append(eid)
    fracs: dict[str, list[float]] = {}
    for root, members in groups.items():
        n = max(1, max(int(round(lengths[m] / h_mm)) for m in members))
        base = np.linspace(0.0, 1.0, n + 1)
        for m in members:
            _, s = uf.find(m)
            fracs[m] = list(base) if s == 1 else list(1.0 - base[::-1])
    return fracs, uf


def split_edge_segment(fracs: dict, uf: _UF, eid: str, k: int) -> None:
    """eid kenarının k. alt parçasını (fracs[k]..fracs[k+1]) ortadan böl — grubun
    tüm üyelerinde aynı yerden (sayılar eşit kalsın)."""
    root, s_e = uf.find(eid)
    f = fracs[eid]
    mid = 0.5 * (f[k] + f[k + 1])
    canon = mid if s_e == 1 else 1.0 - mid
    for m in list(fracs):
        r, s = uf.find(m)
        if r != root:
            continue
        val = canon if s == 1 else 1.0 - canon
        fm = fracs[m]
        if not any(abs(val - x) < 1e-9 for x in fm):
            fm.append(val)
            fm.sort()


# --- üçgenleme ------------------------------------------------------------------
def _hex_grid(poly: np.ndarray, h: float) -> np.ndarray:
    lo, hi = poly.min(axis=0), poly.max(axis=0)
    dy = h * math.sqrt(3) / 2
    ys = np.arange(lo[1] + dy / 2, hi[1], dy)
    pts = []
    for r, y in enumerate(ys):
        off = (h / 2) if r % 2 else 0.0
        xs = np.arange(lo[0] + off + h / 4, hi[0], h)
        pts.append(np.column_stack([xs, np.full(len(xs), y)]))
    if not pts:
        return np.zeros((0, 2))
    return np.concatenate(pts)


def triangulate_loop(boundary: np.ndarray, h: float) -> tuple[np.ndarray, np.ndarray, list[int]]:
    """Kapalı sınır döngüsünü (ilk nokta tekrarlanmaz) üçgenle.

    Döner: (noktalar [sınır önce, sonra iç], CCW üçgenler, kayıp sınır parçası indeksleri
    k (boundary[k]→boundary[k+1] üçgenlemede yoksa)).
    """
    from scipy.spatial import Delaunay

    B = np.asarray(boundary, dtype=float)
    nb = len(B)
    grid = _hex_grid(B, h)
    if len(grid):
        inside = points_in_polygon(grid, B)
        grid = grid[inside]
    if len(grid):
        d = dist_to_segments(grid, B)
        grid = grid[d > _INTERIOR_CLEAR * h]
    pts = np.concatenate([B, grid]) if len(grid) else B.copy()
    tri = Delaunay(pts)
    faces = tri.simplices
    cent = pts[faces].mean(axis=1)
    keep = points_in_polygon(cent, B)
    faces = faces[keep]
    # Kenar ortaları da içeride/sınırda olmalı (içbükey köşede dışarı taşan üçgen).
    if len(faces):
        mids = np.concatenate([(pts[faces[:, a]] + pts[faces[:, b]]) / 2 for a, b in ((0, 1), (1, 2), (2, 0))])
        ok_in = points_in_polygon(mids, B) | (dist_to_segments(mids, B) < 1e-6 * max(h, 1.0) + 1e-9)
        ok = ok_in.reshape(3, -1).all(axis=0)
        faces = faces[ok]
    # Dejenere üçgenler
    if len(faces):
        p0, p1, p2 = pts[faces[:, 0]], pts[faces[:, 1]], pts[faces[:, 2]]
        area = 0.5 * ((p1[:, 0] - p0[:, 0]) * (p2[:, 1] - p0[:, 1]) - (p1[:, 1] - p0[:, 1]) * (p2[:, 0] - p0[:, 0]))
        faces = faces[np.abs(area) > 1e-6 * h * h]
        area = area[np.abs(area) > 1e-6 * h * h]
        flip = area < 0
        faces[flip] = faces[flip][:, [0, 2, 1]]
    # Sınır parçaları üçgenlemede var mı?
    es = set()
    for a, b in ((0, 1), (1, 2), (2, 0)):
        for u, v in zip(faces[:, a], faces[:, b]):
            es.add((min(u, v), max(u, v)))
    missing = [k for k in range(nb) if (min(k, (k + 1) % nb), max(k, (k + 1) % nb)) not in es]
    return pts, faces, missing


def build_piece_mesh(piece: dict, fracs: dict, uf: _UF, h_mm: float,
                     max_iter: int = 8) -> dict:
    """Bir kalıp parçasının (yarı parça dahil, aynalamasız) 2B mesh'i.

    Döner: {"pts": (N,2) mm, "faces": (F,3), "edges": {edge_id: [vertex idx from→to]},
            "boundary": [loop vertex idx]}.
    """
    poly = np.asarray(piece["seam_line"], dtype=float)
    segs = boundary_segments(piece)
    free_n: dict[int, list[float]] = {}
    for it in range(max_iter):
        loop: list[np.ndarray] = []
        owner: list[tuple[int, int]] = []  # her loop noktası → (seg indeksi, alt-parça k)
        edge_vidx: dict[str, list[int]] = {}
        for si, seg in enumerate(segs):
            line = poly[seg["idx"]]
            if seg["id"] is not None:
                f = fracs[seg["id"]]
            else:
                if si not in free_n:
                    n = max(1, int(round(polyline_length(line) / h_mm)))
                    free_n[si] = list(np.linspace(0.0, 1.0, n + 1))
                f = free_n[si]
            sp = sample_at(line, f)
            start = len(loop)
            for k in range(len(sp) - 1):  # son nokta = sonraki parçanın ilk noktası
                loop.append(sp[k])
                owner.append((si, k))
            if seg["id"] is not None:
                ids = list(range(start, start + len(sp)))
                edge_vidx[seg["id"]] = ids  # son indeks (start+len-1) sonraki parçanın başı
        nb = len(loop)
        for eid in edge_vidx:
            edge_vidx[eid] = [v % nb for v in edge_vidx[eid]]
        B = np.asarray(loop)
        if signed_area(B) < 0:
            raise SewPrepError(f"'{piece.get('label_tr', piece['name'])}' parçasının yönü ters (CW).")
        pts, faces, missing = triangulate_loop(B, h_mm)
        if not missing:
            return {"pts": pts, "faces": faces, "edges": edge_vidx, "boundary": list(range(nb))}
        # Kayıp sınır parçalarını böl (dikiş eşleriyle birlikte) ve tekrar dene.
        for k in missing:
            si, sub = owner[k]
            seg = segs[si]
            if seg["id"] is not None:
                split_edge_segment(fracs, uf, seg["id"], sub)
            else:
                f = free_n[si]
                mid = 0.5 * (f[sub] + f[sub + 1])
                if all(abs(mid - x) > 1e-9 for x in f):
                    f.append(mid)
                    f.sort()
    raise SewPrepError(f"'{piece.get('label_tr', piece['name'])}' parçası üçgenlenemedi.")


# --- örnekler (aynalama / çift parça) ----------------------------------------------
def piece_instances(piece: dict, mesh: dict) -> list[dict]:
    """Bir parçanın 3B'de kullanılacak örnekleri.

    Döner: [{"name", "side": "R"|"L"|"C"|"F", "pts", "faces", "edges": {id@side: idx},
             "center_x": float|None, "fold": bool}]; "F" = katlı tam parça (R+L yarılar).
    """
    pts, faces, edges = mesh["pts"], mesh["faces"], mesh["edges"]
    name = piece["name"]
    fold = piece.get("fold_edge") if piece.get("mirror") else None
    if fold and fold in edges:
        fidx = edges[fold]
        p0, p1 = pts[fidx[0]], pts[fidx[-1]]
        on_fold = set(fidx)
        n = len(pts)
        mirror_map = np.full(n, -1, dtype=int)
        new_pts = [pts]
        nxt = n
        for v in range(n):
            if v in on_fold:
                mirror_map[v] = v
            else:
                mirror_map[v] = nxt
                nxt += 1
        others = np.array([v for v in range(n) if v not in on_fold], dtype=int)
        refl = reflect(pts[others], p0, p1)
        # Katlama çizgisindeki noktaları tam çizgiye oturt (yuvarlama).
        all_pts = np.concatenate([pts, refl]) if len(refl) else pts.copy()
        all_pts[list(on_fold)] = reflect(pts[list(on_fold)], p0, p1) * 0.5 + pts[list(on_fold)] * 0.5
        mf = mirror_map[faces][:, [0, 2, 1]]
        all_faces = np.concatenate([faces, mf])
        ed: dict[str, list[int]] = {}
        for eid, idx in edges.items():
            if eid == fold:
                continue
            ed[f"{eid}@R"] = list(idx)
            ed[f"{eid}@L"] = [int(mirror_map[v]) for v in idx]
        cx = float(np.mean([p0[0], p1[0]]))
        return [{"name": name, "side": "F", "pts": all_pts, "faces": all_faces, "edges": ed,
                 "fold_line": [p0.tolist(), p1.tolist()], "center_x": cx, "base_n": n,
                 "mirror_map": mirror_map.tolist()}]
    pair = bool(piece.get("mirror")) or int(piece.get("quantity", 1)) >= 2
    if pair:
        out = []
        for side in ("R", "L"):
            # L: 2B'de aynı parça; 3B'de dünya x'inde aynalanır (geometri aynası).
            out.append({"name": name, "side": side, "pts": pts.copy(), "faces": faces.copy(),
                        "edges": {f"{k}@{side}": list(v) for k, v in edges.items()},
                        "center_x": None})
        return out
    return [{"name": name, "side": "C", "pts": pts.copy(), "faces": faces.copy(),
             "edges": {f"{k}@C": list(v) for k, v in edges.items()}, "center_x": None}]


def seam_pairs(seams: list[dict], inst_edges: dict[str, tuple[int, list[int]]]) -> tuple[list, list[str]]:
    """Dikiş tanımlarını örnek-kenar çiftlerine çevir.

    inst_edges: {"front.side@R": (global_offset, [yerel idx])}. Döner: ([(a_key, b_key,
    reverse, kind)], uyarılar)."""
    out, warn = [], []
    for s in seams:
        a, b, rev = s["a"], s["b"], bool(s.get("reverse"))
        kind = s.get("kind", "seam")
        if a == b:
            if f"{a}@R" in inst_edges and f"{a}@L" in inst_edges:
                out.append((f"{a}@R", f"{a}@L", rev, kind))
            else:
                warn.append(f"{a} kendi eşine dikilemedi (aynalı kopya yok)")
            continue
        done = False
        for side in ("R", "L", "C"):
            ka, kb = f"{a}@{side}", f"{b}@{side}"
            if ka in inst_edges and kb in inst_edges:
                out.append((ka, kb, rev, kind))
                done = True
        if not done:
            warn.append(f"{a} ↔ {b} dikişi eşlenemedi")
    return out, warn


# --- manken analizi ---------------------------------------------------------------
def analyze_body(verts: np.ndarray, faces: np.ndarray) -> dict[str, Any]:
    """Manken (metre, Y-yukarı, ön +Z, ayak y=0) üzerinden seviye ve gövde/kol modeli."""
    v = np.asarray(verts, dtype=float)
    y0 = float(v[:, 1].min())
    H = float(v[:, 1].max()) - y0
    try:
        from common.body_morph import detect_levels
        vn = (v - [0.0, y0, 0.0]) / H
        lv = detect_levels(vn, np.asarray(faces))
    except Exception:  # noqa: BLE001 — seviyeler bulunamazsa ortalama oranlar
        lv = {"crotch": 0.45, "hip": 0.53, "waist": 0.63, "chest": 0.72, "armpit": 0.77, "neck": 0.85}
    lev = {k: y0 + t * H for k, t in lv.items()}
    # Omuz yarı genişliği: koltuk altının hemen altında gövde |x|.
    band = v[(v[:, 1] > lev["armpit"] - 0.03 * H) & (v[:, 1] < lev["armpit"] - 0.01 * H)]
    if len(band):
        cx = band[np.abs(band[:, 0]) < 0.25 * H]
        sx = float(np.abs(cx[:, 0]).max()) if len(cx) else 0.1 * H
    else:
        sx = 0.1 * H
    shoulder_x = sx
    # Kollar: koltuk altı üstünde |x| > shoulder_x*1.1 olan vertexler.
    arm = v[(np.abs(v[:, 0]) > shoulder_x * 1.15) & (v[:, 1] > lev["armpit"] - 0.08 * H)]
    arm_info = None
    if len(arm) > 20:
        ax = np.abs(arm[:, 0])
        bins = np.linspace(ax.min(), ax.max() + 1e-6, 16)
        cy, cz, rr, xs = [], [], [], []
        for lo, hi in zip(bins[:-1], bins[1:]):
            m = (ax >= lo) & (ax < hi)
            if m.sum() < 4:
                continue
            p = arm[m]
            c = np.array([p[:, 1].mean(), p[:, 2].mean()])
            r = float(np.linalg.norm(p[:, 1:] - c, axis=1).max())
            xs.append((lo + hi) / 2)
            cy.append(c[0])
            cz.append(c[1])
            rr.append(r)
        if xs:
            arm_info = {"x": [float(x) for x in xs], "cy": [float(x) for x in cy],
                        "cz": [float(x) for x in cz], "r": [float(x) for x in rr],
                        "x_min": float(ax.min()), "x_max": float(ax.max()),
                        "cy_mean": float(np.median(cy)), "cz_mean": float(np.median(cz)),
                        "r_max": float(np.median(rr))}
    # Omuz üstü: koltuk altı üstünde, gövde merkez kümesinin yarı-genişliğinin
    # omuz genişliğinin %55'inin altına düştüğü ilk seviye (boyun kökü).
    shoulder_top = lev["armpit"] + 0.05 * H
    ys = np.arange(lev["armpit"], lev["neck"] + 0.02 * H, 0.004 * H)
    for y in ys:
        sl = v[(np.abs(v[:, 1] - y) < 0.006 * H) & (np.abs(v[:, 0]) < shoulder_x * 1.6)]
        if len(sl) and float(np.abs(sl[:, 0]).max()) < 0.55 * shoulder_x * 1.2:
            shoulder_top = float(y)
            break
    # Omuz hattının en üst noktası (|x| omuz bandı) — gömleğin oturacağı yer.
    sh = v[(np.abs(v[:, 0]) > 0.5 * shoulder_x) & (np.abs(v[:, 0]) < shoulder_x * 1.1)
           & (v[:, 1] > lev["armpit"]) & (v[:, 1] < lev["neck"])]
    shoulder_y = float(sh[:, 1].max()) if len(sh) else shoulder_top
    return {"height": H, "y0": y0, "levels": lev, "levels_t": lv, "shoulder_x": shoulder_x,
            "shoulder_top": shoulder_top, "shoulder_y": shoulder_y, "arm": arm_info}


def _torso_points(verts: np.ndarray, body: dict, y_lo: float, y_hi: float) -> np.ndarray:
    v = np.asarray(verts, dtype=float)
    m = (v[:, 1] >= y_lo) & (v[:, 1] <= y_hi)
    # Kollar hariç (koltuk altı üstünde omuz genişliği dışı).
    arm = (np.abs(v[:, 0]) > body["shoulder_x"] * 1.15) & (v[:, 1] > body["levels"]["armpit"] - 0.04 * body["height"])
    return v[m & ~arm]


def fit_wrap_ellipse(verts: np.ndarray, body: dict, y_lo: float, y_hi: float,
                     gap: float) -> dict:
    """y aralığındaki gövde noktalarını (kollar hariç) içine alan, ön/arka yarıları ayrı
    yarı-eksenli elips + boşluk."""
    P = _torso_points(verts, body, y_lo, y_hi)
    if len(P) < 10:
        P = np.asarray(verts, dtype=float)
    a0 = max(float(np.abs(P[:, 0]).max()), 0.05)
    z0 = 0.5 * (float(P[:, 2].max()) + float(P[:, 2].min()))
    bf0 = max(float(P[:, 2].max()) - z0, 0.04)
    bb0 = max(z0 - float(P[:, 2].min()), 0.04)
    dz = P[:, 2] - z0
    bz = np.where(dz >= 0, bf0, bb0)
    k = float(np.sqrt((P[:, 0] / a0) ** 2 + (dz / bz) ** 2).max())
    k = max(k, 1.0)
    return {"A": k * a0 + gap, "Bf": k * bf0 + gap, "Bb": k * bb0 + gap, "z0": z0}


def _half_width(inst: dict, piece: dict) -> float:
    """Panelin merkez çizgisinden yana en büyük genişliği (m)."""
    cx, side = _center_x(inst, piece)
    u = (inst["pts"][:, 0] - cx) * side
    return float(u.max()) / 1000.0


def perimeter_ellipse(verts: np.ndarray, body: dict, y_lo: float, y_hi: float,
                      perimeter: float) -> dict:
    """Gövde kesitinin en/boy oranında, verilen ÇEVREDE elips (merkez = gövde ortası)."""
    P = _torso_points(verts, body, y_lo, y_hi)
    if len(P) < 10:
        P = np.asarray(verts, dtype=float)
    z0 = 0.5 * (float(P[:, 2].max()) + float(P[:, 2].min()))
    e = float(np.clip((P[:, 2].max() - P[:, 2].min()) / max(2 * np.abs(P[:, 0]).max(), 1e-6), 0.5, 1.0))
    _, s = _ellipse_arc_table(1.0, e)
    a = perimeter / (2 * s[-1])
    return {"A": a, "Bf": a * e, "Bb": a * e, "z0": z0, "perimeter": perimeter}


def _ellipse_arc_table(A: float, B: float, n: int = 721) -> tuple[np.ndarray, np.ndarray]:
    """Çeyrek+ elips yayı: açı α ∈ [0, π] (0 = merkez önü/arkası, π/2 = yan) için
    yay uzunluğu tablosu (x = A sinα, z = B cosα)."""
    al = np.linspace(0.0, math.pi, n)
    x, z = A * np.sin(al), B * np.cos(al)
    s = np.concatenate([[0.0], np.cumsum(np.hypot(np.diff(x), np.diff(z)))])
    return al, s


def wrap_on_ellipse(u: np.ndarray, A: float, B: float, z0: float, front: bool) -> np.ndarray:
    """İşaretli yay uzunluğu u (m, merkez çizgisinden) → (x, z). front: +z yarı."""
    al, s = _ellipse_arc_table(A, B)
    a = np.interp(np.abs(u), s, al) * np.sign(u)
    x = A * np.sin(a)
    z = B * np.cos(a)
    return np.column_stack([x, z0 + z if front else z0 - z])


# --- yerleşim -----------------------------------------------------------------------
def _role_of(design: str, name: str) -> str:
    r = ROLE_BY_DESIGN.get(design, {}).get(name)
    if r:
        return r
    n = name.lower()
    if "sleeve" in n:
        return "sleeve"
    if "skirt" in n:
        return "circle_skirt"
    if "front" in n:
        return "torso_front"
    if "back" in n:
        return "torso_back"
    return "torso_front"


def _center_x(inst: dict, piece: dict) -> tuple[float, int]:
    """Parçanın merkez (ön orta/arka orta) çizgisinin 2B x'i ve yan yönü (+1: yan +x'te)."""
    pts = inst["pts"]
    if inst.get("center_x") is not None:
        cx = inst["center_x"]
        # Katlı tam parça: yan yönü R yarısının olduğu taraf (orijinal yarı).
        base = pts[: inst.get("base_n", len(pts))]
        return cx, (1 if base[:, 0].mean() >= cx else -1)
    edges = {e["id"]: e for e in piece.get("edges") or []}
    poly = np.asarray(piece["seam_line"], dtype=float)
    for key in ("cb", "cf"):
        eid = f"{piece['name']}.{key}"
        if eid in edges:
            e = edges[eid]
            cx = 0.5 * (poly[int(e["from"])][0] + poly[int(e["to"])][0])
            return cx, (1 if poly[:, 0].mean() >= cx else -1)
    lo, hi = pts[:, 0].min(), pts[:, 0].max()
    return float(lo), 1


def place_torso(inst: dict, piece: dict, ell: dict, top_y: float, front: bool,
                layer: float = 0.0) -> np.ndarray:
    """Gövde/etek panelini elips silindire izometrik sar (mm → m)."""
    pts = inst["pts"] / 1000.0
    cx, side = _center_x(inst, piece)
    u = (pts[:, 0] - cx / 1000.0) * side
    y = pts[:, 1] - pts[:, 1].max() + top_y
    xz = wrap_on_ellipse(u, ell["A"] + layer, (ell["Bf"] if front else ell["Bb"]) + layer, ell["z0"], front)
    return np.column_stack([xz[:, 0], y, xz[:, 1]])


def place_sleeve(inst: dict, piece: dict, body: dict, x_start: float, gap: float) -> tuple[np.ndarray, dict]:
    """Kolu kol ekseni etrafında silindire sar: kol başı tepesi omuza (x_start), etek
    ele doğru; ön yarı (cap_front tarafı) +z'ye bakar."""
    pts = inst["pts"] / 1000.0
    arm = body.get("arm")
    edges = {e["id"]: e for e in piece.get("edges") or []}
    poly = np.asarray(piece["seam_line"], dtype=float) / 1000.0
    # Kol başı tepe noktası: cap_front'un sonu (= cap_back'in başı) ya da en üst nokta.
    cf = edges.get(f"{piece['name']}.cap_front")
    if cf is not None:
        top = poly[int(cf["to"])]
        front_dir = 1 if poly[int(cf["from"])][0] > top[0] else -1
    else:
        top = pts[np.argmax(pts[:, 1])]
        front_dir = 1
    width = float(pts[:, 0].max() - pts[:, 0].min())
    R = width / (2 * math.pi)
    if arm:
        cy, cz, r_arm = arm["cy_mean"], arm["cz_mean"], arm["r_max"]
    else:
        H = body["height"]
        cy, cz, r_arm = body["levels"]["armpit"] + 0.02 * H, 0.0, 0.035
    theta = (pts[:, 0] - top[0]) * front_dir / R  # izometrik açı (dinlenmede)
    along = top[1] - pts[:, 1]  # kol başı tepesinden uzaklık (≥0)
    x = x_start + along
    # Yarıçap kol boyunca YEREL kol kalınlığına göre (omuz/deltoit kalın, bilek ince):
    # kumaş kalın kısımdan geçerken sıkışıp topaklanmasın (ölçüm günlüğü F2 r4:
    # tek ortalama yarıçapla erkek mankende kol omuzda top oldu).
    if arm:
        r_loc = np.interp(x, arm["x"], arm["r"])
        cy_loc = np.interp(x, arm["x"], arm["cy"])
        cz_loc = np.interp(x, arm["x"], arm["cz"])
    else:
        r_loc, cy_loc, cz_loc = np.full(len(x), r_arm), np.full(len(x), cy), np.full(len(x), cz)
    Rw = np.maximum(R, r_loc + gap)
    Y = cy_loc + Rw * np.cos(theta)
    Z = cz_loc + Rw * np.sin(theta)
    return np.column_stack([x, Y, Z]), {"R": R, "R_world_max": float(Rw.max()),
                                        "scale_max": float(Rw.max() / R), "x_start": x_start}


def place_circle_skirt(inst: dict, piece: dict, body: dict, verts: np.ndarray,
                       top_y: float, gap: float) -> tuple[np.ndarray, dict]:
    """Kloş eteği koniye izometrik sar: bel yayının merkezi = koni tepesi; katlama
    (ön orta) +z'de, R yarısı +x'e."""
    pts = inst["pts"] / 1000.0
    edges = {e["id"]: e for e in piece.get("edges") or []}
    poly = np.asarray(piece["seam_line"], dtype=float) / 1000.0
    we = edges.get(f"{piece['name']}.waist")
    if we is not None:
        idx = polyline_indices(len(poly), int(we["from"]), int(we["to"]))
        wpts = poly[idx]
    else:
        wpts = poly[np.argsort(-poly[:, 1])[: max(3, len(poly) // 6)]]
    # Çember merkezi (cebirsel en küçük kareler).
    A_ = np.column_stack([2 * wpts[:, 0], 2 * wpts[:, 1], np.ones(len(wpts))])
    b_ = (wpts ** 2).sum(axis=1)
    sol, *_ = np.linalg.lstsq(A_, b_, rcond=None)
    c = sol[:2]
    rel = pts - c
    rho = np.hypot(rel[:, 0], rel[:, 1])
    # Ön orta yönü: katlama çizgisi boyunca merkezden uzağa (aşağı).
    if inst.get("fold_line"):
        f0, f1 = np.asarray(inst["fold_line"]) / 1000.0
        far = f0 if np.linalg.norm(f0 - c) > np.linalg.norm(f1 - c) else f1
        d0 = far - c
    else:
        d0 = np.array([0.0, -1.0])
    d0 = d0 / max(np.linalg.norm(d0), 1e-12)
    ang0 = math.atan2(d0[1], d0[0])
    psi = np.arctan2(rel[:, 1], rel[:, 0]) - ang0
    psi = (psi + math.pi) % (2 * math.pi) - math.pi
    # Yan yönü: R yarısı (orijinal) psi işaretini +x'e eşle.
    base = inst.get("base_n", len(pts))
    sgn = 1.0 if np.median(psi[:base]) >= 0 else -1.0
    psi = psi * sgn
    span = float(2 * np.abs(psi).max())
    ratio = min(span / (2 * math.pi), 0.97)
    theta = psi / max(ratio, 1e-6) if span < 2 * math.pi else psi
    r3 = rho * ratio
    drop = rho * math.sqrt(max(1e-6, 1 - ratio ** 2))
    rho_w = float(rho.min())
    y = top_y - (drop - rho_w * math.sqrt(max(1e-6, 1 - ratio ** 2)))
    # Kesit: gövdenin bel hizasındaki en/boy oranında ELİPS (aynı çevre) — dairesel
    # koni beli yanlardan keser; elips gövdeyi daha az ölçekle sarar.
    W = _torso_points(verts, body, top_y - 0.06, top_y + 0.02)
    if len(W) >= 10:
        z0 = 0.5 * (float(W[:, 2].max()) + float(W[:, 2].min()))
        e = float(np.clip((W[:, 2].max() - W[:, 2].min()) / max(2 * np.abs(W[:, 0]).max(), 1e-6), 0.5, 1.0))
    else:
        z0, e = 0.0, 1.0
    al, s_unit = _ellipse_arc_table(1.0, e)
    f = (2 * math.pi) / (2 * s_unit[-1])  # birim elips çevresi = 2*yarı-çevre
    a_ax = f * 1.0
    b_ax = f * e
    al_t, s_t = _ellipse_arc_table(a_ax, b_ax)
    s_arc = np.abs(theta) * 1.0  # birim yarıçapta yay
    alpha = np.interp(np.minimum(s_arc, s_t[-1]), s_t, al_t) * np.sign(theta)
    x = r3 * a_ax * np.sin(alpha)
    z = z0 + r3 * b_ax * np.cos(alpha)
    P = np.column_stack([x, y, z])
    prof = body["profile"]
    pushed, kmax = push_out_radial(P, prof, gap * 0.5)
    return P, {"ratio": ratio, "aspect": e, "pushed": pushed, "max_push_ratio": kmax}


def surface_samples(verts: np.ndarray, faces: np.ndarray, n: int = 80_000,
                    seed: int = 0) -> np.ndarray:
    """Alan-ağırlıklı yüzey örnekleri (low-poly mankende vertexler seyrek kalır)."""
    v = np.asarray(verts, dtype=float)
    f = np.asarray(faces, dtype=int)
    a, b, c = v[f[:, 0]], v[f[:, 1]], v[f[:, 2]]
    area = 0.5 * np.linalg.norm(np.cross(b - a, c - a), axis=1)
    if area.sum() <= 0:
        return v
    rng = np.random.default_rng(seed)
    idx = rng.choice(len(f), size=n, p=area / area.sum())
    r1, r2 = rng.random(n), rng.random(n)
    s1 = np.sqrt(r1)
    w0, w1, w2 = 1 - s1, s1 * (1 - r2), s1 * r2
    pts = a[idx] * w0[:, None] + b[idx] * w1[:, None] + c[idx] * w2[:, None]
    return np.concatenate([pts, v])


def body_radial_profile(verts: np.ndarray, body: dict, dy: float = 0.015,
                        sectors: int = 36, faces: np.ndarray | None = None) -> dict:
    """Gövdenin (kollar hariç) yükseklik × açı ızgarasında en büyük yarıçapı.

    Merkez ekseni: x=0, z=z0 (gövde orta). Yüzey örneklerinden kurulur, komşu
    hücrelerle genişletilir (dilate) → güvenli bir dış sınır."""
    src = surface_samples(verts, faces) if faces is not None else verts
    P = _torso_points(src, body, -1.0, 10.0)
    z0 = 0.5 * (float(P[:, 2].max()) + float(P[:, 2].min()))
    y0 = float(P[:, 1].min())
    ny = int((float(P[:, 1].max()) - y0) / dy) + 1
    iy = np.clip(((P[:, 1] - y0) / dy).astype(int), 0, ny - 1)
    th = np.arctan2(P[:, 0], P[:, 2] - z0)
    ia = ((th + math.pi) / (2 * math.pi) * sectors).astype(int) % sectors
    r = np.hypot(P[:, 0], P[:, 2] - z0)
    grid = np.zeros((ny, sectors))
    np.maximum.at(grid, (iy, ia), r)
    # Boş hücreler: önce komşu sektörlerden, hâlâ boşsa satırın en büyüğüyle doldur.
    for _ in range(3):
        empty = grid <= 0
        if not empty.any():
            break
        nb = np.maximum(np.roll(grid, 1, axis=1), np.roll(grid, -1, axis=1))
        grid = np.where(empty, nb, grid)
    rowmax = grid.max(axis=1, keepdims=True)
    grid = np.where(grid > 0, grid, rowmax)
    g = grid.copy()
    for di in (-1, 1):
        g = np.maximum(g, np.roll(grid, di, axis=1))
    g2 = g.copy()
    g2[1:] = np.maximum(g2[1:], g[:-1])
    g2[:-1] = np.maximum(g2[:-1], g[1:])
    return {"grid": g2, "y0": y0, "dy": dy, "sectors": sectors, "z0": z0}


def push_out_radial(P: np.ndarray, prof: dict, gap: float) -> tuple[int, float]:
    """Gövde profilinin (+boşluk) içinde kalan noktaları eksenden radyal dışarı it."""
    g, y0, dy, ns, z0 = prof["grid"], prof["y0"], prof["dy"], prof["sectors"], prof["z0"]
    iy = ((P[:, 1] - y0) / dy).astype(int)
    valid = (iy >= 0) & (iy < len(g))
    th = np.arctan2(P[:, 0], P[:, 2] - z0)
    ia = ((th + math.pi) / (2 * math.pi) * ns).astype(int) % ns
    r = np.hypot(P[:, 0], P[:, 2] - z0)
    req = np.zeros(len(P))
    req[valid] = g[iy[valid], ia[valid]] + gap
    hit = valid & (r < req)
    k = np.ones(len(P))
    k[hit] = req[hit] / np.maximum(r[hit], 1e-6)
    P[hit, 0] *= k[hit]
    P[hit, 2] = z0 + (P[hit, 2] - z0) * k[hit]
    return int(hit.sum()), float(k.max())


def push_out_of_arms(P: np.ndarray, body: dict, gap: float = _ARM_GAP_M) -> int:
    """Kol kapsülüne (boşluk dahil) giren noktaları kol ekseninden radyal dışarı it."""
    arm = body.get("arm")
    if not arm:
        return 0
    cy, cz = arm["cy_mean"], arm["cz_mean"]
    r = arm["r_max"] + gap
    xm = arm["x_min"]
    moved = 0
    ax = np.abs(P[:, 0])
    m = ax > xm - 0.01
    d = P[:, 1:] - np.array([cy, cz])
    dist = np.linalg.norm(d, axis=1)
    hit = np.where(m & (dist < r))[0]
    for i in hit:
        dv = d[i] if dist[i] > 1e-6 else np.array([0.0, -1.0])
        dv = dv / max(np.linalg.norm(dv), 1e-9)
        P[i, 1:] = np.array([cy, cz]) + dv * r
        moved += 1
    return moved


# --- atlas (UV + dinlenme şekli) ------------------------------------------------------
def atlas_layout(insts: list[dict], gap_mm: float = 30.0) -> tuple[list[np.ndarray], float]:
    """Örneklerin 2B noktalarını üst üste binmeyecek şekilde raf dizilimiyle yerleştir.

    L örnekleri x'te aynalanır (gerçek kesilen sol parça). Döner: (örnek başına (N,2) mm,
    normalize ölçeği = atlasın en büyük boyutu mm)."""
    placed = []
    sizes = []
    for inst in insts:
        p = inst["pts"].copy()
        if inst["side"] == "L":
            p[:, 0] = -p[:, 0]
        p -= p.min(axis=0)
        placed.append(p)
        sizes.append(p.max(axis=0))
    total_area = sum(float(s[0] * s[1]) for s in sizes)
    max_w = max(math.sqrt(total_area) * 1.4, max(float(s[0]) for s in sizes))
    x = y = row_h = 0.0
    out = []
    for p, s in zip(placed, sizes):
        if x > 0 and x + s[0] > max_w:
            x = 0.0
            y += row_h + gap_mm
            row_h = 0.0
        out.append(p + [x, y])
        x += float(s[0]) + gap_mm
        row_h = max(row_h, float(s[1]))
    allp = np.concatenate(out)
    extent = float(max(allp[:, 0].max(), allp[:, 1].max()))
    return out, max(extent, 1.0)


# --- ana giriş -------------------------------------------------------------------------
def build_sew_input(pieces_doc: dict, body_verts: np.ndarray, body_faces: np.ndarray,
                    fabric: dict, frames: int = 120, h_mm: float = DEFAULT_EDGE_MM,
                    gap: float = DEFAULT_GAP_M, meta: dict | None = None) -> dict:
    """pieces.json + manken → blender_sew.py girdi sözlüğü (JSON'a yazılabilir)."""
    design = pieces_doc.get("design", "")
    seams = [s for s in pieces_doc.get("seams") or []]
    if not seams:
        raise SewPrepError("Bu kalıpta 3D dikiş bilgisi yok; bu tasarım henüz 3D'de dikilemiyor.")
    seam_edges = {s["a"] for s in seams} | {s["b"] for s in seams}
    pieces = [p for p in pieces_doc["pieces"]
              if any(e["id"] in seam_edges for e in (p.get("edges") or []))]
    skipped = [p.get("label_tr", p["name"]) for p in pieces_doc["pieces"] if p not in pieces]
    warnings: list[str] = []
    if skipped:
        warnings.append("3D dikişte atlanan parçalar (dikiş eşi yok): " + ", ".join(skipped))
    if not pieces:
        raise SewPrepError("Dikilecek parça bulunamadı.")

    fracs, uf = edge_sampling(pieces, seams, h_mm)
    meshes = {p["name"]: build_piece_mesh(p, fracs, uf, h_mm) for p in pieces}
    # Bölme sonrası eş sayıları değişmiş olabilir → tüm parçaları son oranlarla yeniden kur.
    meshes = {p["name"]: build_piece_mesh(p, fracs, uf, h_mm) for p in pieces}
    by_name = {p["name"]: p for p in pieces}

    insts: list[dict] = []
    for p in pieces:
        insts.extend(piece_instances(p, meshes[p["name"]]))

    body = analyze_body(body_verts, body_faces)
    H = body["height"]
    bv = np.asarray(body_verts, dtype=float)
    body["profile"] = body_radial_profile(bv, body, faces=body_faces)

    # Rol bazlı yerleşim.
    roles = {i: _role_of(design, inst["name"]) for i, inst in enumerate(insts)}
    torso_roles = {"torso_front", "torso_back"}
    skirt_roles = {"skirt_front", "skirt_back"}
    placed: dict[int, np.ndarray] = {}
    info: dict[str, Any] = {"roles": {}}
    # Gövde: üst kenar omuz hattının biraz üstünde.
    top_torso = body["shoulder_y"] + 0.02
    top_skirt = body["levels"]["waist"] + 0.03
    for group, top in ((torso_roles, top_torso), (skirt_roles, top_skirt)):
        idxs = [i for i in roles if roles[i] in group]
        if not idxs:
            continue
        hmax = max(float((insts[i]["pts"][:, 1].max() - insts[i]["pts"][:, 1].min()) / 1000.0) for i in idxs)
        # Elips ÇEVRESİ = kıyafetin en geniş çevresi (ön + arka yarı genişlikleri x2)
        # → yan dikişler başlangıçta neredeyse üst üste; gövdeye yaklaşan yerler
        # radyal itmeyle profilin dışına alınır (dinlenme şekli kalıp → ölçü korunur).
        wf = max([_half_width(insts[i], by_name[insts[i]["name"]]) for i in idxs if roles[i].endswith("front")] or [0.0])
        wb = max([_half_width(insts[i], by_name[insts[i]["name"]]) for i in idxs if roles[i].endswith("back")] or [0.0])
        if group is torso_roles:
            # Üst giyim: gövdeyi (omuzlar dahil) boşlukla İÇİNE alan elips. Çevreye
            # eşlenmiş sıkı elips denendi: omuz/koltuk altında itme bölgesi büyüyüp
            # (uzama p95 %50) dikişler kapanmadı → ölçüm günlüğü F2 (r3).
            ell = fit_wrap_ellipse(bv, body, top - hmax, top + 0.02, gap)
        else:
            ell = perimeter_ellipse(bv, body, top - min(hmax, 0.28), top, 2.0 * (wf + wb) * 1.02)
        info[f"ellipse_{'torso' if group is torso_roles else 'skirt'}"] = ell
        for i in idxs:
            inst = insts[i]
            front = roles[i].endswith("front")
            layer = 0.012 if inst["side"] == "L" else 0.0  # üst üste binen yırtmaç payı
            P = place_torso(inst, by_name[inst["name"]], ell, top, front, layer)
            placed[i] = P
    # Kollar: gövde elipsinin dışından başla.
    ell_t = info.get("ellipse_torso")
    # Kol başı tepesi omuz ucuna yakın başlar (gövde panellerinin omuz dikişi ucu);
    # gövde elipsinin dışından başlatmak kolu kalın omuzdan içeri sürükletiyordu.
    x_start = body["shoulder_x"] + 0.03
    if ell_t:
        x_start = min(x_start, ell_t["A"] + 0.02)
    for i in roles:
        if roles[i] == "sleeve":
            P, sinfo = place_sleeve(insts[i], by_name[insts[i]["name"]], body, x_start, 0.03)
            placed[i] = P
            info["roles"][f"{insts[i]['name']}@{insts[i]['side']}"] = sinfo
    for i in roles:
        if roles[i] == "circle_skirt":
            P, cinfo = place_circle_skirt(insts[i], by_name[insts[i]["name"]], body, bv, top_skirt, gap)
            placed[i] = P
            info["roles"][f"{insts[i]['name']}@{insts[i]['side']}"] = cinfo
    # L örnekleri dünya x'inde aynala (katlı tam parça F zaten iki yarılı).
    moved = 0
    for i, inst in enumerate(insts):
        P = placed[i]
        if inst["side"] == "L":
            P = P.copy()
            P[:, 0] = -P[:, 0]
            placed[i] = P
        if roles[i] != "sleeve":
            moved += push_out_of_arms(placed[i], body)
    # Güvenlik ağı: kol dışındaki her parça gövde profilinin (+boşluk) dışında.
    prof = body["profile"]
    rp = 0
    for i in roles:
        if roles[i] != "sleeve":
            n_hit, _k = push_out_radial(placed[i], prof, 0.02)
            rp += n_hit
    info["arm_pushed_vertices"] = moved
    info["radial_pushed_vertices"] = rp

    # Birleştir.
    atlas, extent = atlas_layout(insts)
    V, F, FLAT, UV, piece_ranges = [], [], [], [], []
    inst_edges: dict[str, tuple[int, list[int]]] = {}
    off = 0
    for i, inst in enumerate(insts):
        n = len(inst["pts"])
        faces = np.asarray(inst["faces"], dtype=int)
        if inst["side"] == "L":
            faces = faces[:, [0, 2, 1]]  # aynalama yönü çevirir
        V.append(placed[i])
        F.append(faces + off)
        FLAT.append(np.column_stack([atlas[i] / 1000.0, np.zeros(n)]))
        UV.append(atlas[i] / extent)
        for k, idx in inst["edges"].items():
            inst_edges[k] = (off, idx)
        piece_ranges.append({"name": inst["name"], "side": inst["side"], "start": off, "count": n,
                             "label_tr": by_name[inst["name"]].get("label_tr", inst["name"]),
                             "role": roles[i]})
        off += n
    V = np.concatenate(V)
    F = np.concatenate(F)
    FLAT = np.concatenate(FLAT)
    UV = np.concatenate(UV)

    pairs, w2 = seam_pairs(seams, inst_edges)
    warnings += w2
    springs: list[list[int]] = []
    seam_info = []
    for ka, kb, rev, kind in pairs:
        oa, ia = inst_edges[ka]
        ob, ib = inst_edges[kb]
        if len(ia) != len(ib):
            raise SewPrepError(f"Dikiş nokta sayısı eşleşmedi: {ka} ({len(ia)}) ↔ {kb} ({len(ib)})")
        jb = ib[::-1] if rev else ib
        cnt = 0
        for u, w in zip(ia, jb):
            gu, gw = oa + u, ob + w
            if gu != gw:
                springs.append([gu, gw])
                cnt += 1
        seam_info.append({"a": ka, "b": kb, "reverse": rev, "kind": kind, "pairs": cnt})
    # Tekrarlı yayları ayıkla.
    uniq = sorted({(min(a, b), max(a, b)) for a, b in springs})
    springs = [list(s) for s in uniq]
    seam_vertices = sorted({v for s in springs for v in s})

    return {
        "version": 1,
        "design": design,
        "units": "m",
        "frame": "gltf_y_up",
        "vertices": np.round(V, 6).tolist(),
        "rest": np.round(FLAT, 6).tolist(),
        "uv": np.round(UV, 6).tolist(),
        "faces": F.tolist(),
        "springs": springs,
        "seam_vertices": seam_vertices,
        "pieces": piece_ranges,
        "seams": seam_info,
        "body": {"vertices": np.round(bv, 6).tolist(), "faces": np.asarray(body_faces).tolist()},
        "body_info": {k: body[k] for k in ("height", "levels", "shoulder_x", "shoulder_y", "shoulder_top")},
        "placement": info,
        "fabric": dict(fabric),
        "frames": int(frames),
        "edge_mm": h_mm,
        "warnings": warnings,
    }


# --- manken yükleme (worker tarafı; trimesh) -----------------------------------------
DEFAULT_HEIGHT_M = {"female": 1.65, "male": 1.75}


def load_mannequin(path: str, height_m: float | None = None) -> tuple[np.ndarray, np.ndarray]:
    """GLB'yi yükle → (vertices metre, faces): ayak y=0, XZ merkezli. Birim yükseklikli
    taban mankenler `height_m`'ye ölçeklenir; zaten metre olan (özel) mankenlerde
    height_m=None verilir."""
    import trimesh

    m = trimesh.load(path, force="mesh", process=False)
    v = np.asarray(m.vertices, dtype=float)
    f = np.asarray(m.faces, dtype=int)
    v = v - [0.0, v[:, 1].min(), 0.0]
    v[:, 0] -= (v[:, 0].max() + v[:, 0].min()) / 2
    v[:, 2] -= (v[:, 2].max() + v[:, 2].min()) / 2
    if height_m:
        v *= height_m / max(float(v[:, 1].max()), 1e-6)
    return v, f


def prepare_mannequin(glb_path: str, mannequin_id: str, pattern_body: dict | None) -> tuple[np.ndarray, np.ndarray, dict]:
    """Collider mankeni hazırla (metre, ayak y=0, XZ merkezli).

    - Özel manken (custom-*): GLB zaten gerçek ölçekte → olduğu gibi.
    - Taban manken (birim boylu): kalıbın 5-alan ölçüsü (meta.body) varsa F3 morfuyla
      O ÖLÇÜLERE morflanır (kalıp mankene oturur: etek belde durur, tişört omuzda);
      morf tutmazsa ya da ölçü yoksa yalnız boya ölçeklenir.
    Döner: (vertices, faces, bilgi)."""
    if mannequin_id.startswith("custom-"):
        v, f = load_mannequin(glb_path, None)
        return v, f, {"fit": "custom", "height_m": round(float(v[:, 1].max()), 3)}
    gender = "male" if mannequin_id.startswith("male") else "female"
    body = pattern_body or {}
    try:
        h_cm = float(body.get("height_cm") or 0)
    except (TypeError, ValueError):
        h_cm = 0.0
    if body and h_cm > 0:
        try:
            from pathlib import Path

            from common.body_morph import morph_to_measurements, within_tolerance
            mesh, rep = morph_to_measurements(Path(glb_path), h_cm, float(body["chest_cm"]),
                                              float(body["waist_cm"]), float(body["hip_cm"]))
            ok = within_tolerance(rep["measured"], {"height_cm": h_cm, "chest_cm": body["chest_cm"],
                                                    "waist_cm": body["waist_cm"], "hip_cm": body["hip_cm"]})
            if all(ok.values()):
                v = np.asarray(mesh.vertices, dtype=float)
                v = v - [0.0, v[:, 1].min(), 0.0]
                v[:, 0] -= (v[:, 0].max() + v[:, 0].min()) / 2
                v[:, 2] -= (v[:, 2].max() + v[:, 2].min()) / 2
                return v, np.asarray(mesh.faces, dtype=int), {
                    "fit": "morphed", "height_m": round(h_cm / 100.0, 3), "measured": rep["measured"]}
        except Exception:  # noqa: BLE001 — morf olmazsa ölçeklemeye düş
            pass
        v, f = load_mannequin(glb_path, h_cm / 100.0)
        return v, f, {"fit": "scaled", "height_m": round(h_cm / 100.0, 3)}
    h = DEFAULT_HEIGHT_M.get(gender, 1.70) if mannequin_id in ("female-a", "male-a") else 1.70
    v, f = load_mannequin(glb_path, h)
    return v, f, {"fit": "scaled", "height_m": h}
