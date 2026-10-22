"""Giydirilmiş kıyafetin TERZİ ÖLÇÜLERİ (cm) + bedenle karşılaştırma (bolluk payı).

Kıyafet bir mankene giydirildiğinde gerçek ölçek bilinir: mankenin gerçek boyu (özel
mankende ölçülerden, taban mankende varsayılan boy) ↔ kıyafet çerçevesindeki boyu →
cm/birim. Ölçüler:

- Üst giyim: göğüs, bel, etek ucu çevresi; omuzdan eteğe boy; kol boyu; kol ağzı çevresi.
- Alt giyim: bel, kalça, etek/paça ucu çevresi; boy.

Çevre = o yükseklikteki kesitin dış zarfının (2B dışbükey örtü) çevresi — çift kabuklu
üretilmiş kıyafetlerde iç kabuk sonucu bozmaz. Kesitte kol/kolluk noktaları ayrılır: her
kıyafet noktası pozlu mankenin en yakın parçasına (kol mu gövde mi) atanır.
"""
from __future__ import annotations

from typing import Any

import numpy as np

LABELS_TR = {
    "chest": "Göğüs çevresi", "waist": "Bel çevresi", "hip": "Kalça çevresi",
    "hem": "Etek ucu çevresi", "length": "Boy", "sleeve_length": "Kol boyu",
    "cuff": "Kol ağzı çevresi",
}


def _perimeter(xz: np.ndarray) -> float:
    if len(xz) < 3:
        return 0.0
    from scipy.spatial import ConvexHull
    try:
        h = ConvexHull(xz)
    except Exception:  # noqa: BLE001 — dejenere kesit
        return 0.0
    p = xz[h.vertices]
    return float(np.linalg.norm(np.diff(np.vstack([p, p[:1]]), axis=0), axis=1).sum())


def measure(garment: np.ndarray, body: np.ndarray, arm_mask: np.ndarray, lm: dict,
            s: float, pos: np.ndarray, height_m: float, garment_type: str,
            arm_dirs: dict[int, np.ndarray]) -> dict[str, Any]:
    """garment: giydirilmiş kıyafet köşeleri (kıyafet çerçevesi); body: pozlu manken
    (kıyafet çerçevesi); arm_mask: body köşelerinde kol maskesi."""
    from scipy.spatial import cKDTree
    g = np.asarray(garment, float)
    cm = (height_m * 100.0) / (lm["H"] * s)                  # cm / kıyafet birimi
    lvl = {k: y * s + pos[1] for k, y in lm["levels"].items()}
    band = 0.012 * lm["H"] * s
    tree = cKDTree(body)
    _, nb = tree.query(g)
    on_arm = arm_mask[nb]
    body_arm = arm_mask

    def girth(y: float, pts: np.ndarray) -> float:
        sl = pts[np.abs(pts[:, 1] - y) < band]
        return _perimeter(sl[:, [0, 2]]) * cm

    torso_g = g[~on_arm]
    torso_b = body[~body_arm]
    out: dict[str, Any] = {}
    rows = []

    def add(key: str, garment_cm: float, body_cm: float | None = None) -> None:
        if garment_cm <= 0:
            return
        r = {"key": key, "label_tr": LABELS_TR[key], "garment_cm": round(float(garment_cm), 1)}
        if body_cm and body_cm > 0:
            r["body_cm"] = round(float(body_cm), 1)
            r["ease_cm"] = round(float(garment_cm - body_cm), 1)
        rows.append(r)

    # Etek ucu/boy gövde noktalarından (sarkan kolluk ağzı eteğin altına inebilir).
    bottom = float(torso_g[:, 1].min()) if len(torso_g) else float(g[:, 1].min())
    hem_y = bottom + 0.015 * lm["H"] * s
    if garment_type in ("pants", "skirt"):
        top = float(torso_g[:, 1].max()) if len(torso_g) else float(g[:, 1].max())
        add("waist", girth(top - 0.015 * lm["H"] * s, torso_g), girth(lvl["waist"], torso_b))
        if lvl["hip"] > bottom:
            add("hip", girth(lvl["hip"], torso_g), girth(lvl["hip"], torso_b))
        add("hem", girth(hem_y, torso_g))
        add("length", (top - bottom) * cm)
    else:
        if lvl["chest"] > bottom:
            add("chest", girth(lvl["chest"], torso_g), girth(lvl["chest"], torso_b))
        if lvl["waist"] > bottom:
            add("waist", girth(lvl["waist"], torso_g), girth(lvl["waist"], torso_b))
        add("hem", girth(hem_y, torso_g))
        shoulder = lm["shoulder_y"] * s + pos[1]
        add("length", (shoulder - bottom) * cm)
        # Kol: omuz ekleminden kolluk ucuna (kol ekseni üzerindeki en uzak kolluk noktası).
        sleeves = g[on_arm]
        lens, cuffs = [], []
        for side, d in arm_dirs.items():
            sp = sleeves[np.sign(sleeves[:, 0]) == side]
            if len(sp) < 20:
                continue
            piv = np.array([side * lm["shoulder_x"], lm["arm_cy"], lm["arm_cz"]]) * s + pos
            t = (sp - piv) @ d
            tmax = float(np.quantile(t, 0.99))
            lens.append(tmax * cm)
            end = sp[t > tmax - 0.03 * lm["H"] * s]
            if len(end) >= 6:
                a = d / np.linalg.norm(d)
                u = np.cross(a, [0.0, 0.0, 1.0] if abs(a[2]) < 0.9 else [1.0, 0.0, 0.0])
                u /= np.linalg.norm(u)
                w = np.cross(a, u)
                cuffs.append(_perimeter(np.column_stack([(end - piv) @ u, (end - piv) @ w])) * cm)
        if lens:
            add("sleeve_length", float(np.mean(lens)))
        if cuffs:
            add("cuff", float(np.mean(cuffs)))
    out["rows"] = rows
    out["cm_per_unit"] = round(cm, 4)
    out["height_cm"] = round(height_m * 100, 1)
    return out
