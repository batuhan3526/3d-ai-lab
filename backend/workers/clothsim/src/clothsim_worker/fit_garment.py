"""Kıyafeti mankene geometrik olarak oturt (Blender'sız, CPU).

Designer'daki manken katmanı kıyafete ölçek+öteleme ile hizalanır (customizations
.mannequin.transform: dünya = yerel * scale + position). Üretilen kıyafetler (TRELLIS vb.)
çoğu zaman gerçeğinden incedir → göğüs/kalça kumaşın dışına taşar. Bu modül:

1. Mankeni kıyafet çerçevesine taşır, yüzeyinden yoğun örnek + dış normal alır.
2. Kıyafet köşelerinin işaretli mesafesini ölçer (k-en-yakın örneğin ortalaması).
3. İçeride / `margin`'den yakın köşeleri yüzeyin `margin` dışına iter; itme alanını mesh
   komşuluğuyla yumuşatır (kumaş tek noktada sivrilmesin, göğsün üstünden geçsin) ve
   birkaç tur tekrarlar.

UV dikişlerinde aynı konumda birden çok köşe olur → konuma göre birleştirilip aynı
öteleme uygulanır (doku yırtılmaz). Malzeme/doku dokunulmadan korunur.
"""
from __future__ import annotations

from typing import Any

import numpy as np


def body_samples(verts: np.ndarray, faces: np.ndarray, n: int = 150_000, seed: int = 0) -> tuple[np.ndarray, np.ndarray]:
    """Alan-ağırlıklı yüzey örnekleri + yüz normalleri."""
    v = np.asarray(verts, float)
    f = np.asarray(faces, int)
    a, b, c = v[f[:, 0]], v[f[:, 1]], v[f[:, 2]]
    cr = np.cross(b - a, c - a)
    area = 0.5 * np.linalg.norm(cr, axis=1)
    nrm = cr / np.maximum(2 * area[:, None], 1e-12)
    rng = np.random.default_rng(seed)
    idx = rng.choice(len(f), size=n, p=area / area.sum())
    r1, r2 = rng.random(n), rng.random(n)
    s1 = np.sqrt(r1)
    pts = a[idx] * (1 - s1)[:, None] + b[idx] * (s1 * (1 - r2))[:, None] + c[idx] * (s1 * r2)[:, None]
    return pts, nrm[idx]


def _weld(v: np.ndarray, tol: float = 1e-6) -> tuple[np.ndarray, np.ndarray]:
    key = np.round(v / tol).astype(np.int64)
    uniq, inv = np.unique(key, axis=0, return_inverse=True)
    inv = inv.reshape(-1)
    welded = np.zeros((len(uniq), 3))
    np.add.at(welded, inv, v)
    cnt = np.bincount(inv, minlength=len(uniq))[:, None]
    return welded / cnt, inv


def _adjacency(faces: np.ndarray, n: int):
    from scipy.sparse import coo_matrix
    e = np.concatenate([faces[:, [0, 1]], faces[:, [1, 2]], faces[:, [2, 0]]])
    e = np.concatenate([e, e[:, ::-1]])
    A = coo_matrix((np.ones(len(e)), (e[:, 0], e[:, 1])), shape=(n, n)).tocsr()
    A.data[:] = 1.0
    return A, np.maximum(np.asarray(A.sum(axis=1)).ravel(), 1)


