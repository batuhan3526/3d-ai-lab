"""Kıyafeti mankene GİYDİR — her tasarımda otomatik (Blender'sız, CPU).

Elle ayar gerektirmeden çalışır; kadın/erkek, ölçüden üretilmiş özel mankenler, farklı
boy/genişlik ve kıyafet türleri için:

1. Kıyafet analizi (y-yukarı, ön +z): her yükseklik diliminde gövde / kolluk ayrımı
   (yanlarda boşlukla ayrışan en dış x kümesi = kolluk). Kolluk eksenleri (sağ/sol),
   gövde yarı-genişliği, omuz hizası.
2. Otomatik hiza: üst giyimde göğüs genişliği + omuz hizası, alt giyimde bel kenarı +
   bel genişliği mankenin aynı noktalarıyla eşlenir → ölçek + konum (dönme yok).
3. Kol pozu: mankenin T-poz tabanından kollar, omuz ekleminde kıyafetin kolluk
   eksenine döndürülür (kolsuz/alt giyimde doğal "kollar aşağı" pozu). Omuz bölgesinde
   yumuşak geçiş; baş/gövde yerinde kalır.
4. Oturtma: kolluk ince hizası + beden içinde kalan kumaşı dışarı itme (fit_garment).

Çıktılar: oturtulmuş kıyafet GLB'si + projeye özel pozlu manken GLB'si (mankenin kendi
yerel çerçevesinde; Designer aynı transform'la gösterir) + hiza bilgisi.
"""
from __future__ import annotations

import math
import os
from typing import Any

import numpy as np

from clothsim_worker.fit_garment import body_samples, fit_vertices

TOPS = {"tshirt", "shirt"}
BOTTOMS = {"pants", "skirt"}
# Kıyafet bedenden bol durur: göğüs genişliği ≈ beden × EASE. Kapüşonlu/sweat/tişört
# gibi gündelik üstlerde tipik bolluk ~%20 (88 cm göğüs → ~106 cm kıyafet).
EASE_TOP = 1.20
EASE_WAIST = 1.04
# Kıyafet boyu / manken boyu üst sınırı (check_garment_span): üstünde "kıyafet değil".
# 2026-10-18 ölçümü (77 üst giyim projesi): gerçek kıyafetler 0.33–0.71 (bol kesim tişört),
# tam figür / vazo üretimleri 0.90–1.09. 2026-10-23: maxi elbise (omuz→bilek) ~0.80.
SPAN_LIMIT_TOP = 0.87
SPAN_LIMIT_BOTTOM = 0.85
# Kolsuz kıyafette doğal duruş: dikeyden 12° dışa, 10° öne (radyan).
DEFAULT_ARM = (math.radians(12), math.radians(10))


# --- manken -----------------------------------------------------------------------
def tpose_base(mannequin_path: str) -> str:
    """Kol pozu T-poz tabanından hesaplanır: `*-down.glb` → `*-a.glb`; diğerleri kendisi."""
    base = mannequin_path.replace("-down.glb", "-a.glb")
    return base if base != mannequin_path and os.path.exists(base) else mannequin_path


def body_landmarks(v: np.ndarray, faces: np.ndarray) -> dict[str, Any]:
    """T-poz manken (yerel çerçeve) için seviye ve ölçüler."""
    from clothsim_worker.sew_prep import analyze_body
    y0 = float(v[:, 1].min())
    b = analyze_body(v - [0.0, y0, 0.0], faces)
    H = b["height"]
    lv = {k: y + y0 for k, y in b["levels"].items()}

    def torso_slice(y: float) -> np.ndarray:
        s = v[(np.abs(v[:, 1] - y) < 0.012 * H) & (np.abs(v[:, 0]) < b["shoulder_x"] * 1.25)]
        return s if len(s) >= 6 else v[np.abs(v[:, 1] - y) < 0.02 * H]

    chest = torso_slice(lv["chest"])
    waist = torso_slice(lv["waist"])
    hip = v[np.abs(v[:, 1] - lv["hip"]) < 0.012 * H]
    arm = b.get("arm") or {}
    return {
        "H": H, "y0": y0, "levels": lv, "shoulder_y": b["shoulder_y"] + y0,
        "shoulder_x": b["shoulder_x"],
        "chest_half": float(np.abs(chest[:, 0]).max()), "chest_z": 0.5 * float(chest[:, 2].min() + chest[:, 2].max()),
        "waist_half": float(np.abs(waist[:, 0]).max()), "waist_z": 0.5 * float(waist[:, 2].min() + waist[:, 2].max()),
        "hip_half": float(np.abs(hip[:, 0]).max()) if len(hip) else float(np.abs(waist[:, 0]).max()),
        "arm_cy": (arm.get("cy_mean", b["levels"]["armpit"] + 0.02 * H)) + y0,
        "arm_cz": arm.get("cz_mean", 0.0),
    }


def arm_vertices(v: np.ndarray, lm: dict) -> np.ndarray:
    """T-pozda kol köşeleri: omuz genişliğinin dışında, koltuk altı üstünde."""
    return (np.abs(v[:, 0]) > lm["shoulder_x"] * 1.25) & (v[:, 1] > lm["levels"]["armpit"] - 0.06 * lm["H"])


def _rodrigues(P: np.ndarray, axis: np.ndarray, ang: np.ndarray) -> np.ndarray:
    k = axis / max(np.linalg.norm(axis), 1e-12)
    c, s = np.cos(ang)[:, None], np.sin(ang)[:, None]
    return P * c + np.cross(k, P) * s + np.outer(P @ k, k) * (1 - c)


def pose_arms(v: np.ndarray, lm: dict, dirs: dict[int, np.ndarray]) -> np.ndarray:
    """T-poz kollarını omuz ekleminde `dirs[side]` (birim, omuzdan bileğe) yönüne döndür.
    Ağırlık: omuzdan dışa doğru 0→1 (yumuşak), baş ve gövde yanı korunur."""
    H = lm["H"]
    out = v.copy()
    am = arm_vertices(v, lm)
    for side, d in dirs.items():
        sm = am & (np.sign(v[:, 0]) == side)
        if sm.sum() < 10:
            continue
        a0 = v[sm] - v[sm].mean(axis=0)
        u = np.linalg.svd(a0, full_matrices=False)[2][0]
        u = u if u[0] * side > 0 else -u            # T-poz kol yönü (dışa)
        d = d / max(np.linalg.norm(d), 1e-12)
        axis = np.cross(u, d)
        theta = math.acos(float(np.clip(u @ d, -1, 1)))
        if np.linalg.norm(axis) < 1e-9 or theta < 1e-4:
            continue
        piv = np.array([side * lm["shoulder_x"] * 0.80, lm["arm_cy"], lm["arm_cz"]])
        x = v[:, 0] * side
        w = np.clip((x - (piv[0] * side - 0.02 * H)) / (0.08 * H), 0, 1)
        w *= np.clip((v[:, 1] - (piv[1] - 0.10 * H)) / (0.05 * H), 0, 1)   # gövde yanı/kalça
        w *= np.clip(((piv[1] + 0.07 * H) - v[:, 1]) / (0.03 * H), 0, 1)   # baş/boyun
        w = w * w * (3 - 2 * w)
        m = (x > piv[0] * side - 0.02 * H) & (w > 0)
        out[m] = piv + _rodrigues(v[m] - piv, axis, w[m] * theta)
    return out


def default_arm_dir(side: int) -> np.ndarray:
    out, fwd = DEFAULT_ARM
    return np.array([side * math.sin(out), -math.cos(out) * math.cos(fwd), math.cos(out) * math.sin(fwd)])


# --- kıyafet ----------------------------------------------------------------------
FACING_RATIO = 1.3      # derinlik / genişlik bunun üstünde → önü yana bakıyor
SLAB_FLAT = 0.03        # bileşen yüksekliği / kıyafet boyu bunun altında ve …
SLAB_WIDE = 0.5         # … genişliği kıyafet genişliğinin bu katından fazlaysa: zemin plakası
SLAB_AREA = 0.12        # tek bir ince banttaki yatay yüz alanı / toplam: kaynaşmış plaka


def facing_fix(v: np.ndarray) -> np.ndarray:
    """Önü ±x'e bakan kıyafet (yandan üretilmiş/çevrilmiş) için y ekseninde 90° dönme;
    kıyafetler (üst, alt, elbise) önden bakınca derinliğinden geniştir."""
    ext = np.ptp(v, axis=0)
    if ext[2] > FACING_RATIO * ext[0]:
        return np.array([[0.0, 0.0, -1.0], [0.0, 1.0, 0.0], [1.0, 0.0, 0.0]])
    return np.eye(3)


POLE_W = 0.2            # alt uçta gövde yarı-genişliğinin %90 diliminin bu katından ince: direk


def pole_cut(prof: dict) -> float | None:
    """Alttan ince sap (görseldeki manken ayağı/direği) varsa kesim yüksekliği: alttan
    yukarı, yarı-genişliği (uzun direkte de bozulmasın diye) %90 diliminin POLE_W katını
    geçen ilk kesitin hemen altı."""
    R = prof["rows"]
    if len(R) < 10:
        return None
    thick = np.nonzero(R[:, 1] >= POLE_W * float(np.quantile(R[:, 1], 0.9)))[0]
    if not len(thick) or thick[0] < 2:
        return None
    return float(R[thick[0], 0]) - 0.012 * prof["H"]


