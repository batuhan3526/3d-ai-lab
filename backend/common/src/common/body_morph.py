"""Ölçüden manken üretme — in-house CC0 taban mankenleri ölçülere göre morflar (F3).

SMPL/SMPL-X KULLANILMAZ (ticari lisans değil). Taban: `data/templates/mannequins/`
altındaki ev-içi CC0 mankenler (`female-a.glb`, `male-a.glb`). Bu GLB'ler birim
yüksekliğe normalize edilmiştir (Y-yukarı, boy ≈ 1.0 birim, ön yüz +Z, kollar
neredeyse yatay A-pozu, ~2.6-2.8k vertex, 79 kopuk parça — su geçirmez DEĞİL).

Ölçüm tanımları (terzi mezurası gibi):
- Boy: mesh'in Y uzunluğu (taban→tepe).
- Kesit çevresi: yatay düzlem kesiti (`trimesh.intersections.mesh_plane`) → 2B
  noktalar mesafe-eşiğiyle kümelenir → |x| merkezi gövdeye yakın kümeler (kollar
  hariç) birleşip KONVEKS ZARF çevresi alınır. Mezura içbükeylikleri köprülediği
  için konveks zarf çevresi mezura ölçüsüne en yakın tanımdır; ayrıca mesh'in
  kopuk/su geçirmez olmamasına karşı dayanıklıdır (shapely gerekmez).
- Seviyeler (profil taramasıyla otomatik): koltuk altı = kolların ilk göründüğü
  seviye; göğüs = koltuk altının altındaki bantta EN ÖNE çıkan (göğüs ucu/kafes)
  seviye; bel = kasık ile göğüs arasındaki EN DAR çevre; kalça = kasık ile bel
  arasındaki EN GENİŞ çevre; kasık = bacakların iki ayrı kesite ayrıldığı en üst
  seviye.

Morf (hepsi vertex başına, düz numpy):
1. Boy: üniform ölçek → hedef boy (metre). Çıktı GERÇEK ÖLÇEKTE metredir, ayak
   tabanı y=0'dadır (dikiş/drape gerçek ölçü ister).
2. Gövde: yükseklik boyunca pürüzsüz (PCHIP, aşmasız) yatay ölçek profili s(t);
   düğümler kasık/kalça/bel/göğüs/koltuk-altı/omuz/boyun seviyelerinde. x gövde
   ekseni (x=0), z o seviyenin gövde merkezi etrafında ölçeklenir.
3. Kollar: koltuk altı bandında |x| > omuz yarı-genişliği olan vertisler ölçeklenmez,
   omuz genişlemesi kadar dışarı ÖTELENİR; kalınlığı kol merkez hattı etrafında
   göğüs oranıyla yumuşak büyür (gövde↔kol geçişi smoothstep ağırlıkla sürekli).
4. Bacaklar: kasık altında her bacak KENDİ ekseni etrafında ölçeklenir (bacak
   aralığı kalça oranıyla açılır, kalınlık kasıktan bileğe doğru 1'e yaklaşır) →
   bacaklar iç içe geçmez, ayaklar bozulmaz.
5. Ölç→düzelt: göğüs/bel/kalça faktörleri `hedef/ölçülen` ile 2-4 tur düzeltilir
   (her tur tabandan yeniden morflanır, birikimli hata yok).
"""
from __future__ import annotations

import json
import math
from functools import lru_cache
from pathlib import Path
from typing import Any

import numpy as np
import trimesh

# 5 alanlı basit ölçü setinin kabul aralıkları (cm). Route 422 mesajı bunları kullanır.
BODY_RANGES_CM: dict[str, tuple[float, float]] = {
    "height_cm": (120.0, 215.0),
    "chest_cm": (60.0, 160.0),
    "waist_cm": (45.0, 160.0),
    "hip_cm": (60.0, 170.0),
}
# Taban başına yatay ölçek faktörü sınırı (aşırı değer mesh'i parçalamasın).
_FACTOR_MIN = 0.55
_FACTOR_MAX = 2.2