def fit_vertices(gv: np.ndarray, gf: np.ndarray, bpts: np.ndarray, bnrm: np.ndarray,
                 margin: float = 0.01, rounds: int = 5, radius: float = 0.16,
                 deep: float = 0.04, reach: float = 0.25, smooth_iters: int = 24,
                 frozen: np.ndarray | None = None) -> tuple[np.ndarray, dict[str, Any]]:
    """Kıyafet köşelerini (gv, gf) beden örneklerinin (bpts, bnrm) `margin` dışına it.

    - Bölgesel itme: gereken itme `radius` içindeki TÜM köşelere koni düşüşüyle yayılır
      (komşunun en büyüğü). Üretilen kıyafetler çift kabuklu (dış + iç yüzey) olduğundan
      tek tek itmek iç yüzeyi dışın önüne geçirirdi; aynı bölge aynı miktarda kayınca
      katman sırası korunur ve kumaş göğsün üstünden yumuşakça geçer.
    - `deep`: bedenin bu kadar içindeki parçalar kumaş taşması değil (ör. görselden
      gelen manken boynu) → dokunulmaz.
    - `reach`: bedenden bu kadar uzak köşeler ilgisiz.
    Döner: (yeni gv, rapor)."""
    from scipy.spatial import cKDTree
    W, inv = _weld(np.asarray(gv, float))
    # frozen: itilmeyecek köşeler (ör. boyun üstündeki gömülü parçalar); kaynak köşe
    # dizisinden birleştirilmiş diziye taşınır (herhangi bir kopyası donuksa donuk).
    fz = np.zeros(len(W), dtype=bool)
    if frozen is not None:
        np.logical_or.at(fz, inv, np.asarray(frozen, dtype=bool))
    tree = cKDTree(bpts)
    k = 48  # geniş, mesafe-ağırlıklı komşuluk → düşük poligonlu mankenin köşeleri yumuşar

    def signed(P: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        dist, nb = tree.query(P, k=k)
        w = np.exp(-(dist / 0.025) ** 2) + 1e-12  # ~2.5 cm Gauss çekirdeği
        w /= w.sum(axis=1, keepdims=True)
        p = (bpts[nb] * w[:, :, None]).sum(axis=1)
        n = (bnrm[nb] * w[:, :, None]).sum(axis=1)
        n /= np.maximum(np.linalg.norm(n, axis=1, keepdims=True), 1e-12)
        return ((P - p) * n).sum(axis=1), n, dist[:, 0]

    def poking(d: np.ndarray, near: np.ndarray) -> np.ndarray:
        return (d < 0) & (d > -deep) & (near < reach)

    d0, _, near0 = signed(W)
    inside0 = int(poking(d0, near0).sum())
    P = W.copy()
    for _ in range(rounds):
        d, n, near = signed(P)
        req = np.where((d < margin) & (d > -deep) & (near < reach) & ~fz, margin - d, 0.0)
        src = np.nonzero(req > 1e-6)[0]
        if not len(src):
            break
        gtree = cKDTree(P)
        mag = np.zeros(len(P))
        for j, nbrs in zip(src, gtree.query_ball_point(P[src], radius)):
            nbrs = np.asarray(nbrs, dtype=int)
            fall = 1.0 - np.linalg.norm(P[nbrs] - P[j], axis=1) / radius
            np.maximum.at(mag, nbrs, req[j] * fall)
        mag[d <= -deep] = 0.0
        mag[fz] = 0.0
        # Beden kumaşı aşağı itmez (kalça/kalça arkası eteği aşağı çekip esnetiyordu):
        # itme yönünün aşağı bileşeni atılır, yatay kısım yeniden ölçeklenir.
        nd = n.copy()
        nd[:, 1] = np.maximum(nd[:, 1], 0.0)
        nd /= np.maximum(np.linalg.norm(nd, axis=1, keepdims=True), 1e-9)
        P = P + mag[:, None] * nd
    # Toplam ötelemeyi mesh komşuluğunda yumuşat (köşeli tümsekleri gider); itilen
    # bölgede yumuşatma ötelemeyi azaltmasın diye büyüklük yerel en büyüğe sabitlenir.
    disp = P - W
    if smooth_iters:
        F = inv[np.asarray(gf, int)]
        A, deg = _adjacency(F, len(W))
        need = np.linalg.norm(disp, axis=1)
        for _ in range(smooth_iters):
            disp = 0.5 * disp + 0.5 * (A @ disp) / deg[:, None]
        cur = np.linalg.norm(disp, axis=1)
        scale = np.where(cur > 1e-9, np.maximum(need, cur) / np.maximum(cur, 1e-9), 0.0)
        disp = disp * scale[:, None]
        disp[fz] = 0.0
    P = W + disp
    d1, _, near1 = signed(P)
    inside1 = int(poking(d1, near1).sum())
    moved = np.linalg.norm(P - W, axis=1)
    return P[inv], {"vertices": int(len(W)), "inside_before": inside0, "inside_after": inside1,
                    "moved": int((moved > 1e-5).sum()), "max_move": float(moved.max()),
                    "margin": margin}


def _clusters_1d(x: np.ndarray, gap: float) -> list[np.ndarray]:
    """Sıralı 1B değerleri `gap`'ten büyük boşluklarda kümelere böl → indeks dizileri."""
    order = np.argsort(x)
    xs = x[order]
    cuts = np.nonzero(np.diff(xs) > gap)[0] + 1
    return [order[c] for c in np.split(np.arange(len(xs)), cuts)]


def align_sleeves(gv: np.ndarray, arm_pts: np.ndarray, *, bin_h: float = 0.02,
                  gap: float = 0.012, max_shift: float = 0.04,
                  ramp: float = 0.10) -> tuple[np.ndarray, dict[str, Any]]:
    """Kıyafet kollarını mankenin kollarının üzerine kaydır ("dört kol" görüntüsü).

    Her yükseklik diliminde (her yan ayrı): kol ekseni = manken kol noktalarının (x, z)
    ortalaması; kolluk = kıyafetin o dilimdeki EN DIŞ x kümesi (gövde paneliyle arasında
    boşluk olan). Öteleme = kol merkezi − kolluk merkezi; yükseklik boyunca yumuşatılır,
    omuzdan aşağı `ramp` boyunca 0→1 artar (omuz dikişi yerinde kalır). Gövde paneli
    (kolluk sınırının 3 cm+ içi) ötelenmez."""
    v = np.asarray(gv, float).copy()
    rep: dict[str, Any] = {}
    for side in (1, -1):
        A = arm_pts[np.sign(arm_pts[:, 0]) == side]
        if len(A) < 20:
            continue
        top = float(np.quantile(A[:, 1], 0.98))
        ys = np.arange(A[:, 1].min(), top, bin_h)
        rows = []
        for yb in ys:
            a = A[np.abs(A[:, 1] - yb) < bin_h * 0.6]
            g_idx = np.nonzero((np.sign(v[:, 0]) == side) & (np.abs(v[:, 1] - yb) < bin_h * 0.6))[0]
            if len(a) < 3 or len(g_idx) < 6:
                continue
            ax = np.abs(v[g_idx, 0])
            cl = _clusters_1d(ax, gap)
            if len(cl) < 2:
                continue  # kolluk gövdeden ayrışmıyor (bitişik) → bu dilimde dokunma
            sl = g_idx[cl[-1]]
            if np.ptp(np.abs(v[sl, 0])) > 0.25:
                continue
            arm_c = np.array([np.abs(a[:, 0]).mean(), a[:, 2].mean()])
            sl_c = np.array([np.abs(v[sl, 0]).mean(), v[sl, 2].mean()])
            rows.append((yb, *(arm_c - sl_c), float(np.abs(v[sl, 0]).min())))
        if len(rows) < 3:
            rep[f"side{side:+d}"] = "kolluk bulunamadı"
            continue
        R = np.array(rows)
        # Aykırı dilimleri bastır: 5'li kayan medyan.
        for k in (1, 2):
            R[:, k] = np.array([np.median(R[max(0, i - 2):i + 3, k]) for i in range(len(R))])
        off = R[:, 1:3]
        norm = np.linalg.norm(off, axis=1, keepdims=True)
        off = off * np.minimum(1.0, max_shift / np.maximum(norm, 1e-9))
        sel = np.nonzero(np.sign(v[:, 0]) == side)[0]
        y = v[sel, 1]
        dx = np.interp(y, R[:, 0], off[:, 0])
        dz = np.interp(y, R[:, 0], off[:, 1])
        cut = np.interp(y, R[:, 0], R[:, 3])
        w = np.clip((np.abs(v[sel, 0]) - (cut - 0.03)) / 0.03, 0, 1)
        w *= np.clip((top - y) / ramp, 0, 1)
        v[sel, 0] += side * dx * w
        v[sel, 2] += dz * w
        rep[f"side{side:+d}"] = {"slices": len(R), "mean_shift": round(float(np.linalg.norm(off, axis=1).mean()), 4),
                                 "max_shift": round(float(np.linalg.norm(off, axis=1).max()), 4)}
    return v, rep


def arm_mask(mannequin_path: str, verts: np.ndarray) -> np.ndarray | None:
    """Kol köşeleri. Kollar-aşağı varyantlar (`*-down.glb`) T-poz tabanından (`*-a.glb`)
    köşe sırası korunarak üretildi → kollar orada kesin ayrışır (|x| > omuz)."""
    import os

    import trimesh
    base = mannequin_path.replace("-down.glb", "-a.glb")
    src = verts
    if base != mannequin_path and os.path.exists(base):
        b = np.asarray(trimesh.load(base, force="mesh", process=False).vertices, float)
        if len(b) == len(verts):
            src = b
    src = src - [0.0, src[:, 1].min(), 0.0]
    H = float(np.ptp(src[:, 1]))
    torso = src[(src[:, 1] > 0.70 * H) & (src[:, 1] < 0.74 * H)]  # göğüs bandı
    if len(torso) < 10:
        return None
    half = float(np.quantile(np.abs(torso[:, 0]), 0.5))
    mask = (np.abs(src[:, 0]) > 1.6 * half) & (src[:, 1] > 0.55 * H)
    return mask if mask.sum() > 20 else None


def fit_glb(garment_path: str, mannequin_path: str, transform: dict, out_path: str,
            margin: float = 0.01) -> dict[str, Any]:
    """GLB kıyafeti GLB mankene (Designer transform'uyla) oturt → out_path (GLB).
    Önce kolluklar kolların üzerine hizalanır, sonra beden içinde kalan kumaş dışarı itilir."""
    import trimesh

    man = trimesh.load(mannequin_path, force="mesh", process=False)
    s = float(transform.get("scale", 1.0))
    pos = np.asarray(transform.get("position", [0, 0, 0]), float)
    if any(abs(r) > 1e-6 for r in transform.get("rotation", [0, 0, 0])):
        raise ValueError("Döndürülmüş manken henüz desteklenmiyor (rotation 0 olmalı).")
    bv = np.asarray(man.vertices, float) * s + pos
    am = arm_mask(mannequin_path, np.asarray(man.vertices, float))
    arm_pts = bv[am] if am is not None else None
    # Manken mesh'leri sargı-tutarlı + pozitif hacimli → yüz normalleri dışa bakar.
    bpts, bnrm = body_samples(bv, np.asarray(man.faces))

    scene = trimesh.load(garment_path, force="scene")
    report: dict[str, Any] = {"geometries": {}}
    for name, geom in scene.geometry.items():
        if not hasattr(geom, "faces") or len(geom.faces) == 0:
            continue
        # Sahne düğüm dönüşümü varsa dünya çerçevesinde çalış, sonra geri çevir.
        node = next((nd for nd in scene.graph.nodes_geometry if scene.graph[nd][1] == name), None)
        T = scene.graph[node][0] if node is not None else np.eye(4)
        Ti = np.linalg.inv(T)
        wv = trimesh.transform_points(np.asarray(geom.vertices, float), T)
        sleeve_rep: dict[str, Any] = {}
        if arm_pts is not None:
            wv, sleeve_rep = align_sleeves(wv, arm_pts)
        new, rep = fit_vertices(wv, np.asarray(geom.faces), bpts, bnrm, margin=margin)
        geom.vertices = trimesh.transform_points(new, Ti)
        rep["sleeves"] = sleeve_rep
        report["geometries"][name] = rep
    scene.export(out_path)
    return report