def analysis_faces(v: np.ndarray, f: np.ndarray) -> np.ndarray:
    """Analizde kullanılacak yüzler: ince + geniş yatay bağlı bileşenler (zemin/ürün
    plakası) hariç. Hiçbir şey kalmazsa hepsi."""
    from scipy.sparse import coo_matrix
    from scipy.sparse.csgraph import connected_components
    # Üretilen mesh'ler sık sık kaynaksız üçgen yığınıdır → bağlılık konumla kurulur.
    from clothsim_worker.fit_garment import _weld
    W, inv = _weld(np.asarray(v, float), tol=1e-5)
    f = inv[np.asarray(f, int)]
    v = W
    n = len(v)
    e = np.concatenate([f[:, [0, 1]], f[:, [1, 2]]])
    A = coo_matrix((np.ones(len(e)), (e[:, 0], e[:, 1])), shape=(n, n))
    ncomp, lab = connected_components(A, directed=False)
    if ncomp == 1:
        return np.ones(len(f), bool)
    H = float(np.ptp(v[:, 1]))
    W = float(np.ptp(v[:, 0]))
    order = np.argsort(lab, kind="stable")
    bounds = np.searchsorted(lab[order], np.arange(ncomp + 1))
    bad = np.zeros(ncomp, bool)
    for c in range(ncomp):
        idx = order[bounds[c]:bounds[c + 1]]
        if len(idx) < 4:
            continue
        p = v[idx]
        if np.ptp(p[:, 1]) < SLAB_FLAT * H and max(np.ptp(p[:, 0]), np.ptp(p[:, 2])) > SLAB_WIDE * W:
            bad[c] = True
    keep = ~bad[lab[f[:, 0]]] & ~_slab_band(v, f)
    return keep if keep.any() else np.ones(len(f), bool)


def _slab_band(v: np.ndarray, f: np.ndarray) -> np.ndarray:
    """Kıyafete kaynaşmış plaka: alanın ≥ SLAB_AREA'sını tutan, ince bir y bandındaki
    YATAY yüzler. O banttaki tüm yüzler (plakanın yanları dahil) işaretlenir."""
    a, b, c = v[f[:, 0]], v[f[:, 1]], v[f[:, 2]]
    cr = np.cross(b - a, c - a)
    area = 0.5 * np.linalg.norm(cr, axis=1)
    ny = np.abs(cr[:, 1]) / np.maximum(2 * area, 1e-12)
    H = float(np.ptp(v[:, 1]))
    y0 = float(v[:, 1].min())
    yc = (a[:, 1] + b[:, 1] + c[:, 1]) / 3
    bins = np.clip(((yc - y0) / (0.01 * H)).astype(int), 0, 100)
    horiz = np.bincount(bins, weights=area * (ny > 0.95), minlength=101)
    big = np.nonzero(horiz > SLAB_AREA * area.sum())[0]
    out = np.zeros(len(f), bool)
    if not len(big) or big.max() - big.min() > 20:
        return out
    lo = y0 + (big.min() - 1) * 0.01 * H
    hi = y0 + (big.max() + 2) * 0.01 * H
    ys = np.stack([a[:, 1], b[:, 1], c[:, 1]], axis=1)
    return np.all((ys >= lo) & (ys <= hi), axis=1)


def _silhouette(v: np.ndarray, faces: np.ndarray, res: int = 256):
    """Önden (x-y) silüet maskesi; satır 0 = en alt. Küçük delikler kapatılır."""
    from PIL import Image, ImageDraw
    from scipy import ndimage
    H = float(np.ptp(v[:, 1]))
    c = H / res
    x0, y0 = float(v[:, 0].min()), float(v[:, 1].min())
    W = int(np.ptp(v[:, 0]) / c) + 4
    Hh = res + 4
    px = (v[:, 0] - x0) / c + 1.5
    py = (v[:, 1] - y0) / c + 1.5
    img = Image.new("L", (W, Hh), 0)
    draw = ImageDraw.Draw(img)
    for f in np.asarray(faces, int):
        draw.polygon([(px[f[0]], py[f[0]]), (px[f[1]], py[f[1]]), (px[f[2]], py[f[2]])], fill=255)
    M = ndimage.binary_closing(np.asarray(img) > 0, iterations=2)
    return M, c, x0, y0, px, py


def _runs(row: np.ndarray) -> list[tuple[int, int]]:
    d = np.diff(np.concatenate([[0], row.astype(np.int8), [0]]))
    return list(zip(np.nonzero(d == 1)[0], np.nonzero(d == -1)[0] - 1))


def garment_profile(gv: np.ndarray, faces: np.ndarray | None = None, bin_frac: float = 0.02,
                    cell_frac: float = 0.006, dil: int = 2) -> dict[str, Any]:
    """Yatay kesitlerle gövde / kolluk ayrımı.

    Her yükseklikte kesit noktaları x–z düzleminde ızgaraya basılıp bağlı bileşenlere
    ayrılır: ortadaki (x≈0) bileşen gövde, yanlardaki ayrık bileşenler kolluk. Önden
    bakınca gövdeye binen sarkık kollar da kesitte ayrıdır. Kolluk merkezleri kolun
    eksenini verir (uzun kolda dikey, kısa kolda çapraz). Koltuk altı = kolluğun
    gövdeden ayrık olduğu en üst kesit."""
    from scipy import ndimage
    v = np.asarray(gv, float)
    H = float(np.ptp(v[:, 1]))
    bh = bin_frac * H
    cell = cell_frac * H
    ys = np.arange(v[:, 1].min() + bh / 2, v[:, 1].max(), bh)
    rows, cents = [], {1: [], -1: []}
    for yb in ys:
        sl = v[np.abs(v[:, 1] - yb) < bh * 0.6]
        if len(sl) < 8:
            continue
        x0, z0 = sl[:, 0].min(), sl[:, 2].min()
        ix = ((sl[:, 0] - x0) / cell).astype(int) + 1
        iz = ((sl[:, 2] - z0) / cell).astype(int) + 1
        G = np.zeros((ix.max() + 2, iz.max() + 2), bool)
        G[ix, iz] = True
        G = ndimage.binary_dilation(G, iterations=dil)
        lab, n = ndimage.label(G)
        pl = lab[ix, iz]
        cx = (0.0 - x0) / cell + 1
        # Gövde: x=0'a en yakın (ve büyük) bileşen.
        best, torso = None, 1
        for k in range(1, n + 1):
            pk = sl[pl == k]
            if not len(pk):
                continue
            score = float(np.min(np.abs(pk[:, 0]))) - 0.001 * len(pk)
            if best is None or score < best:
                best, torso = score, k
        tp = sl[pl == torso]
        halves, flags = [], 0
        for side in (1, -1):
            ts = tp[np.sign(tp[:, 0]) == side]
            half = float(np.abs(ts[:, 0]).max()) if len(ts) else 0.0
            halves.append(half)
            cands = [k for k in range(1, n + 1) if k != torso]
            best_k, best_n = None, 0
            for k in cands:
                pk = sl[pl == k]
                if len(pk) >= 4 and np.sign(pk[:, 0].mean()) == side and np.abs(pk[:, 0]).mean() > 0.5 * half \
                        and np.ptp(pk[:, 0]) < 0.25 * H and len(pk) > best_n:
                    best_k, best_n = k, len(pk)
            if best_k is not None:
                pk = sl[pl == best_k]
                cents[side].append((float(pk[:, 0].mean()), float(yb), float(pk[:, 2].mean()), half))
                flags += 1
        rows.append((float(yb), float(np.mean(halves)), 0.5 * float(tp[:, 2].min() + tp[:, 2].max()), flags))
    R = np.array(rows) if rows else np.zeros((0, 4))
    armpit, cut, srows = {}, {}, {}
    for side, C in cents.items():
        if len(C) < 3:
            continue
        C = np.array(C)
        # Koltuk altı: üst yarıdaki en üst ayrık kesit (etek/manşet hizasındaki ayrışma sayılmaz).
        upper = C[C[:, 1] > v[:, 1].min() + 0.35 * H]
        top = upper if len(upper) else C
        armpit[side] = float(top[:, 1].max())
        cut[side] = float(np.median(top[np.argsort(-top[:, 1])[:3], 3]))
        srows[side] = np.column_stack([C[:, 1], C[:, 0], C[:, 2], C[:, 3]])  # (y, x, z, gövde kenarı)
    return {"rows": R, "H": H, "top": float(v[:, 1].max()), "bottom": float(v[:, 1].min()),
            "armpit": float(np.mean(list(armpit.values()))) if armpit else None,
            "armpit_side": armpit, "cut": cut, "sleeve_rows": srows,
            "sleeves": {k: True for k in srows}}