BASE_BY_GENDER = {"female": "female-a", "male": "male-a"}

# Profil taraması: t = (y - y_min) / boy.
_SCAN_LO = 0.20
_SCAN_HI = 0.95
_SCAN_STEP = 0.005
# Kesit kümeleme eşiği (boyun oranı) ve "gövde kümesi" sınırı (|cx| < oran*boy).
_CLUSTER_GAP = 0.025
_TORSO_X = 0.15
# Ölçü toleransı (doğrulamada ve testte kullanılır).
TOLERANCE = 0.03


# --- kesit ölçümü --------------------------------------------------------------
def _section_points(verts: np.ndarray, faces: np.ndarray, y: float) -> np.ndarray:
    """Yatay düzlem (Y=y) kesitinin 2B (x, z) noktaları; kesit yoksa (0,2)."""
    from trimesh.intersections import mesh_plane

    m = trimesh.Trimesh(vertices=verts, faces=faces, process=False)
    try:
        seg = mesh_plane(m, plane_normal=[0.0, 1.0, 0.0], plane_origin=[0.0, y, 0.0])
    except Exception:  # noqa: BLE001 — dejenere kesit
        return np.zeros((0, 2))
    if seg is None or len(seg) == 0:
        return np.zeros((0, 2))
    return np.asarray(seg).reshape(-1, 3)[:, [0, 2]]


def _clusters(pts: np.ndarray, gap: float) -> list[np.ndarray]:
    """2B noktaları mesafe eşiğiyle (gap) bağlı bileşenlere ayırır."""
    if len(pts) == 0:
        return []
    import scipy.sparse as sp
    from scipy.sparse.csgraph import connected_components
    from scipy.spatial import cKDTree

    pairs = cKDTree(pts).query_pairs(gap, output_type="ndarray")
    n = len(pts)
    if len(pairs):
        adj = sp.coo_matrix((np.ones(len(pairs)), (pairs[:, 0], pairs[:, 1])), shape=(n, n))
    else:
        adj = sp.coo_matrix((n, n))
    k, lab = connected_components(adj, directed=False)
    return [pts[lab == i] for i in range(k)]


def _hull_perimeter(pts: np.ndarray) -> float:
    """2B konveks zarf çevresi (mezura ölçüsü); <3 nokta → 0."""
    if len(pts) < 3:
        return 0.0
    from scipy.spatial import ConvexHull

    try:
        hull = ConvexHull(pts, qhull_options="QJ")
    except Exception:  # noqa: BLE001 — düz/dejenere küme
        return 0.0
    return float(hull.area)  # 2B'de "area" = çevre


def _slice_stats(verts: np.ndarray, faces: np.ndarray, y: float, height: float) -> dict:
    """Tek kesit: gövde çevresi, toplam x-açıklığı, bacak/küme bilgisi, ön z."""
    pts = _section_points(verts, faces, y)
    if len(pts) == 0:
        return {"girth": 0.0, "span": 0.0, "n_big": 0, "two_legs": False, "front_z": -1e9,
                "cz": 0.0}
    cls = _clusters(pts, _CLUSTER_GAP * height)
    torso = [c for c in cls if abs(float(c[:, 0].mean())) < _TORSO_X * height]
    tpts = np.concatenate(torso) if torso else np.zeros((0, 2))
    big = [c for c in cls if _hull_perimeter(c) > 0.10 * height]
    left = [c for c in big if float(c[:, 0].max()) < 0.0]
    right = [c for c in big if float(c[:, 0].min()) > 0.0]
    return {
        "girth": _hull_perimeter(tpts),
        "span": float(pts[:, 0].max() - pts[:, 0].min()),
        "n_big": len(big),
        "two_legs": bool(left) and bool(right) and len(big) == len(left) + len(right),
        "front_z": float(tpts[:, 1].max()) if len(tpts) else -1e9,
        "cz": float((tpts[:, 1].max() + tpts[:, 1].min()) / 2) if len(tpts) else 0.0,
    }


