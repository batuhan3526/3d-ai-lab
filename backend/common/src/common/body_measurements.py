"""Basit 5 ölçüden FreeSewing ölçü setine (mm) tahminci — F1.

Arayüz yalnızca 5 alan ister:
    {"gender": "female"|"male", "height_cm", "chest_cm", "waist_cm", "hip_cm"}
FreeSewing tasarımları ise ~35 ölçü ister (neck, biceps, shoulderSlope,
hpsToWaistBack, waistToHips, inseam, crossSeam ...). Bu modül eksikleri
FreeSewing'in kendi ortalama yetişkin ölçü tablosundan (`@freesewing/models`,
`neckstimate.mjs` — MIT) oranlayarak tahmin eder:

* Çevre ölçüleri (göğüs/bel/basen) doğrudan kullanıcıdan gelir.
  `hips` (FreeSewing'de bel ile basen arası "üst kalça") bel ve basenden
  tabloda yer aldığı oranla ara-değerlenir; kullanıcının "basen"i = `seat`.
* Üst gövde çevre/arkları (boyun, pazu, bilek, baş, göğüs-üstü ...) göğüs
  çarpanıyla, alt gövde çevreleri (uyluk, diz, bilek) basen çarpanıyla
  FreeSewing'in `neckstimate` düzeltme oranları kullanılarak ölçeklenir
  (çevre ölçüsü büyüdüğünde boyun aynı oranda büyümez → oran<1).
* Dikey ölçüler (omuz→bel, bel→yer, iç bacak ...) boy çarpanıyla ölçeklenir.
* `shoulderSlope` derecedir, ölçeklenmez.

Bu bir TAHMİNDİR — gerçek terzi ölçüsünün yerini tutmaz; kullanıcı istediği
ölçüyü `measurements` ile ezebilir (gateway önce tahmini, üstüne verilenleri
uygular).
"""
from __future__ import annotations

from typing import Any

# FreeSewing neckstimate tabanı: [kadın, erkek] — mm (shoulderSlope derece).
# Kaynak: @freesewing/models@4.10.2 src/neckstimate.mjs (MIT).
_BASE: dict[str, tuple[float, float]] = {
    "ankle": (245, 235),
    "biceps": (270, 350),
    "bustFront": (480, 560),
    "bustPointToUnderbust": (100, 60),
    "bustSpan": (160, 190),
    "chest": (925, 1000),
    "crossSeam": (740, 870),
    "crossSeamFront": (370, 410),
    "crotchDepth": (270, 340),
    "heel": (315, 360),
    "head": (565, 590),
    "highBust": (865, 1030),
    "highBustFront": (440, 570),
    "hips": (900, 840),
    "hpsToBust": (275, 280),
    "hpsToWaistBack": (395, 470),
    "hpsToWaistFront": (400, 460),
    "inseam": (765, 780),
    "knee": (380, 410),
    "neck": (340, 380),
    "seat": (1010, 1020),
    "seatBack": (520, 560),
    "shoulderSlope": (13, 13),
    "shoulderToElbow": (340, 360),
    "shoulderToShoulder": (415, 450),
    "shoulderToWrist": (590, 630),
    "underbust": (780, 980),
    "upperLeg": (570, 625),
    "waist": (750, 810),
    "waistBack": (380, 410),
    "waistToArmpit": (170, 210),
    "waistToFloor": (1050, 1160),
    "waistToHips": (125, 130),
    "waistToKnee": (600, 640),
    "waistToSeat": (250, 270),
    "waistToUnderbust": (80, 55),
    "waistToUpperLeg": (285, 340),
    "wrist": (165, 175),
}

# Tablonun temsil ettiği boy (mm) — waistToFloor + hpsToWaistBack + baş/boyun
# payından türetilmiş yaklaşık değer (FreeSewing boy ölçüsü tutmaz).
_BASE_HEIGHT = {"female": 1680.0, "male": 1800.0}

# neckstimate düzeltme oranları (çevre büyüdükçe ölçünün ne kadarı büyür).
_RATIO = {
    "bustFront": 0.5, "bustPointToUnderbust": 0.5, "bustSpan": 0.5, "highBustFront": 0.5,
    "ankle": 1.0, "biceps": 1.0, "highBust": 1.0, "neck": 1.0, "underbust": 1.0,
    "head": 0.35, "heel": 0.25, "knee": 0.65, "upperLeg": 0.45, "wrist": 0.5,
    "shoulderToShoulder": 0.65, "crossSeam": 0.6, "crossSeamFront": 0.6, "seatBack": 0.6,
}

# Göğüs çarpanıyla ölçeklenen üst gövde ölçüleri.
_UPPER = ("neck", "biceps", "wrist", "head", "highBust", "highBustFront", "underbust",
          "bustFront", "bustSpan", "bustPointToUnderbust", "shoulderToShoulder")