def sleeve_dirs(prof: dict, gv: np.ndarray | None = None) -> dict[int, np.ndarray]:
    """Kolluk kesit merkezlerinden (3B PCA) omuzdan bileğe birim yön; kolluk yoksa ya da
    çok kısaysa doğal varsayılan. Dışa/aşağı yönlendirilir, öne eğim ±30° ile sınırlı."""
    out = {}
    H = prof["H"]
    for side in (1, -1):
        S = prof["sleeve_rows"].get(side)
        if S is None or len(S) < 3:
            out[side] = default_arm_dir(side)
            continue
        P = np.column_stack([S[:, 1], S[:, 0], S[:, 2]])          # (x, y, z)
        if np.linalg.norm(np.ptp(P, axis=0)) < 0.06 * H:
            out[side] = default_arm_dir(side)
            continue
        u = np.linalg.svd(P - P.mean(axis=0), full_matrices=False)[2][0]
        if u @ np.array([side, -1.0, 0.0]) < 0:
            u = -u
        if u[0] * side < 0:          # içe bakan eksen gürültüdür → dikeye çek
            u[0] = 0.0
        u[2] = float(np.clip(u[2], -0.5 * abs(u[1]), 0.6 * abs(u[1]) + 0.3 * abs(u[0])))
        out[side] = u / np.linalg.norm(u)
    return out


def garment_occupancy(gv: np.ndarray, faces: np.ndarray, cell: float) -> dict[str, Any]:
    """Kıyafet yüzeyinin 3B doluluk ızgarası (alan-ağırlıklı yüzey örnekleri, 1 hücre şişirilmiş)."""
    from scipy import ndimage
    pts, _ = body_samples(gv, faces, n=200_000, seed=1)
    lo = pts.min(axis=0) - 2 * cell
    idx = ((pts - lo) / cell).astype(int)
    G = np.zeros(idx.max(axis=0) + 3, bool)
    G[idx[:, 0], idx[:, 1], idx[:, 2]] = True
    return {"G": ndimage.binary_dilation(G), "lo": lo, "cell": cell}


def _enclosure(occ: dict, P: np.ndarray, axis: np.ndarray, rmax: float, rmin: float = 0.0) -> np.ndarray:
    """Her nokta için eksene dik 8 yönde [rmin, rmax] aralığında kumaşa çarpan ışın oranı."""
    G, lo, c = occ["G"], occ["lo"], occ["cell"]
    a = axis / np.linalg.norm(axis)
    t = np.cross(a, [0.0, 0.0, 1.0] if abs(a[2]) < 0.9 else [1.0, 0.0, 0.0])
    t /= np.linalg.norm(t)
    b = np.cross(a, t)
    dirs = np.array([np.cos(k * np.pi / 4) * t + np.sin(k * np.pi / 4) * b for k in range(8)])
    steps = np.arange(max(1, int(rmin / c)), int(rmax / c) + 1) * c
    Q = P[:, None, None, :] + dirs[None, :, None, :] * steps[None, None, :, None]
    I = ((Q - lo) / c).astype(int)
    ok = np.all((I >= 0) & (I < np.array(G.shape)), axis=-1)
    hit = np.zeros(ok.shape, bool)
    Ii = I[ok]
    hit[ok] = G[Ii[:, 0], Ii[:, 1], Ii[:, 2]]
    return hit.any(axis=2).mean(axis=1)


SLEEVE_START = 2         # kolluk sarılması kolun ilk bu kadar+1 örneğinde (≤ kol boyunun ~%30u: koltuk altı hizası) başlamalı
SLEEVE_MIN_UP = 0.34     # kol aramasında üst kolun en az bu kadarı sarılıyorsa kol kollukta
ARM_INSET = 0.25         # kol köşeleri kol eksenine bu oranda içeri: kolluğun kola değmesi kesme sayılmaz
ARM_CROSS_W = 2.0        # kollu kıyafet aramasında kumaşı kesen kol noktalarının cezası
ARM_ROOT = 0.12          # omuz ekleminden bu kadar (× kol boyu) içerisi kesme sayılmaz (oyuk kenarı)


def arm_samples(bv0: np.ndarray, lm: dict, side: int, n: int = 400) -> dict[str, np.ndarray]:
    """T-poz kolunun örnekleri (pose_arms ile aynı eklem ve eksen): eklemden göreli
    konumlar (eksene ARM_INSET kadar çekilmiş), eksen boyunca kol boyu oranı t."""
    am = arm_vertices(bv0, lm) & (np.sign(bv0[:, 0]) == side)
    A = bv0[am]
    piv = np.array([side * lm["shoulder_x"] * 0.80, lm["arm_cy"], lm["arm_cz"]])
    u = np.linalg.svd(A - A.mean(axis=0), full_matrices=False)[2][0]
    u = u if u[0] * side > 0 else -u
    rel = A - piv
    t = rel @ u
    axis_pt = A.mean(axis=0) - piv + np.outer(t - (A.mean(axis=0) - piv) @ u, u)
    rel = rel + ARM_INSET * (axis_pt - rel)
    tf = (t - t.min()) / max(float(np.ptp(t)), 1e-9)
    keep = tf > ARM_ROOT
    idx = np.nonzero(keep)[0]
    if len(idx) > n:
        idx = idx[np.random.default_rng(side + 2).choice(len(idx), n, replace=False)]
    return {"piv": piv, "u": u, "rel": rel[idx], "t": tf[idx]}


def arm_crossing(occ: dict, smp: dict, d: np.ndarray, s: float, pos: np.ndarray,
                 sleeve: float | None = None) -> float:
    """Kol `d` yönüne döndürülünce (eklemde katı dönme) kumaşı kesen örnek oranı (el ucu
    yarım ağırlıklı: ele değen etek kumaşı kolun gövdeden geçmesi kadar kötü değil).
    `sleeve` = kolluğun bittiği kol boyu oranı: kolluğun İÇİNDEKİ temas sayılmaz —
    üretilen kolluk koldan dar olabilir, onu fit_vertices kolun etrafında genişletir."""
    u = smp["u"]
    axis = np.cross(u, d)
    theta = math.acos(float(np.clip(u @ d, -1, 1)))
    rel = smp["rel"] if np.linalg.norm(axis) < 1e-9 else \
        _rodrigues(smp["rel"], axis, np.full(len(smp["rel"]), theta))
    P = (smp["piv"] + rel) * s + pos
    G, lo, c = occ["G"], occ["lo"], occ["cell"]
    I = ((P - lo) / c).astype(int)
    ok = np.all((I >= 0) & (I < np.array(G.shape)), axis=1)
    hit = np.zeros(len(P), bool)
    hit[ok] = G[I[ok, 0], I[ok, 1], I[ok, 2]]
    w = np.where(smp["t"] > 0.85, 0.5, 1.0)
    if sleeve is not None:
        return float((hit * w * (smp["t"] > sleeve)).sum() / w.sum())
    return float((hit * w).sum() / w.sum())


def sleeve_run(full: np.ndarray) -> int:
    """Omuzdan (ilk örnekler) başlayan kesintisiz sarılmanın son indeksi; tek tük sarılmayan
    kesit (kolluk kıvrımı, delik) araya girebilir. Sarılma omuzda başlamıyorsa (-1): kolu
    dirsekten aşağı saran bol etek / geniş gövde kolluk değildir."""
    last, miss = -1, 0
    for i, f in enumerate(full):
        if f:
            last, miss = i, 0
            continue
        if last < 0:                       # henüz başlamadı: yalnız başlangıç penceresi
            if i >= SLEEVE_START:
                break
            continue
        miss += 1
        if miss > 1:
            break
    return last


def _arm_dir(side: int, th: float, ph: float) -> np.ndarray:
    o, f = math.radians(th), math.radians(ph)
    return np.array([side * math.sin(o), -math.cos(o) * math.cos(f), math.cos(o) * math.sin(f)])


def clear_arm_dirs(occ: dict, smps: dict, s: float, pos: np.ndarray) -> tuple[dict[int, np.ndarray], dict]:
    """Kolsuz / alt giyim: kumaşı KESMEYEN en doğal kol yönü (aynalı). Kol oyuğundan çıkar,
    bol etek/kloş eteğin dışından iner; kumaş kolu hiç zorlamıyorsa doğal duruş kalır."""
    best = None
    for th in range(4, 76, 3):                    # dikten dışa
        for ph in range(-10, 31, 5):              # öne
            cr = max(arm_crossing(occ, smps[sd], _arm_dir(sd, th, ph), s, pos) for sd in (1, -1))
            cost = cr + 0.0015 * abs(th - 12) + 0.001 * abs(ph - 10)
            if best is None or cost < best[0]:
                best = (cost, th, ph, cr)
    _, th, ph, cr = best
    out = {sd: _arm_dir(sd, th, ph) for sd in (1, -1)}
    return out, {str(sd): {"enclosure": 0.0, "deg_from_vertical": float(th), "forward_deg": float(ph),
                           "crossing": round(cr, 3)} for sd in (1, -1)}