def _profile(verts: np.ndarray, faces: np.ndarray) -> tuple[np.ndarray, list[dict], float, float]:
    y0 = float(verts[:, 1].min())
    h = float(verts[:, 1].max()) - y0
    ts = np.arange(_SCAN_LO, _SCAN_HI + 1e-9, _SCAN_STEP)
    stats = [_slice_stats(verts, faces, y0 + t * h, h) for t in ts]
    return ts, stats, y0, h


def detect_levels(verts: np.ndarray, faces: np.ndarray) -> dict[str, float]:
    """Profil taramasıyla anatomik seviyeleri (t ∈ [0,1], boy oranı) bulur."""
    ts, st, _y0, h = _profile(verts, faces)
    girth = np.array([s["girth"] for s in st])
    span = np.array([s["span"] for s in st])

    # Koltuk altı: kesit x-açıklığının ilk kez boyun %35'ini aştığı seviye (kollar
    # kesite girer). 0.55 altını arama (A-pozunda eller kalçaya inmez varsayımı;
    # inerse de el kümeleri |cx| filtresiyle gövde çevresine girmez).
    arm_idx = [i for i, t in enumerate(ts) if t > 0.55 and span[i] > 0.35 * h]
    armpit_t = float(ts[arm_idx[0]]) if arm_idx else 0.78

    # Kasık: aşağıdan yukarı tararken "iki ayrı bacak" düzeninin bittiği ilk seviye.
    crotch_t = 0.45
    seen_legs = False
    for i, t in enumerate(ts):
        if t > 0.62:
            break
        if st[i]["two_legs"]:
            seen_legs = True
        elif seen_legs:
            crotch_t = float(t)
            break

    def band(lo: float, hi: float) -> np.ndarray:
        return np.where((ts >= lo) & (ts <= hi) & (girth > 0))[0]

    # Göğüs: koltuk altının hemen altındaki bantta en öne çıkan seviye.
    b = band(armpit_t - 0.10, armpit_t - 0.015)
    if len(b):
        fz = np.array([st[i]["front_z"] for i in b])
        chest_t = float(ts[b[int(np.argmax(fz))]])
    else:
        chest_t = armpit_t - 0.05
    # Bel: kasık+0.10 ile göğüs-0.04 arası en dar çevre.
    b = band(crotch_t + 0.10, chest_t - 0.04)
    waist_t = float(ts[b[int(np.argmin(girth[b]))]]) if len(b) else (crotch_t + chest_t) / 2
    # Kalça: kasık ile bel arası en geniş çevre.
    b = band(crotch_t, waist_t - 0.02)
    hip_t = float(ts[b[int(np.argmax(girth[b]))]]) if len(b) else crotch_t + 0.05
    # Boyun: koltuk altı üstünde (kollar bittikten sonra) en dar gövde çevresi.
    b = [i for i in band(armpit_t + 0.03, armpit_t + 0.15) if span[i] < 0.35 * h]
    neck_t = float(ts[b[int(np.argmin(girth[b]))]]) if b else armpit_t + 0.07
    return {"crotch": crotch_t, "hip": hip_t, "waist": waist_t, "chest": chest_t,
            "armpit": armpit_t, "neck": neck_t}


