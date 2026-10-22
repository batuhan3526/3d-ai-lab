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
# tam figür / vazo üretimleri 0.90–1.09.
SPAN_LIMIT_TOP = 0.82
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


def search_arm_dirs(occ: dict, lm: dict, s: float, pos: np.ndarray) -> tuple[dict[int, np.ndarray], dict]:
    """Kollar için omuzdan aday yönler tara; kolu kumaşın en iyi SARDIĞI yönü seç
    (kolluk içindeki kol neredeyse her yönde kumaşa çarpar; havadaki hiçbir yerde;
    bol gövdenin içine sarkan kol yalnız birkaç yönde). İki kol AYNALI tek açıyla
    aranır (kıyafetler simetrik; tek yandaki delik/gürültü sonucu bozmasın). Hiçbir
    yönde yeterince sarılmıyorsa (kolsuz kıyafet) doğal varsayılan."""
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
        I = ((P - lo) / c).astype(int)
        ok = np.all((I >= 0) & (I < np.array(G.shape)), axis=1)
        inwall = np.zeros(len(P), bool)
        inwall[ok] = G[I[ok, 0], I[ok, 1], I[ok, 2]]   # ekseni kumaşın içinden geçen kol cezalı
        return float((full * wts).sum() / wts.sum()) - 0.8 * float(inwall.mean()), float(full[tt < 0.55 * L].mean())

    best = (-9.0, 0, 0, 0.0)
    for th in range(0, 100, 5):                   # 0° = dik aşağı … 90° = yatay (T-poz kolluk)
        for ph in range(-10, 30, 5):
            o, f = math.radians(th), math.radians(ph)
            tot, ups = 0.0, []
            for side in (1, -1):
                d = np.array([side * math.sin(o), -math.cos(o) * math.cos(f), math.cos(o) * math.sin(f)])
                sc, up = side_score(side, d)
                tot += sc
                ups.append(up)
            tot -= 0.004 * th                     # eşitlikte doğal (dik) duruş
            if tot > best[0]:
                best = (tot, th, ph, float(np.mean(ups)))
    _, th, ph, up = best
    out, rep = {}, {}
    for side in (1, -1):
        if up < 0.34:                             # üst kolun ~1/3'ü bile kollukta değil: kolsuz say
            d = default_arm_dir(side)
        else:
            o, f = math.radians(th), math.radians(ph)
            d = np.array([side * math.sin(o), -math.cos(o) * math.cos(f), math.cos(o) * math.sin(f)])
        out[side] = d
        rep[str(side)] = {"enclosure": round(up, 2),
                          "deg_from_vertical": round(math.degrees(math.atan2(abs(d[0]), -d[1])), 1),
                          "forward_deg": round(math.degrees(math.atan2(d[2], -d[1])), 1)}
    return out, rep


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


# --- giydir -------------------------------------------------------------------------
def mannequin_height_m(mannequin_path: str, lm: dict) -> float:
    """Mankenin gerçek boyu: özel (ölçüden) mankenler metre ölçeklidir; taban mankenler
    birim boyludur → varsayılan boy (kadın 1.65, erkek 1.75, nötr 1.70)."""
    if lm["H"] > 1.2:
        return float(lm["H"])
    name = os.path.basename(mannequin_path)
    return 1.75 if name.startswith("male") else 1.65 if name.startswith("female") else 1.70


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
    prof = garment_profile(allw, allf)

    settle_rep: dict[str, Any] = {}
    if transform:
        tr = dict(transform)
    else:
        tr = auto_transform(prof, lm, garment_type)
        check_garment_span(prof["H"], lm["H"] * float(tr["scale"]), garment_type)
        tr, settle_rep = settle(allw, bv0, bf, lm, tr)
    s = float(tr["scale"])
    pos = np.asarray(tr["position"], float)
    # Kol yönleri kıyafet çerçevesinde; manken yereli aynı yönelimde (yalnız ölçek+öteleme).
    if garment_type in TOPS:
        occ = garment_occupancy(allw, allf, 0.008 * prof["H"])
        dirs, arm_rep = search_arm_dirs(occ, lm, s, pos)
    else:
        dirs, arm_rep = {1: default_arm_dir(1), -1: default_arm_dir(-1)}, {}
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
    fitted: list[np.ndarray] = []
    for name, geom, T in geoms:
        wv = trimesh.transform_points(np.asarray(geom.vertices, float), T)
        srep: dict[str, Any] = {}
        if garment_type in TOPS and prof["sleeve_rows"]:
            wv, srep = align_to_arms(wv, prof, arm_pts)
        # Boyun üstünde bedenin içinde kalan parçalar (görselden gelen manken boynu, baş
        # içi) kumaş taşması değildir → itilmez (yoksa yüzde "maske" oluşur). Gövdede derin
        # taşmalar (sığ üretilmiş kıyafet) da itilsin diye derinlik sınırı geniş.
        neck_w = lm["levels"]["neck"] * s + pos[1]
        frozen = wv[:, 1] > neck_w - 0.01 * lm["H"] * s
        new, rep = fit_vertices(wv, np.asarray(geom.faces), bpts, bnrm, margin=margin,
                                deep=0.25 * lm["H"] * s * 0.6, frozen=frozen)
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