def search_arm_dirs(occ: dict, lm: dict, s: float, pos: np.ndarray,
                    smps: dict | None = None) -> tuple[dict[int, np.ndarray], dict]:
    """Kollar için omuzdan aday yönler tara; kolu kumaşın en iyi SARDIĞI yönü seç
    (kolluk içindeki kol neredeyse her yönde kumaşa çarpar; havadaki hiçbir yerde;
    bol gövdenin içine sarkan kol yalnız birkaç yönde). Kolun kumaşı KESMESİ (kolluk
    dışında kalan ön kolun eteği/gövdeyi delmesi) cezalıdır. İki kol AYNALI tek açıyla
    aranır (kıyafetler simetrik; tek yandaki delik/gürültü sonucu bozmasın). Hiçbir
    yönde yeterince sarılmıyorsa (kolsuz kıyafet) kumaşı kesmeyen en doğal yön."""
    H = lm["H"] * s
    L = 0.33 * H                                  # omuz→bilek (beden boyunun ~%33'ü)
    G, lo, c = occ["G"], occ["lo"], occ["cell"]
    tt = np.linspace(0.15, 0.95, 12) * L          # kolun tamamı (omuz→bilek)
    wts = np.where(tt < 0.55 * L, 1.0, 0.6)       # üst kol daha belirleyici
    pivots = {side: np.array([side * lm["shoulder_x"] * 0.80, lm["arm_cy"], lm["arm_cz"]]) * s + pos
              for side in (1, -1)}

    def side_score(side: int, d: np.ndarray) -> tuple[float, float]:
        P = pivots[side] + tt[:, None] * d
        enc = _enclosure(occ, P, d, 0.07 * H, rmin=0.014 * H)
        full = (enc >= 0.875).astype(float)       # ≥7/8 ışın: gerçekten kolluk içinde
        full *= np.arange(len(full)) <= sleeve_run(full)   # kolluk omuzdan başlar (bol etek değil)
        I = ((P - lo) / c).astype(int)
        ok = np.all((I >= 0) & (I < np.array(G.shape)), axis=1)
        inwall = np.zeros(len(P), bool)
        inwall[ok] = G[I[ok, 0], I[ok, 1], I[ok, 2]]   # ekseni kumaşın içinden geçen kol cezalı
        sc = float((full * wts).sum() / wts.sum()) - 0.8 * float(inwall.mean())
        if smps is not None:
            # kolluk = omuzdan başlayıp en son sarılan noktaya kadar
            inside = np.nonzero(full > 0)[0]
            end = float(tt[inside[-1]] / L) + 0.05 if len(inside) else 0.0
            sc -= ARM_CROSS_W * arm_crossing(occ, smps[side], d, s, pos, end)
        return sc, float(full[tt < 0.55 * L].mean())

    best = (-9.0, 0, 0, 0.0)
    for th in range(0, 100, 5):                   # 0° = dik aşağı … 90° = yatay (T-poz kolluk)
        for ph in range(-10, 30, 5):
            tot, ups = 0.0, []
            for side in (1, -1):
                sc, up = side_score(side, _arm_dir(side, th, ph))
                tot += sc
                ups.append(up)
            tot -= 0.004 * th                     # eşitlikte doğal (dik) duruş
            if tot > best[0]:
                best = (tot, th, ph, float(np.mean(ups)))
    _, th, ph, up = best
    if up < SLEEVE_MIN_UP:                        # üst kolun ~1/3'ü bile kollukta değil: kolsuz say
        if smps is not None:
            return clear_arm_dirs(occ, smps, s, pos)
        dirs = {side: default_arm_dir(side) for side in (1, -1)}
    else:
        dirs = {side: _arm_dir(side, th, ph) for side in (1, -1)}
    rep = {}
    for side, d in dirs.items():
        rep[str(side)] = {"enclosure": round(up, 2),
                          "deg_from_vertical": round(math.degrees(math.atan2(abs(d[0]), -d[1])), 1),
                          "forward_deg": round(math.degrees(math.atan2(d[2], -d[1])), 1)}
        if smps is not None:
            rep[str(side)]["crossing"] = round(arm_crossing(occ, smps[side], d, s, pos), 3)
    return dirs, rep


ARM_CLEAR_T = (0.15, 0.45)  # üst kol (× kol boyu): eksen ve yarıçap buradan; gövde kumaşı yalnız üst kolla çakışır
ARM_CLEAR_ROUNDS = 4        # itme turu (yayılımın kola soktuğu köşeler bir sonraki turda çıkar)
ARM_CLEAR_SPREAD = 1.5      # itme, kol yarıçapının bu katı içinde koni düşüşüyle komşulara yayılır


def clear_arm_roots(wv: np.ndarray, arms: dict[int, np.ndarray], lm: dict, dirs: dict[int, np.ndarray],
                    s: float, pos: np.ndarray, occ: dict, margin: float) -> tuple[np.ndarray, dict]:
    """Koltuk altının altında kolun İÇİNDE kalan gövde kumaşını kol ile gövde ARASINA it.

    Kol pivotu sabit, üretilen korsaj gövdeden geniş: kol hangi doğal açıyla inerse insin
    kökü korsajın yan duvarını keser (kollar oyuktan değil kumaşın içinden çıkar; kolu
    yataya kaldırmak da doğal değil). Gerçekte o kumaş koltuk altında kola ve gövdeye
    sıkışır → üst kol silindirinin içindeki köşeler gövdeye bakan yönde (iç yan) silindirin
    `margin` dışına taşınır, itme komşulara yayılır (çift kabuk birlikte kayar).
    Yalnız kolsuz giysi / alt giyimde çağrılır (kol kollukta ise kökteki kumaş kolluğun
    kendisidir, onu fit_vertices kolun çevresinde açar); kolu SARAN kesitler (kolluk
    sanılmadan kalmış kısa kolluk) yine atlanır. Koltuk altının üstü (omuz, askı)
    dokunulmaz. `arms[side]`: pozlu kol köşeleri (manken yereli)."""
    from scipy.spatial import cKDTree
    W, inv = np.unique(np.round(wv, 9), axis=0, return_inverse=True)
    inv = inv.ravel()
    out = W.copy()
    armpit_y = lm["levels"]["armpit"] * s + pos[1]
    rep: dict[str, Any] = {}
    for side, d in dirs.items():
        A = arms[side] * s + pos
        t = A @ (d / np.linalg.norm(d))
        t0, L = float(t.min()), float(np.ptp(t))
        up = (t > t0 + ARM_CLEAR_T[0] * L) & (t < t0 + ARM_CLEAR_T[1] * L)
        if up.sum() < 10:
            continue
        # silindir: üst kol köşelerinden eksen (PCA) ve yarıçap (medyan uzaklık)
        c = A[up].mean(axis=0)
        ax = np.linalg.svd(A[up] - c, full_matrices=False)[2][0]
        ax = ax if ax @ d > 0 else -ax
        rad = float(np.median(np.linalg.norm((A[up] - c) - np.outer((A[up] - c) @ ax, ax), axis=1)))
        R = rad + margin
        ta = (A - c) @ ax
        lo_t, hi_t = float(ta.min()), float(ta.min() + ARM_CLEAR_T[1] * np.ptp(ta))
        tb = np.linspace(lo_t, hi_t, 8)
        enc = _enclosure(occ, c + tb[:, None] * ax, ax, 2.0 * rad, rmin=R)
        m = np.array([-side, 0.0, 0.0])
        m -= (m @ ax) * ax
        m /= np.linalg.norm(m)
        rho = ARM_CLEAR_SPREAD * rad
        open_sec = enc < 0.875                   # kolu saran kesit: kolluk
        start = out.copy()
        n_in, moved = 0, np.zeros(len(W), bool)
        for _ in range(ARM_CLEAR_ROUNDS):        # yayılım dış yandaki komşuyu kola sokabilir → tekrar
            g = out - c
            gt = g @ ax
            q = g - np.outer(gt, ax)
            cand = (W[:, 1] < armpit_y) & (gt > lo_t) & (gt < hi_t) & (np.linalg.norm(q, axis=1) < R)
            cand &= open_sec[np.clip(np.searchsorted(tb, gt), 0, len(tb) - 1)]
            idx = np.nonzero(cand)[0]
            if not len(idx):
                break
            n_in = n_in or len(idx)
            qm = q[idx] @ m
            lam = -qm + np.sqrt(np.maximum(qm ** 2 - (q[idx] ** 2).sum(axis=1) + R ** 2, 0.0))
            mag = np.zeros(len(W))
            mag[idx] = lam
            for j, lj, nb in zip(idx, lam, cKDTree(out).query_ball_point(out[idx], rho), strict=True):
                nb = np.asarray(nb, dtype=int)
                np.maximum.at(mag, nb, lj * (1.0 - np.linalg.norm(out[nb] - out[j], axis=1) / rho))
            out += mag[:, None] * m
            moved |= mag > 1e-9
        rep[str(side)] = {"inside": int(n_in), "moved": int(moved.sum()),
                          "max_move": round(float(np.linalg.norm(out - start, axis=1).max(initial=0.0)), 4)}
    return out[inv], rep