def measure_body(verts: np.ndarray, faces: np.ndarray,
                 levels: dict[str, float] | None = None) -> dict[str, Any]:
    """Mesh'in boy/göğüs/bel/kalça ölçülerini cm cinsinden döner (mesh birimi = metre).

    `levels` verilmezse seviyeler mesh'in kendisinden otomatik bulunur (bağımsız
    doğrulama). Döner: `{height_cm, chest_cm, waist_cm, hip_cm, levels}`.
    """
    verts = np.asarray(verts, dtype=float)
    if levels is None:
        levels = detect_levels(verts, faces)
    y0 = float(verts[:, 1].min())
    h = float(verts[:, 1].max()) - y0

    def girth_at(t: float) -> float:
        return _slice_stats(verts, faces, y0 + t * h, h)["girth"]

    # Göğüs için seviye ±1 adım içinde en büyük; bel için en küçük; kalça en büyük
    # (ızgara kuantalamasına karşı küçük yerel arama).
    def local(t: float, fn) -> float:
        vals = [girth_at(t + d) for d in (-_SCAN_STEP, 0.0, _SCAN_STEP)]
        vals = [v for v in vals if v > 0]
        return fn(vals) if vals else 0.0

    return {
        "height_cm": round(h * 100.0, 1),
        "chest_cm": round(local(levels["chest"], max) * 100.0, 1),
        "waist_cm": round(local(levels["waist"], min) * 100.0, 1),
        "hip_cm": round(local(levels["hip"], max) * 100.0, 1),
        "levels": {k: round(v, 4) for k, v in levels.items()},
    }