# Basen çarpanıyla ölçeklenen alt gövde ölçüleri.
_LOWER = ("upperLeg", "knee", "ankle", "heel")
# Boy çarpanıyla doğrudan ölçeklenen dikey ölçüler.
_VERTICAL = ("hpsToBust", "hpsToWaistBack", "hpsToWaistFront", "waistToArmpit", "waistToHips",
             "waistToKnee", "waistToSeat", "waistToUnderbust", "waistToUpperLeg", "crotchDepth",
             "inseam", "waistToFloor", "shoulderToElbow", "shoulderToWrist")

# Kabul edilen aralıklar (cm) — dışındakiler büyük olasılıkla yazım hatası.
LIMITS_CM = {
    "height_cm": (120.0, 220.0),
    "chest_cm": (60.0, 170.0),
    "waist_cm": (45.0, 170.0),
    "hip_cm": (60.0, 180.0),
}
_FIELD_TR = {"height_cm": "Boy", "chest_cm": "Göğüs", "waist_cm": "Bel", "hip_cm": "Basen"}


class MeasurementError(ValueError):
    """Kullanıcıya gösterilebilir (Türkçe) ölçü hatası."""


def _scale(base: float, factor: float, ratio: float) -> float:
    """neckstimate formülü: base + (factor·base − base)·ratio."""
    return base + (factor * base - base) * ratio


def validate_simple(body: dict[str, Any]) -> dict[str, Any]:
    """5 alanlı basit ölçüyü doğrula; temiz kopya döner, hatada MeasurementError."""
    if not isinstance(body, dict):
        raise MeasurementError("Ölçüler eksik: cinsiyet, boy, göğüs, bel ve basen gerekli.")
    gender = str(body.get("gender", "")).strip().lower()
    if gender in ("kadin", "kadın", "k", "f", "woman"):
        gender = "female"
    if gender in ("erkek", "e", "m", "man"):
        gender = "male"
    if gender not in ("female", "male"):
        raise MeasurementError("Cinsiyet 'kadın' (female) ya da 'erkek' (male) olmalı.")
    out: dict[str, Any] = {"gender": gender}
    for key, (lo, hi) in LIMITS_CM.items():
        raw = body.get(key)
        if raw is None or raw == "":
            raise MeasurementError(f"{_FIELD_TR[key]} ölçüsü eksik (cm olarak girin).")
        try:
            val = float(raw)
        except (TypeError, ValueError):
            raise MeasurementError(f"{_FIELD_TR[key]} ölçüsü sayı olmalı (cm).") from None
        if not (lo <= val <= hi):
            raise MeasurementError(
                f"{_FIELD_TR[key]} ölçüsü {val:g} cm olamaz; {lo:g}–{hi:g} cm arasında olmalı."
            )
        out[key] = val
    return out


def estimate_measurements(body: dict[str, Any]) -> dict[str, float]:
    """5 basit alandan FreeSewing'in tüm ölçülerini (mm, shoulderSlope derece) tahmin et."""
    b = validate_simple(body)
    gi = 0 if b["gender"] == "female" else 1
    base = {k: float(v[gi]) for k, v in _BASE.items()}

    chest = b["chest_cm"] * 10.0
    waist = b["waist_cm"] * 10.0
    seat = b["hip_cm"] * 10.0
    height = b["height_cm"] * 10.0

    f_chest = chest / base["chest"]
    f_seat = seat / base["seat"]
    f_h = height / _BASE_HEIGHT[b["gender"]]

    m: dict[str, float] = {}
    for k in _UPPER:
        m[k] = _scale(base[k], f_chest, _RATIO.get(k, 1.0))
    for k in _LOWER:
        m[k] = _scale(base[k], f_seat, _RATIO.get(k, 1.0))
    for k in _VERTICAL:
        m[k] = base[k] * f_h

    m["chest"] = chest
    m["waist"] = waist
    m["seat"] = seat
    # hips: bel ile basen arasında, tablodaki konumuna göre ara-değer.
    span = base["seat"] - base["waist"]
    t = (base["hips"] - base["waist"]) / span if span else 0.5
    m["hips"] = waist + (seat - waist) * t
    # Bel/basen arka yarıları — tablodaki oranı korur.
    m["waistBack"] = waist * base["waistBack"] / base["waist"]
    m["seatBack"] = seat * base["seatBack"] / base["seat"]
    # Ağ (kasık) ölçüleri hem basene hem boya bağlı.
    for k in ("crossSeam", "crossSeamFront"):
        m[k] = _scale(base[k], f_seat, _RATIO[k]) * (1.0 + (f_h - 1.0) * 0.5)
    # Göğüs-üstü ve göğüs-altı göğüsten büyük/küçük olamaz (tutarlılık).
    if b["gender"] == "female":
        m["highBust"] = min(m["highBust"], chest * 0.995)
        m["underbust"] = min(m["underbust"], chest * 0.97)
    m["shoulderSlope"] = base["shoulderSlope"]
    # Pazu çevresi kol için mantıklı aralıkta kalsın.
    m["biceps"] = max(m["biceps"], 200.0)
    return {k: round(v, 1) for k, v in sorted(m.items())}