def align_to_arms(gv: np.ndarray, prof: dict, arm_pts: np.ndarray, max_shift: float = 0.04,
                  ramp: float = 0.10) -> tuple[np.ndarray, dict[str, Any]]:
    """Kolluk ince hizası (silüet kolluk satırlarıyla): her satırda kolluk merkezi →
    kol merkezi ötelemesi (≤ max_shift), gövde kenarının içi ötelenmez."""
    v = np.asarray(gv, float).copy()
    rep: dict[str, Any] = {}
    for side, S in prof["sleeve_rows"].items():
        A = arm_pts[np.sign(arm_pts[:, 0]) == side]
        if len(A) < 20:
            continue
        top = float(np.quantile(A[:, 1], 0.98))
        rows = []
        for y, sx, sz, lim in S:
            a = A[np.abs(A[:, 1] - y) < 0.012]
            if len(a) < 3 or np.isnan(sz):
                continue
            rows.append((y, a[:, 0].mean() - sx, a[:, 2].mean() - sz, lim))
        if len(rows) < 3:
            continue
        R = np.array(sorted(rows))
        # Gerçek kolluk kolun hemen etrafındadır: kola uzak "kolluk" satırları (delik/
        # çukur kaynaklı sahte kesit parçaları) kırpılmaz, tamamen atılır — yoksa gövde
        # duvarını kola doğru basamaklı kaydırır.
        R = R[np.linalg.norm(R[:, 1:3], axis=1) <= 2.5 * max_shift]
        if len(R) < 3:
            continue
        for k in (1, 2):
            R[:, k] = np.array([np.median(R[max(0, i - 3):i + 4, k]) for i in range(len(R))])
        off = R[:, 1:3]
        n = np.linalg.norm(off, axis=1, keepdims=True)
        off = off * np.minimum(1.0, max_shift / np.maximum(n, 1e-9))
        sel = np.nonzero(np.sign(v[:, 0]) == side)[0]
        y = v[sel, 1]
        lim = np.interp(y, R[:, 0], R[:, 3])
        w = np.clip((np.abs(v[sel, 0]) - (lim - 0.03)) / 0.03, 0, 1) * np.clip((top - y) / ramp, 0, 1)
        w *= (y >= R[0, 0] - 0.02) & (y <= R[-1, 0] + 0.02)
        v[sel, 0] += np.interp(y, R[:, 0], off[:, 0]) * w
        v[sel, 2] += np.interp(y, R[:, 0], off[:, 1]) * w
        rep[f"side{side:+d}"] = {"rows": len(R), "mean_shift": round(float(np.linalg.norm(off, axis=1).mean()), 4)}
    return v, rep


def auto_transform(prof: dict, lm: dict, garment_type: str) -> dict[str, Any]:
    """Kıyafet ↔ manken landmark eşlemesi → {position, rotation, scale} (manken yerel → kıyafet)."""
    R = prof["rows"]
    if len(R) < 5:
        raise ValueError("Kıyafet analiz edilemedi (çok az geometri).")
    H = prof["H"]
    if garment_type in BOTTOMS:
        top_rows = R[R[:, 0] > prof["top"] - 0.08 * H]
        waist_g = float(np.median(top_rows[:, 1]))
        s = waist_g / (lm["waist_half"] * EASE_WAIST)
        py = prof["top"] - 0.01 * H - lm["levels"]["waist"] * s
        pz = float(np.median(top_rows[:, 2])) - lm["waist_z"] * s
        return {"position": [0.0, py, pz], "rotation": [0, 0, 0], "scale": s, "anchor": "waist"}
    # Üst giyim. Çapa = koltuk altı (silüette net kırılma; kapüşon/yaka yanıltmaz).
    arm_g = prof.get("armpit")
    # Mantıksız koltuk altı (etek/yaka hizası) → tipik oran (üstten ~%35).
    if arm_g is None or not (prof["top"] - 0.65 * H < arm_g < prof["top"] - 0.12 * H):
        arm_g = prof["top"] - 0.35 * H
    # Ölçek ipucu 1 — genişlik: koltuk altının hemen altındaki gövde yarı-genişliği.
    chest = R[(R[:, 0] < arm_g - 0.03 * H) & (R[:, 0] > arm_g - 0.25 * H)]
    if not len(chest):
        chest = R
    chest_g = float(np.median(chest[:, 1]))
    s_w = chest_g / (lm["chest_half"] * EASE_TOP)
    # Ölçek ipucu 2 — boy: koltuk altı→etek ≈ koltuk altı→(kalça-kasık arası).
    hem_m = 0.5 * (lm["levels"]["hip"] + lm["levels"]["crotch"])
    s_h = (arm_g - prof["bottom"]) / max(lm["levels"]["armpit"] - hem_m, 1e-6)
    # İpuçları uyuşursa ortalama; %25'ten fazla ayrışırsa KÜÇÜĞÜ (oversize kesim genişliği,
    # uzun kesim boyu şişirir; küçük olan bedeni kıyafetten taşırmaz).
    s = 0.5 * (s_w + s_h) if abs(s_w - s_h) <= 0.25 * min(s_w, s_h) else min(s_w, s_h)
    py = arm_g - lm["levels"]["armpit"] * s
    chest_y = lm["levels"]["chest"] * s + py
    near = R[np.abs(R[:, 0] - chest_y) < 0.05 * H]
    gz = float(np.median(near[:, 2])) if len(near) else float(np.median(chest[:, 2]))
    pz = gz - lm["chest_z"] * s
    return {"position": [0.0, py, pz], "rotation": [0, 0, 0], "scale": s, "anchor": "armpit",
            "cues": {"width": round(s_w, 3), "height": round(s_h, 3)}}


def settle(gv: np.ndarray, bv0: np.ndarray, bf: np.ndarray, lm: dict, tr: dict) -> tuple[dict, dict]:
    """Kıyafeti bedene "bırak": ölçek sabit; önce önden-arkaya, sonra dikey öteleme
    taranır. Gövde (kollar ve boyun üstü hariç) kumaşı en az delen konumlar arasından
    EN YUKARIDAKİ seçilir → kıyafet omuzlara oturur ama gövdeyi içine almaz."""
    from scipy.spatial import cKDTree
    s = float(tr["scale"])
    pos = np.asarray(tr["position"], float)
    keep = ~arm_vertices(bv0, lm) & (bv0[:, 1] < lm["levels"]["neck"])
    pts, nrm = body_samples(bv0, bf, n=40_000, seed=2)
    near_keep = cKDTree(bv0[keep]).query(pts)[0] < 0.02 * lm["H"]
    pts, nrm = pts[near_keep] * s, nrm[near_keep]
    g = np.asarray(gv, float)
    gtree = cKDTree(g)
    H = float(np.ptp(g[:, 1]))

    def pen(off: np.ndarray) -> int:
        P = pts + pos + off
        d, i = gtree.query(P, k=1)
        # Beden noktası kumaşın dışına taştı mı: en yakın kumaş noktasına göre beden
        # normali yönünde ileride kalıyorsa (ve yakınsa) taşma sayılır.
        out = ((P - g[i]) * nrm).sum(axis=1) > 0
        return int((out & (d < 0.08 * H)).sum())

    zs = np.arange(-0.04, 0.0401, 0.01) * H
    best_z = min(zs, key=lambda z: (pen(np.array([0.0, 0.0, z])), abs(z)))
    ys = np.arange(-0.15, 0.1001, 0.01) * H
    pens = [pen(np.array([0.0, y, best_z])) for y in ys]
    pmin = min(pens)
    tol = pmin + max(5, int(0.01 * len(pts)))
    best_y = max(y for y, pv in zip(ys, pens) if pv <= tol)
    out = dict(tr)
    out["position"] = [float(pos[0]), float(pos[1] + best_y), float(pos[2] + best_z)]
    return out, {"dy": round(float(best_y), 4), "dz": round(float(best_z), 4), "pen_min": pmin,
                 "pen_at_0": pens[int(np.argmin(np.abs(ys)))]}


# --- kayıt (ölçek + konum) ------------------------------------------------------------
# Landmark tahmini (koltuk altı / etek ucu / sabit bolluk) türden türe kırılgandı: askılar
# kolluk, elbise beli koltuk altı sanılıyordu. Bunun yerine manken gövdesinin yatay
# kesitlerinden kumaşa ışın atılır ve ölçek + konum, "gövde kumaşı delmeden içine sığsın"
# koşuluyla aranır. Dar yer (bel/beden/kalça) kendiliğinden mankenin aynı yerine oturur.
REG_BINS = 24                      # kesit başına ışın (azimut)
REG_K_IN = np.linspace(0.15, 1.0, 11)  # gövde yarıçapı oranında iç örnekler (delme testi)
REG_PEN_K = 0.86                   # bu oranın içinde kumaş = delme (≈1–2 cm)
REG_PEN_TOLS = (0.02, 0.06, 0.12, 0.2)   # izin verilen delme oranı (en iyiye ek), kademeli
REG_LONG = 0.80                    # kıyafet boyu / manken boyu bunun üstündeyse tolerans gevşer
REG_EASE = 0.97                    # bulunan ölçeğin bu katı → hafif bolluk payı
# Çapa (üstte omuz, altta bel) kıyafetin tepesinden en fazla bu kadar (× manken boyu)
# aşağıda: kapüşonun başı örtmesi kadar; daha aşağısı (omuzlar elbise belinde gibi) olmaz.
REG_ANCHOR_DROP = 0.18
REG_SHOULDER_DROP = 0.06           # üst giyim: omuz, kıyafetin omuz çizgisinden en fazla bu kadar aşağıda
REG_SHOULDER_W = 0.85              # omuz çizgisi: gövde yarı-genişliği üst bölge medyanının bu katı
REG_Z_RANGE = 0.07                 # ön-arka arama (× kıyafet boyu)
# Üretilen kıyafetin DERİNLİĞİ (ön-arka) tek görselden uydurulur ve çoğu zaman basıktır;
# genişliği güvenilir. Delme testi yalnız yana bakan ışınlarla (|cos| ≥ bu, ±15°) yapılır;
# ön/arka ışınlar gövdeyi kumaşın ortasına alır (kalan delmeyi fit_vertices iter).
REG_LATERAL = 0.96
REG_Z_W = 4.0                      # ön-arka seçiminde ön/arka delme dengesinin ağırlığı
REG_MIN_COVER = 0.5                # oturma bölgesinde kumaşa çarpan ışın oranı alt sınırı
REG_SHELL_K = 1.3                  # kabuk (en dış kumaş) gövde yarıçapının bu katına kadar aranır