# --- taban analizi --------------------------------------------------------------
class _Base:
    """Bir taban mankenin önhesaplanmış verisi (seviyeler, merkezler, eksenler)."""

    def __init__(self, path: Path) -> None:
        self.path = path
        mesh = trimesh.load(str(path), force="mesh", process=False)
        if not isinstance(mesh, trimesh.Trimesh) or len(mesh.faces) == 0:
            raise ValueError(f"Taban manken yüklenemedi: {path}")
        self.mesh = mesh
        v = np.asarray(mesh.vertices, dtype=float)
        self.y0 = float(v[:, 1].min())
        self.h = float(v[:, 1].max()) - self.y0
        # Birim yüksekliğe normalize et (taban zaten ~1.0; yine de garanti).
        self.v = (v - [0.0, self.y0, 0.0]) / self.h
        self.v[:, 0] -= (self.v[:, 0].max() + self.v[:, 0].min()) / 2
        self.v[:, 2] -= (self.v[:, 2].max() + self.v[:, 2].min()) / 2
        self.f = np.asarray(mesh.faces)
        self.t = self.v[:, 1]
        self.levels = detect_levels(self.v, self.f)
        ts, st, _y0, _h = _profile(self.v, self.f)
        cz = np.array([s["cz"] for s in st])
        ok = np.array([s["girth"] > 0 for s in st])
        self._cz_t, self._cz_v = ts[ok], cz[ok]
        # Omuz yarı-genişliği: koltuk altının hemen altındaki gövde kesitinin x yarı açıklığı.
        # (koltuk altının 1.5 adım altındaki kesitte x=0'a en yakın küme = gövde).
        a = self.levels["armpit"]
        pts = _section_points(self.v, self.f, a - 3 * _SCAN_STEP)
        cls = _clusters(pts, _CLUSTER_GAP)
        if cls:
            torso = min(cls, key=lambda c: abs(float(c[:, 0].mean())))
            self.shoulder_x = float(np.abs(torso[:, 0]).max())
        else:
            self.shoulder_x = 0.09
        self._leg_axes()
        self._arm_axes()

    def cz(self, t: np.ndarray) -> np.ndarray:
        """Seviyedeki gövde z-merkezi (taranmış profilden enterpolasyon)."""
        return np.interp(t, self._cz_t, self._cz_v)

    def _leg_axes(self) -> None:
        """Kasık altı her bacağın (sol/sağ) seviye bazında x/z merkez hattı."""
        c = self.levels["crotch"]
        bins = np.linspace(0.0, c + 0.04, 40)
        self._leg_bins = (bins[:-1] + bins[1:]) / 2
        self._leg_cx: dict[int, np.ndarray] = {}
        self._leg_cz: dict[int, np.ndarray] = {}
        for side in (-1, 1):
            cx, cz = [], []
            for lo, hi in zip(bins[:-1], bins[1:]):
                m = (self.t >= lo) & (self.t < hi) & (np.sign(self.v[:, 0]) == side)
                if m.sum() >= 3:
                    cx.append(float(self.v[m, 0].mean()))
                    cz.append(float(self.v[m, 2].mean()))
                else:
                    cx.append(np.nan)
                    cz.append(np.nan)
            cx_a, cz_a = np.array(cx), np.array(cz)
            good = ~np.isnan(cx_a)
            idx = np.arange(len(cx_a))
            cx_a = np.interp(idx, idx[good], cx_a[good])
            cz_a = np.interp(idx, idx[good], cz_a[good])
            k = np.array([0.25, 0.5, 0.25])  # hafif yumuşatma
            cx_a = np.convolve(np.pad(cx_a, 1, mode="edge"), k, mode="valid")
            cz_a = np.convolve(np.pad(cz_a, 1, mode="edge"), k, mode="valid")
            self._leg_cx[side], self._leg_cz[side] = cx_a, cz_a

    def leg_center(self, t: np.ndarray, x: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        cx = np.where(x < 0, np.interp(t, self._leg_bins, self._leg_cx[-1]),
                      np.interp(t, self._leg_bins, self._leg_cx[1]))
        cz = np.where(x < 0, np.interp(t, self._leg_bins, self._leg_cz[-1]),
                      np.interp(t, self._leg_bins, self._leg_cz[1]))
        return cx, cz

    def _arm_axes(self) -> None:
        """Kolların |x| boyunca (y, z) merkez hattı (omuzdan ele)."""
        a = self.levels["armpit"]
        arm = (np.abs(self.v[:, 0]) > self.shoulder_x) & (self.t > a - 0.04)
        ax = np.abs(self.v[arm, 0])
        xmax = float(ax.max()) if len(ax) else self.shoulder_x + 0.3
        bins = np.linspace(self.shoulder_x, xmax + 1e-6, 30)
        self._arm_bins = (bins[:-1] + bins[1:]) / 2
        cy, cz = [], []
        for lo, hi in zip(bins[:-1], bins[1:]):
            m = arm & (np.abs(self.v[:, 0]) >= lo) & (np.abs(self.v[:, 0]) < hi)
            cy.append(float(self.v[m, 1].mean()) if m.sum() >= 3 else np.nan)
            cz.append(float(self.v[m, 2].mean()) if m.sum() >= 3 else np.nan)
        cy_a, cz_a = np.array(cy), np.array(cz)
        good = ~np.isnan(cy_a)
        idx = np.arange(len(cy_a))
        if good.any():
            cy_a = np.interp(idx, idx[good], cy_a[good])
            cz_a = np.interp(idx, idx[good], cz_a[good])
        else:
            cy_a = np.full(len(idx), a)
            cz_a = np.zeros(len(idx))
        self._arm_cy, self._arm_cz = cy_a, cz_a

    def arm_center(self, ax: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        return (np.interp(ax, self._arm_bins, self._arm_cy),
                np.interp(ax, self._arm_bins, self._arm_cz))


@lru_cache(maxsize=4)
def _load_base(path_str: str, _mtime: float) -> _Base:
    return _Base(Path(path_str))


def load_base(path: Path) -> _Base:
    return _load_base(str(path), path.stat().st_mtime)


# --- morf ------------------------------------------------------------------------
def _smoothstep(e0: float, e1: float, x: np.ndarray) -> np.ndarray:
    u = np.clip((x - e0) / max(e1 - e0, 1e-9), 0.0, 1.0)
    return u * u * (3 - 2 * u)


def _morph(base: _Base, height_m: float, s_chest: float, s_waist: float,
           s_hip: float) -> np.ndarray:
    """Taban (birim boy) vertislerini faktörlerle morflar → metre cinsinden vertisler."""
    from scipy.interpolate import PchipInterpolator

    lv = base.levels
    v = base.v
    t, x, y, z = v[:, 1], v[:, 0], v[:, 1], v[:, 2]

    # Gövde ölçek profili s(t) — PCHIP aşma yapmaz (düğümler arası tuhaf şişme yok).
    s_sh = 1 + (s_chest - 1) * 0.8
    s_neck = 1 + (s_chest - 1) * 0.35
    knots = [
        (lv["crotch"] - 0.06, s_hip), (lv["crotch"], s_hip), (lv["hip"], s_hip),
        (lv["waist"], s_waist), (lv["chest"], s_chest), (lv["armpit"], s_chest),
        (lv["armpit"] + 0.03, s_sh), (lv["neck"], s_neck), (lv["neck"] + 0.04, 1.0),
        (1.01, 1.0),
    ]
    knots.sort()
    kt, ks = [], []
    for kx, kv in knots:  # PCHIP kesin artan düğüm ister
        if kt and kx <= kt[-1] + 1e-4:
            continue
        kt.append(kx)
        ks.append(kv)
    prof = PchipInterpolator(np.array(kt), np.array(ks), extrapolate=False)
    s = prof(np.clip(t, kt[0], kt[-1]))

    # 1) Gövde formülü: x eksen etrafında, z seviyenin gövde merkezi etrafında.
    cz = base.cz(t)
    xt = s * x
    zt = cz + s * (z - cz)
    yt = y.copy()

    # 2) Kol formülü: omuz genişlemesi kadar öteleme + kalınlık (kol ekseni etrafında).
    sx = base.shoulder_x
    s_arm_root = float(prof(np.clip(lv["armpit"], kt[0], kt[-1])))
    ax = np.abs(x)
    acy, acz = base.arm_center(ax)
    t_arm = 1 + (s_chest - 1) * 0.5
    w_thick = _smoothstep(sx, sx + 0.06, ax)
    k_arm = 1 + (t_arm - 1) * w_thick
    xa = x + np.sign(x) * (s_arm_root - 1) * sx
    ya = acy + k_arm * (y - acy)
    za = acz + k_arm * (z - acz)
    w_arm = _smoothstep(sx, sx + 0.04, ax) * _smoothstep(lv["armpit"] - 0.03, lv["armpit"], t)

    # 3) Bacak formülü: her bacak kendi ekseni etrafında; aralık kalça oranıyla açılır.
    lcx, lcz = base.leg_center(t, x)
    k_ankle = 1 + (s_hip - 1) * 0.3
    u = np.clip(t / max(lv["crotch"], 1e-6), 0.0, 1.0)  # 0=taban, 1=kasık
    k_leg = k_ankle + (s_hip - k_ankle) * _smoothstep(0.0, 1.0, u)
    cz0 = base.cz(np.full_like(t, lv["crotch"]))
    xl = s_hip * lcx + k_leg * (x - lcx)
    zl = cz0 + s_hip * (lcz - cz0) + k_leg * (z - lcz)
    w_leg = 1 - _smoothstep(lv["crotch"] - 0.03, lv["crotch"] + 0.02, t)

    # Harmanla: bacak bölgesi → bacak; kol bölgesi → kol; kalan → gövde.
    xb = (1 - w_leg) * xt + w_leg * xl
    zb = (1 - w_leg) * zt + w_leg * zl
    xo = (1 - w_arm) * xb + w_arm * xa
    yo = (1 - w_arm) * yt + w_arm * ya
    zo = (1 - w_arm) * zb + w_arm * za

    out = np.stack([xo, yo, zo], axis=1) * height_m
    out[:, 1] -= out[:, 1].min()  # ayak tabanı y=0
    return out


def morph_to_measurements(base_path: Path, height_cm: float, chest_cm: float,
                          waist_cm: float, hip_cm: float,
                          iterations: int = 6) -> tuple[trimesh.Trimesh, dict]:
    """Taban mankeni hedef ölçülere morflar; ölç→düzelt iterasyonu yapar (en çok `iterations` tur).

    Döner: (metre cinsinden yeni Trimesh — taban görsel/UV korunur, rapor dict).
    Rapor: `{measured:{...cm}, factors:{chest,waist,hip}, iterations, base_levels}`.
    """
    base = load_base(base_path)
    h_m = height_cm / 100.0
    target = {"chest_cm": chest_cm, "waist_cm": waist_cm, "hip_cm": hip_cm}
    key_of = {"chest_cm": "chest", "waist_cm": "waist", "hip_cm": "hip"}

    # Başlangıç: taban (hedef boya ölçeklenmiş) ölçüsüne göre ilk tahmin.
    base_meas = measure_body(base.v * h_m, base.f, levels=base.levels)
    fac = {k: float(np.clip(target[k] / max(base_meas[k], 1e-6), _FACTOR_MIN, _FACTOR_MAX))
           for k in target}
    best: tuple[float, np.ndarray, dict, dict] | None = None
    done = 0
    for i in range(max(1, iterations)):
        verts = _morph(base, h_m, fac["chest_cm"], fac["waist_cm"], fac["hip_cm"])
        # Ölçüm seviyeleri her turda morflanmış mesh'ten YENİDEN bulunur (bel/kalça
        # seviyesi kayabilir) → raporlanan ölçü = mezuranın göreceği ölçü.
        meas = measure_body(verts, base.f)
        done += 1
        err = max(abs(meas[k] - target[k]) / target[k] for k in target)
        if best is None or err < best[0]:
            best = (err, verts, meas, dict(fac))
        if err < 0.005:
            break
        # Sönümlü düzeltme (ilk tur tam, sonrakiler ^0.8): uç bedenlerde seviye
        # tespiti turdan tura kayınca salınımı bastırır.
        damp = 1.0 if i == 0 else 0.8
        for k in target:
            if meas[k] > 0:
                fac[k] = float(np.clip(fac[k] * (target[k] / meas[k]) ** damp,
                                       _FACTOR_MIN, _FACTOR_MAX))
    # En iyi tur döner (son tur değil — salınımda en yakın sonuç korunur).
    _err, verts, meas, fac = best
    out = base.mesh.copy()
    out.vertices = verts
    measured = {k: meas[k] for k in ("height_cm", "chest_cm", "waist_cm", "hip_cm")}
    report = {
        "measured": measured,
        "factors": {key_of[k]: round(v, 4) for k, v in fac.items()},
        "iterations": done,
        "levels": meas["levels"],
        "base_levels": {k: round(v, 4) for k, v in base.levels.items()},
    }
    return out, report


def within_tolerance(measured: dict, body: dict, tol: float = TOLERANCE) -> dict[str, bool]:
    """Her ölçü için |ölçülen-hedef|/hedef ≤ tol mu?"""
    return {k: abs(float(measured[k]) - float(body[k])) / float(body[k]) <= tol
            for k in ("height_cm", "chest_cm", "waist_cm", "hip_cm")}


def export_glb(mesh: trimesh.Trimesh, out_path: Path) -> None:
    """Morflanmış manken'i GLB yazar (atomik: tmp → rename)."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = out_path.with_suffix(".glb.tmp")
    data = trimesh.Scene(mesh).export(file_type="glb")
    tmp.write_bytes(data)
    tmp.replace(out_path)


def manifest_json(entries: list[dict]) -> str:
    return json.dumps(entries, ensure_ascii=False, indent=2)


if __name__ == "__main__":  # elle hızlı deneme: python -m common.body_morph f 165 88 70 96
    import sys

    g, hh, cc, ww, pp = sys.argv[1:6]
    root = Path(__file__).resolve().parents[4] / "data" / "templates" / "mannequins"
    bp = root / f"{BASE_BY_GENDER['female' if g.startswith('f') else 'male']}.glb"
    _m, rep = morph_to_measurements(bp, float(hh), float(cc), float(ww), float(pp))
    print(json.dumps(rep, ensure_ascii=False, indent=2))
    if len(sys.argv) > 6:
        export_glb(_m, Path(sys.argv[6]))