def _main_cluster(p: np.ndarray, gap: float, center: bool) -> np.ndarray:
    """Kesitte x boşluklarıyla ayrılan kümelerden gövdeninkini döndür: center → x=0'ı
    içeren (yoksa en yakın), değilse (bacak) en kalabalık küme. A-pozda gövdenin yanına
    inen kollar/eller ayrı küme kalır ve gövde yarıçapını şişirmez."""
    if len(p) < 10:
        return p
    order = np.argsort(p[:, 0])
    xs = p[order, 0]
    cuts = np.nonzero(np.diff(xs) > gap)[0] + 1
    groups = np.split(order, cuts)
    if len(groups) == 1:
        return p
    if center:
        g = min(groups, key=lambda ix: 0.0 if p[ix, 0].min() <= 0 <= p[ix, 0].max()
                else float(np.min(np.abs(p[ix, 0]))))
    else:
        g = max(groups, key=len)
    return p[g]


def body_rings(bv0: np.ndarray, bf: np.ndarray, lm: dict, garment_type: str) -> dict[str, np.ndarray]:
    """Manken (yerel) gövde kesitleri: her yükseklik × azimut için merkez ve yarıçap.
    Kollar (T-poz maskesi + kesitte ayrı küme kalan A-poz kolları/eller) ve boyun üstü hariç; kasık altında her bacak kendi merkezinden (iç bacak
    kumaşı delme sayılmasın). Alt giyimde belin üstü alınmaz."""
    H = lm["H"]
    pts, _ = body_samples(bv0, bf, n=60_000, seed=3)
    pts = pts[~arm_vertices(pts, lm)]
    lv = lm["levels"]
    top = lv["waist"] + 0.02 * H if garment_type in BOTTOMS else lv["neck"]
    ys = np.arange(lm["y0"] + 0.06 * H, top, 0.01 * H)
    th = np.arange(REG_BINS) * (2 * np.pi / REG_BINS)
    out = {k: [] for k in ("y", "cx", "cz", "r", "dx", "dz", "row")}
    for i, y in enumerate(ys):
        sl = pts[np.abs(pts[:, 1] - y) < 0.006 * H]
        if len(sl) < 20:
            continue
        parts = [sl[sl[:, 0] > 0], sl[sl[:, 0] <= 0]] if y < lv["crotch"] else [sl]
        for p in parts:
            p = _main_cluster(p, 0.012 * H, center=len(parts) == 1)
            if len(p) < 10:
                continue
            cx = 0.0 if len(parts) == 1 else 0.5 * float(p[:, 0].min() + p[:, 0].max())
            cz = 0.5 * float(p[:, 2].min() + p[:, 2].max())
            a = np.arctan2(p[:, 2] - cz, p[:, 0] - cx) % (2 * np.pi)
            rr = np.hypot(p[:, 0] - cx, p[:, 2] - cz)
            b = (a / (2 * np.pi) * REG_BINS).astype(int) % REG_BINS
            r = np.zeros(REG_BINS)
            np.maximum.at(r, b, rr)
            for j in np.nonzero(r > 0.005 * H)[0]:
                out["y"].append(y); out["cx"].append(cx); out["cz"].append(cz); out["r"].append(r[j])
                out["dx"].append(np.cos(th[j])); out["dz"].append(np.sin(th[j])); out["row"].append(i)
    return {k: np.asarray(v, float) for k, v in out.items()}


def _ray_hits(occ: dict, rings: dict, s: float, py: float, pz: float, kk: np.ndarray) -> np.ndarray:
    """Her ışın × örnek oranı (kk) için kumaşa çarpma (bool)."""
    G, lo, c = occ["G"], occ["lo"], occ["cell"]
    r = rings["r"][:, None] * kk[None, :] * s
    P = np.stack([rings["cx"][:, None] * s + rings["dx"][:, None] * r,
                  np.broadcast_to(rings["y"][:, None] * s + py, r.shape),
                  rings["cz"][:, None] * s + pz + rings["dz"][:, None] * r], axis=-1)
    I = ((P - lo) / c).astype(int)
    ok = np.all((I >= 0) & (I < np.array(G.shape)), axis=-1)
    hit = np.zeros(ok.shape, bool)
    Ii = I[ok]
    hit[ok] = G[Ii[:, 0], Ii[:, 1], Ii[:, 2]]
    return hit


def garment_length(prof: dict, garment_type: str) -> float:
    """Boy oranı kontrolleri için kıyafet boyu: üst giyimde omuz çizgisinden etek ucuna
    (görselden gelen manken boynu/kapüşon sayılmaz), alt giyimde tüm boy."""
    if garment_type in BOTTOMS:
        return prof["H"]
    return shoulder_line(prof) - prof["bottom"]


_EVAL_HOOK: list | None = None     # testler/teşhis: register_body'nin değerlendiricisi


def shoulder_line(prof: dict) -> float:
    """Kıyafetin omuz çizgisi (y): üst %45'te gövde yarı-genişliği medyanın REG_SHOULDER_W
    katını geçen ya da kolluk/askı ayrışan EN ÜST kesit. Boyun parçası, dik yaka ve
    kapüşon tek ve dar orta bileşendir → elenir."""
    R = prof["rows"]
    up = R[R[:, 0] > prof["top"] - 0.45 * prof["H"]]
    if len(up) < 3:
        return prof["top"]
    # Omuz bölgesi: gövde genişse YA DA o kesitte kolluk/askı ayrışıyorsa (askılı elbise).
    wide = up[(up[:, 1] >= REG_SHOULDER_W * float(np.median(up[:, 1]))) | (up[:, 3] >= 1)]
    return float(wide[:, 0].max()) + 0.01 * prof["H"] if len(wide) else prof["top"]


def register_body(occ: dict, prof: dict, lm: dict, rings: dict, garment_type: str) -> tuple[dict, dict]:
    """Ölçek + konum araması (manken yerel → kıyafet çerçevesi, dönme yok).

    Her aday (ölçek, dikey, ön-arka) için gövde ışınları:
    - pen: kıyafet boyuna giren ışınlardan kumaşı DELENLERİN oranı (gövde kumaşın içinde
      kalmalı);
    - snug: OTURMA BÖLGESİNDE (üstte göğüs→bel, altta bel→kalça) kumaşa ortalama
      boşluk (gövde yarıçapı oranında; kumaşa çarpmayan ışın = en büyük boşluk). Kıyafet
      orada bedene oturur — kloş etek gibi bol kısımlar ölçeği yanıltamaz.
    Sığan (pen ≤ en iyi + tolerans) adaylardan snug'ı en küçük olan seçilir (eşitlikte
    büyük ölçek), çevresinde ince aranır. Son adımda ölçek REG_EASE ile hafif gevşetilir;
    gövde sığan konumlar arasından EN YUKARIYA alınır (kıyafet omuza/kalçaya "oturur")."""
    H, Hg = lm["H"], prof["H"]
    gtop, gbot = prof["top"], prof["bottom"]
    lv = lm["levels"]
    if garment_type in BOTTOMS:
        anchor = lv["waist"] - 0.03 * H
        snug_band = (lv["hip"] - 0.01 * H, lv["waist"] + 0.01 * H)
        span = (0.12, 0.85)                       # kıyafet boyu / manken boyu
        a_top, drop = gtop, REG_ANCHOR_DROP
    else:
        anchor = lm["shoulder_y"] - 0.015 * H
        # Çapa kıyafetin tepesine değil OMUZ ÇİZGİSİNE: boyun parçası (görselden gelen
        # manken boynu), dik yaka ve kapüşon tepe sayılmaz.
        a_top, drop = shoulder_line(prof), REG_SHOULDER_DROP
        snug_band = (lv["waist"] - 0.01 * H, lv["chest"] + 0.02 * H)
        span = (0.20, 0.88)
    kk_out = np.array([1.08, 1.18, 1.3, 1.45, 1.65, 1.9, 2.2, 2.6])
    kk = np.concatenate([REG_K_IN, kk_out])
    gap_of = np.append(kk - 1.0, 1.8)             # son = hiç çarpmadı
    n_shell = int(np.searchsorted(kk, REG_SHELL_K, side="right"))
    y_body = rings["y"]
    in_snug = (y_body >= snug_band[0]) & (y_body <= snug_band[1])
    n_snug = int(in_snug.sum())
    zc_g = float(np.median(prof["rows"][:, 2])) if len(prof["rows"]) else 0.0

    def zc0(sc: float) -> float:                   # gövde merkezi kıyafet merkezinde
        return zc_g - lm["chest_z"] * sc

    # Delme testi: yana bakan ışınlar; üst giyimde göğüs hattının altı (koltuk altı/omuz
    # eklemi kol oyuğundan/kolluk köküne doğal olarak taşar; kol oyuğu yüksekliği de
    # kıyafetten kıyafete değişir — orası delme ölçüsü değildir).
    lateral = np.abs(rings["dx"]) >= REG_LATERAL
    if garment_type not in BOTTOMS:
        lateral &= y_body < lv["chest"] + 0.01 * H
    else:
        # Bacaklar: A-poz bacak aralığı paça aralığıyla uyuşmaz; bacaktaki delmeyi
        # fit_vertices iter → ölçek/konum kalça-bel bandından.
        lateral &= y_body >= lv["crotch"]
    foot = lm["y0"]

    def evaluate(s: float, py: float, pz: float) -> tuple[float, float, int, float]:
        if gbot < foot * s + py - 0.01 * H * s:     # kıyafet ayak tabanının altına inemez
            return 1.0, 9.0, 0, 9.0
        yw = y_body * s + py
        valid = (yw > gbot + 0.01 * Hg) & (yw < gtop - 0.005 * Hg)
        if (valid & in_snug).sum() < 0.6 * n_snug:   # oturma bölgesi kıyafetin dışında
            return 1.0, 9.0, 0, 9.0
        hit = _ray_hits(occ, {k: v[valid] for k, v in rings.items()}, s, py, pz, kk)
        lat = lateral[valid]
        # Işın boyunca (gövdeye yakın) EN DIŞ kumaş = kıyafetin kabuğu. İçeride kalan yüzeyler (görselden
        # gelen manken gövdesi/boynu, astar, çift katman) delme sayılmaz.
        # Kabuk = gövdeye yakın bantta (uzaktaki etek kıvrımı sayılmaz) en dıştaki
        # KESİNTİSİZ kumaş bandı; iç ucu ölçülür. Bitişik çift katman (astar/kalınlık)
        # kabuğun parçasıdır; arada boşlukla ayrılan iç yüzeyler sayılmaz.
        near = hit[:, :n_shell]
        anyn = near.any(axis=1)
        start = np.where(anyn, n_shell - 1 - np.argmax(near[:, ::-1], axis=1), 0)
        for _ in range(n_shell):
            step = (start > 0) & near[np.arange(len(near)), np.maximum(start - 1, 0)]
            if not step.any():
                break
            start = start - step
        first = np.where(hit.any(axis=1), np.argmax(hit, axis=1), len(kk))
        last = np.where(anyn, start, first)
        pen = float((anyn & (kk[np.minimum(last, len(kk) - 1)] <= REG_PEN_K))[lat].mean())
        sn = in_snug[valid]
        # Gövde kumaşın İÇİNDE olmalı: oturma bölgesindeki ışınların çoğu kumaşa çarpar.
        # (Kumaştan çok büyük gövdede kumaş gövdenin derininde kalır, hiçbir ışın çarpmaz →
        # "delme yok" sanılıp en iyi delme sıfıra iniyor, gerçek adaylar eleniyordu.)
        if hit[sn].any(axis=1).mean() < REG_MIN_COVER:
            return 1.0, 9.0, 0, 9.0
        snug = float(np.mean(np.maximum(gap_of[last[sn]], 0.0)))
        # Ön/arka: derinlik güvenilmez → delme serbest ama dengeli (karesel derinlik);
        # yalnız ön-arka konumu seçer, ölçeği etkilemez (basık kumaş gövdeyi küçültmesin).
        fb = ~lat
        zd = float(np.mean(np.maximum(-gap_of[last[fb]], 0.0) ** 2)) if fb.any() else 0.0
        return pen, snug, int(valid.sum()), zd

    if _EVAL_HOOK is not None:
        _EVAL_HOOK.append(evaluate)

    def grid(ss, pys, pzs) -> np.ndarray:
        out = []
        for s in ss:
            for py in pys(s):
                for pz in pzs(s):
                    out.append((s, py, pz, *evaluate(s, py, pz)))
        A = np.array(out)
        return A[A[:, 5] > 0]

    def pick(A: np.ndarray, pmin: float, tol: float) -> np.ndarray:
        ok = A[A[:, 3] <= pmin + tol]
        # Ölçek + yükseklik: oturma boşluğu (düz bir eğri → 0.01 hassasiyet, eşitlikte
        # büyük ölçek). Ön-arka: o ölçek/yükseklikteki adaylardan boşluk + ön/arka delme
        # dengesi en iyi olan.
        b = ok[np.lexsort((-ok[:, 0], np.round(ok[:, 4], 2)))][0]
        same = ok[(ok[:, 0] == b[0]) & (ok[:, 1] == b[1])]
        return same[np.argmin(same[:, 4] + REG_Z_W * same[:, 6])]

    def py_range(s: float, n: int, lo_frac: float = drop):
        hi = a_top - 0.005 * Hg - anchor * s      # çapa en fazla kıyafetin tepesinde
        return np.linspace(hi - lo_frac * H * s, hi, n)

    s_lo, s_hi = Hg / (span[1] * H), Hg / (span[0] * H)
    A0 = grid(np.geomspace(s_lo, s_hi, 32), lambda s: py_range(s, 16),
              lambda s: np.linspace(-REG_Z_RANGE, REG_Z_RANGE, 9) * Hg + zc0(s))
    if not len(A0):
        raise ValueError("Kıyafet mankene hizalanamadı (oturma bölgesi bulunamadı).")
    pmin = float(A0[:, 3].min())
    # Üretilen kıyafetler çoğu zaman boyuna göre DAR çıkar (kalçayı tam sığdıran ölçekte
    # kıyafet bedenin tamamını örter). Sonuç bu kadar uzunsa delme toleransı kademeli
    # gevşetilir; kalan dar kısmı fit_vertices dışarı iter.
    for tol in REG_PEN_TOLS:
        b = pick(A0, pmin, tol)
        for ds, dy, dz, n in ((0.08, 0.04, 0.05, 7), (0.025, 0.012, 0.015, 7)):
            s0, y0, z0 = b[0], b[1], b[2]
            A = grid(np.linspace(s0 * (1 - ds), s0 * (1 + ds), n),
                     lambda s: np.linspace(-dy, dy, n) * H * s + y0 + (s - s0) * -anchor,
                     lambda s: np.linspace(-dz, dz, n) * Hg + z0 + zc0(s) - zc0(s0))
            if len(A):
                b = pick(np.vstack([A, b[None]]), pmin, tol)
        if garment_length(prof, garment_type) / (H * b[0] * REG_EASE) <= REG_LONG:
            break
    s_fit = float(b[0])
    s = s_fit * REG_EASE
    # Gevşetilmiş ölçekte: aynı çapa hizasından başlayıp gövde sığdığı kadar yukarı.
    y_c = b[1] + (s - s_fit) * -anchor
    y_top = min(y_c + 0.05 * H * s, a_top - 0.005 * Hg - anchor * s)
    Q = grid([s], lambda _s: np.linspace(min(y_c - 0.02 * H * s, y_top), y_top, 15),
             lambda _s: b[2] + zc0(s) - zc0(s_fit) + np.linspace(-0.02, 0.02, 9) * Hg)
    good = Q[(Q[:, 3] <= max(pmin + tol, b[3])) & (Q[:, 4] <= b[4] + 0.05)] if len(Q) else Q
    if len(good):
        py = float(good[:, 1].max())
        at = good[np.abs(good[:, 1] - py) < 1e-9]
        best = at[np.argmin(at[:, 4] + REG_Z_W * at[:, 6])]
    else:
        best = np.array([s, y_c, b[2] + zc0(s) - zc0(s_fit), b[3], b[4], b[5], b[6]])
    tr = {"position": [0.0, float(best[1]), float(best[2])], "rotation": [0, 0, 0], "scale": float(s),
          "anchor": "register"}
    return tr, {"s_fit": round(s_fit, 4), "pen": round(float(best[3]), 3), "pen_min": round(pmin, 3),
                "tol": tol,
                "snug_gap": round(float(best[4]), 3), "rays": int(best[5])}


# --- giydir -------------------------------------------------------------------------
def mannequin_height_m(mannequin_path: str, lm: dict) -> float:
    """Mankenin gerçek boyu: özel (ölçüden) mankenler metre ölçeklidir; taban mankenler
    birim boyludur → varsayılan boy (kadın 1.65, erkek 1.75, nötr 1.70)."""
    if lm["H"] > 1.2:
        return float(lm["H"])
    name = os.path.basename(mannequin_path)
    return 1.75 if name.startswith("male") else 1.65 if name.startswith("female") else 1.70


FLAT_RATIO = 0.45       # yükseklik / en büyük yatay boyut bunun altında: yatık/düz model
LEG_ROWS = 0.6          # üst giyimde alt %35'te ortası boş (iki bacak) kesit oranı üst sınırı


def check_garment_shape(v: np.ndarray, garment_type: str) -> None:
    """Giydirilemeyecek şekilleri baştan reddet: yatırılmış/yığılmış model ve (üst
    giyimde) bacakları olan model (tam insan figürü / tulum). Kayıt her şekle bir ölçek
    bulur; bu yüzden boy oranı tek başına yetmez."""
    ext = np.ptp(v, axis=0)
    if ext[1] < FLAT_RATIO * max(ext[0], ext[2]):
        raise ValueError("Model yatık ya da düz görünüyor (kıyafet dik durmalı). "
                         "Önden, dik duran bir kıyafet görseliyle yeniden üretin.")
    if garment_type in BOTTOMS:
        return
    H = float(ext[1])
    y0 = float(v[:, 1].min())
    xc = 0.5 * float(v[:, 0].min() + v[:, 0].max())
    band = 0.03 * float(ext[0])
    rows = empty = 0
    for y in np.linspace(y0 + 0.02 * H, y0 + 0.35 * H, 12):
        sl = v[np.abs(v[:, 1] - y) < 0.01 * H]
        if len(sl) < 10:
            continue
        rows += 1
        empty += int(not np.any(np.abs(sl[:, 0] - xc) < band))
    if rows >= 6 and empty >= LEG_ROWS * rows:
        raise ValueError("Modelde bacaklar var (tam insan figürü ya da tulum üretilmiş olabilir). "
                         "Yalnız kıyafeti gösteren bir görsel/prompt ile yeniden üretin.")


def check_garment_span(garment_h: float, body_h: float, garment_type: str) -> None:
    """Kıyafet boyu / manken boyu (aynı çerçevede) mantıksızsa reddet. Üretim bazen kıyafet
    yerine tam insan figürü verir (oran ~1.0); oturtulursa saçma ölçülerle 'başarılı' görünür.
    Tipik: uzun gömlek/kapüşonlu ~0.65, pantolon ~0.6."""
    ratio = garment_h / max(body_h, 1e-9)
    limit = SPAN_LIMIT_BOTTOM if garment_type in BOTTOMS else SPAN_LIMIT_TOP
    if ratio > limit:
        raise ValueError(f"Model kıyafete benzemiyor (boyu mankenin %{ratio * 100:.0f}'i — "
                         "tam figür üretilmiş olabilir). Farklı bir prompt/seed ile yeniden üretin.")


def dress_glb(garment_path: str, mannequin_path: str, garment_type: str, out_garment: str,
              out_mannequin: str, transform: dict | None = None, margin: float = 0.012) -> dict[str, Any]:
    """Kıyafeti mankene giydir. transform None → otomatik hiza. Döner: rapor
    (transform, kol yönleri, oturtma istatistikleri)."""
    import trimesh

    if garment_type not in TOPS | BOTTOMS:
        raise ValueError(f"'{garment_type}' türü için giydirme desteklenmiyor (üst/alt giyim).")
    base = trimesh.load(tpose_base(mannequin_path), force="mesh", process=False)
    bv0 = np.asarray(base.vertices, float)
    bf = np.asarray(base.faces)
    lm = body_landmarks(bv0, bf)

    scene = trimesh.load(garment_path, force="scene")
    geoms = []
    for name, geom in scene.geometry.items():
        if not hasattr(geom, "faces") or len(geom.faces) == 0:
            continue
        node = next((nd for nd in scene.graph.nodes_geometry if scene.graph[nd][1] == name), None)
        T = scene.graph[node][0] if node is not None else np.eye(4)
        geoms.append((name, geom, T))
    allw = np.concatenate([trimesh.transform_points(np.asarray(g.vertices, float), T) for _, g, T in geoms])
    offs = np.cumsum([0] + [len(g.vertices) for _, g, _ in geoms[:-1]])
    allf = np.concatenate([np.asarray(g.faces) + o for (_, g, _), o in zip(geoms, offs)])
    # Yön: kıyafetin önü yana bakıyorsa (derinlik ≫ genişlik) y ekseninde 90° çevir;
    # çıktı da çevrilmiş kalır (manken dönmez, kıyafet ona döner).
    Ry = facing_fix(allw)
    allw = allw @ Ry.T
    # Analiz (profil/doluluk) zemin plakası gibi ince yatay parçaları görmez.
    keep_f = analysis_faces(allw, allf)
    used = np.zeros(len(allw), bool)
    used[allf[keep_f].ravel()] = True
    if not transform:
        check_garment_shape(allw[used], garment_type)
    prof = garment_profile(allw[used], None)
    cut = pole_cut(prof)
    if cut is not None:                       # manken ayağı/direk: analizden kırp
        used &= allw[:, 1] >= cut
        keep_f &= np.all(allw[allf, 1] >= cut, axis=1)
        prof = garment_profile(allw[used], None)

    settle_rep: dict[str, Any] = {}
    occ = garment_occupancy(allw, allf[keep_f], 0.008 * prof["H"])
    if transform:
        tr = dict(transform)
    else:
        rings = body_rings(bv0, bf, lm, garment_type)
        tr, settle_rep = register_body(occ, prof, lm, rings, garment_type)
        check_garment_span(garment_length(prof, garment_type), lm["H"] * float(tr["scale"]), garment_type)
    s = float(tr["scale"])
    pos = np.asarray(tr["position"], float)
    # Kol yönleri kıyafet çerçevesinde; manken yereli aynı yönelimde (yalnız ölçek+öteleme).
    smps = {side: arm_samples(bv0, lm, side) for side in (1, -1)}
    if garment_type in TOPS:
        dirs, arm_rep = search_arm_dirs(occ, lm, s, pos, smps)
    else:
        dirs, arm_rep = clear_arm_dirs(occ, smps, s, pos)
    posed = pose_arms(bv0, lm, dirs)
    pm = trimesh.Trimesh(posed, bf, process=False)
    if hasattr(base, "visual"):
        pm.visual = base.visual
    pm.export(out_mannequin)

    bw = posed * s + pos
    bpts, bnrm = body_samples(bw, bf)
    arm_pts = bw[arm_vertices(bv0, lm)]
    report: dict[str, Any] = {"transform": {k: tr[k] for k in ("position", "rotation", "scale")},
                              "anchor": tr.get("anchor", "manual"),
                              "arm_dirs": {str(k): np.round(d, 3).tolist() for k, d in dirs.items()},
                              "arm_search": arm_rep, "settle": settle_rep,
                              "sleeves_found": sorted(int(k) for k in prof["sleeves"]),
                              "geometries": {}}
    am_t = arm_vertices(bv0, lm)
    arms = {sd: posed[am_t & (np.sign(bv0[:, 0]) == sd)] for sd in dirs}
    in_sleeve = any(r.get("enclosure", 0.0) >= SLEEVE_MIN_UP for r in arm_rep.values())
    report["arm_clear"] = {}
    fitted: list[np.ndarray] = []
    for name, geom, T in geoms:
        wv = trimesh.transform_points(np.asarray(geom.vertices, float), T) @ Ry.T
        srep: dict[str, Any] = {}
        if garment_type in TOPS and prof["sleeve_rows"]:
            wv, srep = align_to_arms(wv, prof, arm_pts)
        if not in_sleeve:
            wv, report["arm_clear"][name] = clear_arm_roots(wv, arms, lm, dirs, s, pos, occ, margin)
        # Boyun üstünde bedenin içinde kalan parçalar (görselden gelen manken boynu, baş
        # içi) kumaş taşması değildir → itilmez (yoksa yüzde "maske" oluşur). Gövdede derin
        # taşmalar (sığ üretilmiş kıyafet) da itilsin diye derinlik sınırı geniş.
        neck_w = lm["levels"]["neck"] * s + pos[1]
        frozen = wv[:, 1] > neck_w - 0.01 * lm["H"] * s
        new, rep = fit_vertices(wv, np.asarray(geom.faces), bpts, bnrm, margin=margin,
                                deep=0.25 * lm["H"] * s * 0.6, frozen=frozen)
        if not in_sleeve:
            # oturtma kumaşı gövdeden dışa iterken koltuk altı kıvrımındaki (kalın / çok
            # katmanlı) kumaşı kola geri sokabilir: son söz kolun (kıvrımda kalan gövde teması
            # kol ile gövde arasında, görünmez)
            new, report["arm_clear"][name]["after_fit"] = clear_arm_roots(
                new, arms, lm, dirs, s, pos, occ, margin)
        geom.vertices = trimesh.transform_points(new, np.linalg.inv(T))
        rep["sleeves"] = srep
        report["geometries"][name] = rep
        fitted.append(new)
    scene.export(out_garment)
    try:
        from clothsim_worker.measure import measure
        report["measurements"] = measure(np.concatenate(fitted), bw, arm_vertices(bv0, lm), lm, s, pos,
                                         mannequin_height_m(mannequin_path, lm), garment_type, dirs)
    except Exception as exc:  # noqa: BLE001 — ölçü tablosu giydirmeyi asla düşürmesin
        report["measurements"] = {"error": str(exc)}
    return report
