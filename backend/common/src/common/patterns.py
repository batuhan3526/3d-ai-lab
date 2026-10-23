"""FreeSewing tabanlı parametrik dikiş kalıbı — F1.

Akış: tasarım + ölçü (mm) + opsiyon → `backend/services/freesewing/draft.mjs`
(Node, @freesewing/* v4.10.2, MIT) → parça poligonları → bu modül:

* `pieces.json` (ORTAK SÖZLEŞME): her parça için dikiş çizgisi (`seam_line`, payı
  yok) + kesim çizgisi (`cut_line`, paylı), düz boy açısı, kenarlar (`edges`)
  ve tasarım bazında 3D dikiş eşlemesi (`seams`).
* `pattern.svg` — 1:1 mm ölçekli (width/height "mm"), sol üstte 10 cm
  kalibrasyon karesi; A4'te %100 ölçekle basılınca doğru boy.
* `pattern.pdf` — `common.sewing.svg_to_pdf_tiles` ile A4 karolar.
* `freesewing.svg` — FreeSewing'in kendi (İngilizce etiketli) çıktısı, referans.
* `meta.json` — tasarım, ölçüler, opsiyonlar, katlama kenarları, uyarılar.

Koordinat çerçevesi (pieces.json): mm, **y YUKARI** (FreeSewing/SVG y-aşağı
çerçevesinden çevrilir), her parça kendi kesim-çizgisi sınır kutusunun sol-alt
köşesi (0,0) olacak şekilde ötelenir; poligonlar CCW (shoelace alanı > 0).
`edges[].from/to` `seam_line` indeksleridir; polyline indeks artış yönünde
(sondan başa sararak) from→to izlenir.

Dikiş eşlemesi (`seams`): `{"a","b","reverse"}` — a kenarı b kenarına dikilir;
`reverse=true` ise a'nın başı b'nin SONUNA denk gelir. `a == b` ise kenar, o
parçanın ayna kopyasıyla dikilir (mirror=true katlı parçalarda katlamanın öbür
yarısı; quantity=2 parçalarda sağ/sol çiftin öbürü — ör. kol altı değil, arka
orta dikişi). Yalnız `sew3d: true` tasarımlarda dolu, diğerlerinde [].
"""
from __future__ import annotations

import json
import math
import os
import shutil
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from common.config import get_settings

# --- yollar --------------------------------------------------------------------
# patterns.py: backend/common/src/common/patterns.py → parents[3] = backend/
_BACKEND = Path(__file__).resolve().parents[3]
FREESEWING_DIR = Path(os.getenv("FREESEWING_DIR", str(_BACKEND / "services" / "freesewing")))
DRAFT_SCRIPT = FREESEWING_DIR / "draft.mjs"
NODE_TIMEOUT_S = float(os.getenv("FREESEWING_TIMEOUT_S", "60"))


class PatternError(Exception):
    """Kullanıcıya gösterilebilir (Türkçe) kalıp hatası. `status` HTTP kodu önerisi."""

    def __init__(self, message: str, status: int = 422):
        super().__init__(message)
        self.status = status


def patterns_dir() -> Path:
    """Kalıp veri kökü: `PATTERNS_DIR` env ya da `<projects_dir>/../patterns`.

    projects_dir'den türetmek testlerde (PROJECTS_DIR=tmp) izolasyonu bedavaya
    getirir; üretimde `data/patterns/` olur.
    """
    env = os.getenv("PATTERNS_DIR")
    if env:
        return Path(env)
    return Path(get_settings().projects_dir).parent / "patterns"


def pattern_path(pattern_id: str) -> Path:
    """Doğrulanmış kalıp dizini (yol kaçışına karşı yalnız hex/uuid id)."""
    pid = str(pattern_id)
    if not pid or len(pid) > 64 or not all(c in "0123456789abcdef-" for c in pid):
        raise PatternError("Kalıp bulunamadı", status=404)
    return patterns_dir() / pid


def node_bin() -> str:
    """Node yürütücüsü: `NODE_BIN` env → PATH."""
    env = os.getenv("NODE_BIN")
    if env:
        return env
    return shutil.which("node") or "node"


# --- katalog -------------------------------------------------------------------
# Opsiyon şeması: {"id","label_tr","default","choices":[{"id","label_tr","set":{fs_opt: değer}}]}
# FreeSewing pct opsiyonları KESİR olarak verilir (0.12 = %12).
def _fit(opt: str, dar: float, normal: float, bol: float, extra: dict | None = None) -> dict:
    extra = extra or {}
    return {
        "id": "fit", "label_tr": "Kesim", "default": "normal",
        "choices": [
            {"id": "dar", "label_tr": "Dar", "set": {opt: dar, **extra.get("dar", {})}},
            {"id": "normal", "label_tr": "Normal", "set": {opt: normal, **extra.get("normal", {})}},
            {"id": "bol", "label_tr": "Bol", "set": {opt: bol, **extra.get("bol", {})}},
        ],
    }


def _length(opt: str, kisa: float, normal: float, uzun: float, label: str = "Boy") -> dict:
    return {
        "id": "length", "label_tr": label, "default": "normal",
        "choices": [
            {"id": "kisa", "label_tr": "Kısa", "set": {opt: kisa}},
            {"id": "normal", "label_tr": "Normal", "set": {opt: normal}},
            {"id": "uzun", "label_tr": "Uzun", "set": {opt: uzun}},
        ],
    }


def _bool(oid: str, label: str, opt: str, default: bool, yes: str = "Evet", no: str = "Hayır") -> dict:
    return {
        "id": oid, "label_tr": label, "default": "evet" if default else "hayir",
        "choices": [
            {"id": "evet", "label_tr": yes, "set": {opt: True}},
            {"id": "hayir", "label_tr": no, "set": {opt: False}},
        ],
    }


# Kenar tanımı: (parça, kenar_adı, başlangıç_noktası, bitiş_noktası) — FreeSewing
# adlandırılmış noktaları; başlangıç→bitiş FreeSewing seam poligonunun sırasıyla
# aynı yönde olmalı. Bitiş bir liste ise ilk bulunan kullanılır (opsiyona bağlı noktalar).
# Dikiş tanımı: (a, b, reverse) — reverse FreeSewing çerçevesindeki yönlere göre.
_TEAGAN_EDGES = [
    ("front", "hem", "cfHem", "hem"),
    ("front", "side", "hem", "armhole"),
    ("front", "armhole", "armhole", "shoulder"),
    ("front", "shoulder", "shoulder", "neck"),
    ("front", "neck", "neck", "cfNeck"),
    ("front", "cf", "cfNeck", "cfHem"),
    ("back", "hem", "cfHem", "hem"),
    ("back", "side", "hem", "armhole"),
    ("back", "armhole", "armhole", "shoulder"),
    ("back", "shoulder", "shoulder", "neck"),
    ("back", "neck", "neck", "cbNeck"),
    ("back", "cb", "cbNeck", "cfHem"),
    ("sleeve", "hem", "hemLeft", "hemRight"),
    ("sleeve", "underarm_front", "hemRight", "bicepsRight"),
    ("sleeve", "cap_front", "bicepsRight", "__capSplit"),
    ("sleeve", "cap_back", "__capSplit", "bicepsLeft"),
    ("sleeve", "underarm_back", "bicepsLeft", "hemLeft"),
]
_TEAGAN_SEAMS = [
    ("front.side", "back.side", False),           # yan dikiş
    ("front.shoulder", "back.shoulder", False),   # omuz
    ("front.armhole", "sleeve.cap_front", False), # kol takma (ön): koltuk altı↔koltuk altı
    ("back.armhole", "sleeve.cap_back", True),    # kol takma (arka)
    ("sleeve.underarm_front", "sleeve.underarm_back", True),  # kol altı: etek↔etek
]
_PENELOPE_EDGES = [
    ("front", "cf", "lWaist", "lHem"),
    ("front", "hem", "lHem", "rHem"),
    ("front", "side", "rHem", "rWaist"),
    ("back", "cb", "lWaist", ["lVent", "lHem"]),
    ("back", "side", "rHem", "rWaist"),
]
_PENELOPE_SEAMS = [
    ("front.side", "back.side", False),  # yan dikiş
    ("back.cb", "back.cb", False),        # arka orta (sağ/sol arka çifti; fermuar/yırtmaç üstü)
]
_SANDY_EDGES = [
    ("skirt", "hem", "ex2Flipped", "ex2"),
    ("skirt", "cb", "ex2", "in2"),
    ("skirt", "waist", "in2", "in2Flipped"),
    ("skirt", "cf", "in2Flipped", "ex2Flipped"),
]
_SANDY_SEAMS = [
    ("skirt.cb", "skirt.cb", False),  # arka orta: katlı parçanın iki ucu birleşir
]

CATALOG: list[dict[str, Any]] = [
    {
        "id": "teagan", "label_tr": "Tişört", "category": "ust", "category_tr": "Üst giyim",
        "description_tr": "Bisiklet yaka, kısa kollu basit tişört. Esnek örme kumaş için.",
        "gender": "unisex", "difficulty": 1, "sew3d": True,
        "edges": _TEAGAN_EDGES, "seams": _TEAGAN_SEAMS,
        "options": [
            _fit("chestEase", 0.06, 0.12, 0.20, {"dar": {"hipsEase": 0.12}, "normal": {"hipsEase": 0.18}, "bol": {"hipsEase": 0.26}}),
            _length("lengthBonus", 0.0, 0.15, 0.30),
            {"id": "sleeve", "label_tr": "Kol boyu", "default": "kisa", "choices": [
                {"id": "kisa", "label_tr": "Kısa kol", "set": {"sleeveLength": 0.30}},
                {"id": "yarim", "label_tr": "Yarım kol", "set": {"sleeveLength": 0.55}},
                {"id": "uzun", "label_tr": "Uzun kol", "set": {"sleeveLength": 1.0}},
            ]},
        ],
    },
    {
        "id": "aaron", "label_tr": "Atlet", "category": "ust", "category_tr": "Üst giyim",
        "description_tr": "Kolsuz atlet, yaka ve kol ağzı biyeli. Esnek örme kumaş için.",
        "gender": "unisex", "difficulty": 1, "sew3d": False,
        "options": [_fit("chestEase", 0.02, 0.08, 0.15), _length("lengthBonus", 0.0, 0.10, 0.25)],
    },
    {
        "id": "sven", "label_tr": "Sweatshirt", "category": "ust", "category_tr": "Üst giyim",
        "description_tr": "Uzun kollu, ribanalı klasik sweatshirt.",
        "gender": "unisex", "difficulty": 2, "sew3d": False,
        "options": [
            _fit("chestEase", 0.08, 0.15, 0.25),
            _length("lengthBonus", 0.05, 0.15, 0.25),
            _bool("ribbing", "Etek ve manşet ribanası", "ribbing", True, "Var", "Yok"),
        ],
    },
    {
        "id": "hugo", "label_tr": "Kapüşonlu sweatshirt", "category": "ust", "category_tr": "Üst giyim",
        "description_tr": "Reglan kollu, kanguru cepli kapüşonlu sweatshirt.",
        "gender": "unisex", "difficulty": 3, "sew3d": False,
        "options": [_fit("chestEase", 0.05, 0.08, 0.14), _length("lengthBonus", 0.0, 0.05, 0.15)],
    },
    {
        "id": "simon", "label_tr": "Gömlek", "category": "ust", "category_tr": "Üst giyim",
        "description_tr": "Düğmeli, yakalı klasik gömlek (ileri seviye).",
        "gender": "unisex", "difficulty": 4, "sew3d": False,
        "options": [
            _fit("chestEase", 0.08, 0.15, 0.24),
            {"id": "sleeve", "label_tr": "Kol boyu", "default": "uzun", "choices": [
                {"id": "kisa", "label_tr": "Kısa kol", "set": {"sleeveStyle": "short"}},
                {"id": "uzun", "label_tr": "Uzun kol", "set": {"sleeveStyle": "long"}},
            ]},
        ],
    },
    {
        "id": "bella", "label_tr": "Temel beden kalıbı (korsaj)", "category": "temel", "category_tr": "Temel kalıp",
        "description_tr": "Pensli kadın beden kalıbı; kendi modelini türetmek için temel.",
        "gender": "female", "difficulty": 2, "sew3d": False,
        "options": [_fit("chestEase", 0.06, 0.11, 0.18)],
    },
    {
        "id": "penelope", "label_tr": "Kalem etek", "category": "alt", "category_tr": "Alt giyim",
        "description_tr": "Pensli, dize kadar kalem etek; arkada yırtmaç ve fermuar.",
        "gender": "female", "difficulty": 2, "sew3d": True,
        "edges": _PENELOPE_EDGES, "seams": _PENELOPE_SEAMS,
        "options": [
            _length("lengthBonus", -0.20, 0.0, 0.20),
            _bool("vent", "Arka yırtmaç", "backVent", True, "Var", "Yok"),
        ],
    },
    {
        "id": "sandy", "label_tr": "Kloş etek", "category": "alt", "category_tr": "Alt giyim",
        "description_tr": "Bel bantlı, dökümlü kloş (daire) etek.",
        "gender": "female", "difficulty": 1, "sew3d": True,
        "edges": _SANDY_EDGES, "seams": _SANDY_SEAMS,
        "options": [
            {"id": "length", "label_tr": "Boy", "default": "diz", "choices": [
                {"id": "mini", "label_tr": "Mini", "set": {"lengthBonus": 0.35}},
                {"id": "diz", "label_tr": "Diz boyu", "set": {"lengthBonus": 0.50}},
                {"id": "midi", "label_tr": "Midi", "set": {"lengthBonus": 0.70}},
            ]},
            {"id": "flare", "label_tr": "Bolluk (kloş)", "default": "yarim", "choices": [
                {"id": "az", "label_tr": "Az kloş", "set": {"circleRatio": 0.30}},
                {"id": "yarim", "label_tr": "Yarım daire", "set": {"circleRatio": 0.50}},
                {"id": "tam", "label_tr": "Tam daire", "set": {"circleRatio": 1.0}},
            ]},
            {"id": "rise", "label_tr": "Oturduğu yer", "default": "orta", "choices": [
                {"id": "bel", "label_tr": "Belde", "set": {"waistbandPosition": 0.0}},
                {"id": "orta", "label_tr": "Bel ile kalça arası", "set": {"waistbandPosition": 0.5}},
            ]},
        ],
    },
    {
        "id": "titan", "label_tr": "Pantolon (temel)", "category": "alt", "category_tr": "Alt giyim",
        "description_tr": "Düz paça temel pantolon kalıbı (ön + arka).",
        "gender": "unisex", "difficulty": 3, "sew3d": False,
        "options": [
            _fit("seatEase", 0.01, 0.02, 0.06, {"dar": {"waistEase": 0.01}, "normal": {"waistEase": 0.02}, "bol": {"waistEase": 0.05}}),
            _bool("knee", "Dize oturan", "fitKnee", False, "Evet", "Hayır (düz paça)"),
        ],
    },
    {
        "id": "lily", "label_tr": "Tayt", "category": "alt", "category_tr": "Alt giyim",
        "description_tr": "Çok esnek kumaş için tayt (likralı örme).",
        "gender": "female", "difficulty": 2, "sew3d": False,
        "options": [
            {"id": "length", "label_tr": "Boy", "default": "uzun", "choices": [
                {"id": "kisa", "label_tr": "Diz altı (kapri)", "set": {"lengthReduction": 0.45}},
                {"id": "normal", "label_tr": "Bilek üstü", "set": {"lengthReduction": 0.15}},
                {"id": "uzun", "label_tr": "Tam boy", "set": {"lengthReduction": 0.0}},
            ]},
        ],
    },
    {
        "id": "waralee", "label_tr": "Sarma pantolon (Tay balıkçı)", "category": "alt", "category_tr": "Alt giyim",
        "description_tr": "Bol, bele sarılarak bağlanan rahat pantolon.",
        "gender": "unisex", "difficulty": 2, "sew3d": False,
        "options": [],
    },
]
_CATALOG_BY_ID = {d["id"]: d for d in CATALOG}

PIECE_LABELS_TR = {
    "front": "Ön", "back": "Arka", "sleeve": "Kol", "cuff": "Manşet", "waistband": "Bel bandı",
    "collar": "Yaka", "collarStand": "Yaka ayağı", "yoke": "Roba", "pocket": "Cep",
    "pocketFacing": "Cep pervazı", "hoodSide": "Kapüşon yanı", "hoodCenter": "Kapüşon orta şerit",
    "neckBinding": "Yaka biyesi", "armBinding": "Kol ağzı biyesi", "frontRight": "Sağ ön",
    "frontLeft": "Sol ön", "sleevePlacketOverlap": "Kol patı (üst)",
    "sleevePlacketUnderlap": "Kol patı (alt)", "skirt": "Etek", "pants": "Pantolon",
    "backPocket": "Arka cep", "strapFront": "Ön bağcık", "strapBack": "Arka bağcık",
    "frontSideDart": "Ön (yan pensli)", "buttonPlacket": "Düğme patı",
    "buttonholePlacket": "İlik patı", "facingFront": "Ön pervaz", "facingBack": "Arka pervaz",
}
MATERIAL_LABELS_TR = {
    "fabric": "Ana kumaş", "ribbing": "Ribana", "lining": "Astar", "interfacing": "Tela",
}


def public_catalog() -> list[dict]:
    """GET /patterns/designs yanıtı — iç kenar/dikiş tanımları hariç."""
    from common.body_measurements import _BASE  # tahmin edilebilen ölçü adları

    out = []
    for d in CATALOG:
        req = _DESIGN_MEASUREMENTS.get(d["id"], [])
        out.append({
            "id": d["id"], "label_tr": d["label_tr"], "category": d["category"],
            "category_tr": d["category_tr"], "description_tr": d["description_tr"],
            "gender": d["gender"], "difficulty": d["difficulty"], "sew3d": d["sew3d"],
            "measurements": req,
            "estimable": all(m in _BASE for m in req),
            "options": [
                {"id": o["id"], "label_tr": o["label_tr"], "default": o["default"],
                 "choices": [{"id": c["id"], "label_tr": c["label_tr"]} for c in o["choices"]]}
                for o in d["options"]
            ],
            "license": "MIT (FreeSewing)",
        })
    return out


# FreeSewing getConfig().measurements — `node draft.mjs --list` ile doğrulandı (v4.10.2).
_DESIGN_MEASUREMENTS: dict[str, list[str]] = {
    "teagan": ["biceps", "chest", "hpsToBust", "hpsToWaistBack", "neck", "shoulderToShoulder", "shoulderSlope",
               "waistToArmpit", "waistToHips", "hips", "waist", "shoulderToWrist", "wrist"],
    "aaron": ["biceps", "chest", "hpsToBust", "hpsToWaistBack", "neck", "shoulderToShoulder", "shoulderSlope",
              "waistToArmpit", "waistToHips", "hips"],
    "sven": ["biceps", "chest", "hpsToBust", "hpsToWaistBack", "neck", "shoulderToShoulder", "shoulderSlope",
             "waistToArmpit", "waistToHips", "hips", "waist", "shoulderToWrist", "wrist"],
    "hugo": ["biceps", "chest", "hpsToBust", "hpsToWaistBack", "neck", "shoulderToShoulder", "shoulderSlope",
             "waistToArmpit", "waistToHips", "hips", "shoulderToWrist", "wrist", "head"],
    "simon": ["biceps", "chest", "hpsToBust", "hpsToWaistBack", "neck", "shoulderToShoulder", "shoulderSlope",
              "waistToArmpit", "waistToHips", "waist", "hips", "shoulderToWrist", "wrist"],
    "bella": ["highBust", "chest", "underbust", "waist", "waistBack", "bustSpan", "neck", "hpsToBust",
              "hpsToWaistFront", "hpsToWaistBack", "shoulderToShoulder", "shoulderSlope", "biceps",
              "shoulderToWrist", "waistToArmpit", "wrist"],
    "penelope": ["waist", "seat", "waistToHips", "waistToSeat", "waistToKnee"],
    "sandy": ["waist", "waistToFloor", "waistToHips", "hips"],
    "titan": ["crossSeam", "crossSeamFront", "knee", "seat", "seatBack", "waist", "waistBack", "waistToFloor",
              "waistToKnee", "waistToHips", "waistToSeat", "waistToUpperLeg"],
    "lily": ["crossSeam", "crossSeamFront", "knee", "seat", "seatBack", "waist", "waistBack", "waistToFloor",
             "waistToKnee", "waistToHips", "waistToSeat", "waistToUpperLeg", "ankle", "heel"],
    "waralee": ["seat", "inseam", "crotchDepth", "waistToHips"],
}


def get_design(design_id: str) -> dict:
    d = _CATALOG_BY_ID.get(str(design_id).lower())
    if d is None:
        raise PatternError(f"'{design_id}' adında bir kalıp tasarımı yok. Listeden bir tasarım seçin.")
    return d


def resolve_options(design: dict, options: dict | None, fs_options: dict | None = None) -> dict:
    """Basit seçim id'lerini ({"fit":"bol"}) FreeSewing opsiyonlarına çevir.

    Belirtilmeyen opsiyonların varsayılan seçimi uygulanır. `fs_options` ham
    FreeSewing opsiyonlarıdır (ileri kullanım) ve en son uygulanır.
    """
    options = options or {}
    if not isinstance(options, dict):
        raise PatternError("Seçenekler bir sözlük olmalı (ör. {\"fit\": \"bol\"}).")
    known = {o["id"]: o for o in design["options"]}
    for key in options:
        if key not in known:
            names = ", ".join(known) or "yok"
            raise PatternError(f"'{key}' bu tasarım için geçerli bir seçenek değil (geçerli: {names}).")
    fs: dict[str, Any] = {}
    for oid, o in known.items():
        choice_id = options.get(oid, o["default"])
        choice = next((c for c in o["choices"] if c["id"] == choice_id), None)
        if choice is None:
            valid = ", ".join(c["id"] for c in o["choices"])
            raise PatternError(f"'{o['label_tr']}' için '{choice_id}' geçersiz (geçerli: {valid}).")
        fs.update(choice["set"])
    if fs_options:
        if not isinstance(fs_options, dict):
            raise PatternError("fs_options bir sözlük olmalı.")
        for k, v in fs_options.items():
            if not isinstance(v, (int, float, bool, str)):
                raise PatternError(f"fs_options['{k}'] sayı/metin/evet-hayır olmalı.")
            fs[str(k)] = v
    return fs


# --- node çağrısı --------------------------------------------------------------
def run_freesewing(design: str, measurements: dict, options: dict, sa_mm: float,
                   render_svg: bool = True) -> dict:
    """draft.mjs'i alt süreçte çalıştır; JSON sonucu döner (hata → PatternError)."""
    if not DRAFT_SCRIPT.is_file():
        raise PatternError("Kalıp motoru (FreeSewing) kurulu değil.", status=500)
    if not (FREESEWING_DIR / "node_modules" / "@freesewing" / "core").is_dir():
        raise PatternError(
            "Kalıp motoru paketleri eksik (backend/services/freesewing içinde 'npm install' gerekli).",
            status=500,
        )
    payload = json.dumps({
        "design": design, "measurements": measurements, "options": options,
        "sa_mm": sa_mm, "render_svg": render_svg,
    })
    try:
        proc = subprocess.run(
            [node_bin(), str(DRAFT_SCRIPT)], input=payload, capture_output=True, text=True,
            cwd=str(FREESEWING_DIR), timeout=NODE_TIMEOUT_S, check=False,
        )
    except FileNotFoundError:
        raise PatternError("Node.js bulunamadı; kalıp motoru çalıştırılamıyor.", status=500) from None
    except subprocess.TimeoutExpired:
        raise PatternError("Kalıp çizimi çok uzun sürdü (zaman aşımı). Tekrar deneyin.", status=500) from None
    try:
        out = json.loads(proc.stdout or "{}")
    except json.JSONDecodeError:
        tail = (proc.stderr or "")[-400:]
        raise PatternError(f"Kalıp motoru beklenmeyen çıktı verdi. {tail}".strip(), status=500) from None
    if not out.get("ok"):
        err = str(out.get("error") or "bilinmeyen hata")
        raise PatternError(f"Kalıp çizilemedi: {err}", status=422)
    return out


# --- geometri yardımcıları -----------------------------------------------------
def _area(poly: list[list[float]]) -> float:
    s = 0.0
    n = len(poly)
    for i in range(n):
        x1, y1 = poly[i]
        x2, y2 = poly[(i + 1) % n]
        s += x1 * y2 - x2 * y1
    return s / 2.0


def polyline_length(poly: list[list[float]], i: int, j: int) -> float:
    """seam_line'da i→j (artan indeks, sararak) polyline uzunluğu."""
    n = len(poly)
    total = 0.0
    k = i
    while k != j:
        k2 = (k + 1) % n
        total += math.dist(poly[k], poly[k2])
        k = k2
    return total


def edge_points(poly: list[list[float]], i: int, j: int) -> list[list[float]]:
    return [poly[k] for k in _edge_indices(len(poly), i, j)]


def _edge_indices(n: int, i: int, j: int) -> list[int]:
    out = [i]
    k = i
    while k != j:
        k = (k + 1) % n
        out.append(k)
    return out


def _short_name(part_name: str) -> str:
    return part_name.split(".", 1)[1] if "." in part_name else part_name


def _material_info(cut: dict) -> tuple[int, list[dict], bool]:
    """FreeSewing cutlist → (ana kumaş adedi, malzeme listesi, katlı mı)."""
    mats = []
    on_fold_any = False
    for mat, cuts in (cut.get("materials") or {}).items():
        qty = 0
        fold = False
        for c in cuts or []:
            qty += int(c.get("cut") or 0)
            fold = fold or bool(c.get("onFold"))
        on_fold_any = on_fold_any or fold
        mats.append({"material": mat, "label_tr": MATERIAL_LABELS_TR.get(mat, mat),
                     "quantity": qty, "on_fold": fold})
    main = next((m for m in mats if m["material"] == "fabric"), mats[0] if mats else None)
    return (main["quantity"] if main else 1), mats, on_fold_any


def _inside(poly: list[list[float]], pt: list[float]) -> bool:
    """Çift-tek kuralıyla nokta-poligon içi testi."""
    x, y = pt
    inside = False
    n = len(poly)
    for i in range(n):
        x1, y1 = poly[i]
        x2, y2 = poly[(i + 1) % n]
        if (y1 > y) != (y2 > y):
            xi = x1 + (y - y1) * (x2 - x1) / (y2 - y1)
            if xi > x:
                inside = not inside
    return inside


def _dist_to_polyline(pt: list[float], line: list[list[float]], closed: bool = False) -> float:
    best = math.inf
    n = len(line)
    rng = range(n) if closed else range(n - 1)
    for i in rng:
        a, b = line[i], line[(i + 1) % n]
        dx, dy = b[0] - a[0], b[1] - a[1]
        l2 = dx * dx + dy * dy
        t = 0.0 if l2 == 0 else max(0.0, min(1.0, ((pt[0] - a[0]) * dx + (pt[1] - a[1]) * dy) / l2))
        best = min(best, math.hypot(pt[0] - a[0] - t * dx, pt[1] - a[1] - t * dy))
    return best


def _nearest_index(poly: list[list[float]], pt: list[float]) -> tuple[int, float]:
    best_i, best_d = 0, math.inf
    for i, q in enumerate(poly):
        d = math.dist(q, pt)
        if d < best_d:
            best_i, best_d = i, d
    return best_i, best_d


def _covers(cut: list[list[float]], seam: list[list[float]], tol: float = 0.6) -> bool:
    """Kesim çizgisi dikiş çizgisini kapsıyor mu (her köşe içeride ya da sınırda)."""
    if len(cut) < 3 or _area(cut) <= _area(seam) * 1.001:  # pay gerçekten dışarıda olmalı
        return False
    for q in seam:
        if not _inside(cut, q) and _dist_to_polyline(q, cut, closed=True) > tol:
            return False
    return True


def _stitch(sa: list[list[float]], seam: list[list[float]], sa_mm: float) -> list[list[float]] | None:
    """Açık dikiş payı yolunu, payın OLMADIĞI dikiş çizgisi yayıyla kapat.

    Ör. katlı parçada pay katlama kenarında yoktur; biyeli atlette kol/yaka
    ağzında yoktur. Payın iki ucu dikiş çizgisine izdüşürülür; iki yaydan payın
    uzağında kalanı (ortalama uzaklığı büyük olan) kesim çizgisine eklenir.
    """
    if len(sa) < 2:
        return None
    i0, d0 = _nearest_index(seam, sa[0])
    i1, d1 = _nearest_index(seam, sa[-1])
    lim = max(3.5 * sa_mm, 2.0) + 1.0
    if d0 > lim or d1 > lim or i0 == i1:
        return None
    arc_a = [seam[k] for k in _edge_indices(len(seam), i1, i0)]  # sa sonu → sa başı (artan)
    arc_b = [seam[k] for k in _edge_indices(len(seam), i0, i1)][::-1]  # sa sonu → sa başı (azalan)

    def far(arc: list[list[float]]) -> float:
        step = max(1, len(arc) // 25)
        pts = arc[::step]
        return sum(_dist_to_polyline(q, sa) for q in pts) / len(pts)

    arc = arc_a if far(arc_a) >= far(arc_b) else arc_b
    return [list(q) for q in sa] + [list(q) for q in arc[1:-1]]


def _raycast(seam: list[list[float]], sa_lines: list[list[list[float]]], sa_mm: float) -> list[list[float]]:
    """Her dikiş köşesinden dış normal boyunca ilk dikiş payı yoluna ışın at.

    Payı olmayan kenarlarda (katlama/biye) ışın bir şeye çarpmaz → nokta yerinde
    kalır. FreeSewing payı birden çok yola böldüğünde (sa + hemSa ...) kullanılır.
    """
    n = len(seam)
    maxd = max(4.0 * sa_mm, 2.0) + 1.0
    segs = [(ln[k], ln[k + 1]) for ln in sa_lines for k in range(len(ln) - 1)]
    out = []
    for i in range(n):
        p0, p1, p2 = seam[i - 1], seam[i], seam[(i + 1) % n]
        # CCW poligonda kenar (dx,dy) dış normali = (dy,-dx).
        nx = ny = 0.0
        for a, b in ((p0, p1), (p1, p2)):
            dx, dy = b[0] - a[0], b[1] - a[1]
            ln = math.hypot(dx, dy) or 1.0
            nx += dy / ln
            ny += -dx / ln
        ln = math.hypot(nx, ny)
        if ln < 1e-9:
            out.append(list(p1))
            continue
        nx, ny = nx / ln, ny / ln
        best = None
        for a, b in segs:
            ex, ey = b[0] - a[0], b[1] - a[1]
            den = nx * (-ey) - ny * (-ex)
            if abs(den) < 1e-12:
                continue
            ax, ay = a[0] - p1[0], a[1] - p1[1]
            t = (ax * (-ey) - ay * (-ex)) / den
            u = (nx * ay - ny * ax) / den
            if 0.05 < t <= maxd and -1e-6 <= u <= 1 + 1e-6 and (best is None or t < best):
                best = t
        out.append([p1[0] + nx * best, p1[1] + ny * best] if best is not None else list(p1))
    return out


def build_cut_line(seam: list[list[float]], sa_main: list[list[float]] | None,
                   sa_all: list[list[list[float]]], sa_mm: float) -> tuple[list[list[float]], str]:
    """Kesim (paylı) çizgisini kur. Döner: (poligon CCW, yöntem).

    Sıra: (1) FreeSewing ana pay yolu kapalıysa aynen, açıksa dikiş çizgisiyle
    dikişlenerek; (2) tüm pay yollarına ışın atma; (3) düz öteleme (son çare).
    Her aday dikiş çizgisini kapsıyor mu diye doğrulanır.
    """
    def ccw(poly: list[list[float]]) -> list[list[float]]:
        return poly if _area(poly) >= 0 else poly[::-1]

    if sa_mm <= 0 or (not sa_main and not sa_all):
        # Pay istenmedi ya da FreeSewing bu parçaya bilerek pay vermedi (biye şeridi).
        return [list(q) for q in seam], "none"
    cands: list[tuple[list[list[float]], str]] = []
    if sa_main and len(sa_main) >= 3:
        closed = math.dist(sa_main[0], sa_main[-1]) < 0.05
        if closed:
            cands.append((sa_main[:-1] if len(sa_main) > 3 else sa_main, "freesewing"))
        st = _stitch(sa_main, seam, sa_mm)
        if st:
            cands.append((st, "freesewing+seam"))
        if not closed:
            cands.append((sa_main, "freesewing"))
    if sa_all:
        cands.append((_raycast(seam, sa_all, sa_mm), "raycast"))
    for poly, method in cands:
        poly = ccw([list(q) for q in poly])
        if _covers(poly, seam):
            return poly, method
    from common.sewing import _offset_polygon  # noqa: PLC0415 — yerel yardımcı
    import numpy as np

    return ccw(_offset_polygon(np.asarray(seam, dtype=float), float(sa_mm)).tolist()), "offset"


def build_pieces(design: dict, fs_out: dict, sa_mm: float) -> tuple[list[dict], list[dict], list[str]]:
    """FreeSewing parçaları → sözleşme `pieces` + `seams` + uyarılar."""
    warnings: list[str] = []
    pieces: list[dict] = []
    flipped: dict[str, bool] = {}
    anchors_by_piece: dict[str, dict[str, int]] = {}
    used_names: set[str] = set()
    for part in fs_out.get("parts", []):
        name = _short_name(part["name"])
        if name in used_names:
            name = part["name"].replace(".", "_")
        used_names.add(name)
        # y-aşağı → y-yukarı
        seam = [[float(x), -float(y)] for x, y in part["seam"]]
        sa_raw = part.get("sa")
        sa_main = [[float(x), -float(y)] for x, y in sa_raw] if sa_raw else None
        sa_all = [[[float(x), -float(y)] for x, y in ln] for ln in (part.get("sa_all") or [])]
        anchors = dict(part.get("anchors") or {})
        n = len(seam)
        rev = _area(seam) < 0
        if rev:
            seam = seam[::-1]
            anchors = {k: n - 1 - v for k, v in anchors.items()}
        cut, cut_method = build_cut_line(seam, sa_main, sa_all, float(sa_mm))
        if cut_method == "offset" and (sa_main or sa_all):
            warnings.append(f"{name}: FreeSewing dikiş payı yolu kullanılamadı, düz öteleme uygulandı.")
        # Sınır kutusunu (0,0)'a ötele.
        minx = min(p[0] for p in cut + seam)
        miny = min(p[1] for p in cut + seam)
        seam = [[round(x - minx, 3), round(y - miny, 3)] for x, y in seam]
        cut = [[round(x - minx, 3), round(y - miny, 3)] for x, y in cut]
        qty, mats, _on_fold = _material_info(part.get("cut") or {})
        fold_info = (part.get("cut") or {}).get("cutOnFold")
        # Katlı kesim → yarım parça, simetri ekseni = katlama kenarı. FreeSewing
        # cutOnFold bilgisini türetilen parçalara da kopyalar (simon roba, hugo cep
        # pervazı) → yalnız iki katlama ucu da bu parçanın dış hattındaysa geçerli.
        mirror = bool(fold_info) and "__fold0" in anchors and "__fold1" in anchors \
            and anchors["__fold0"] != anchors["__fold1"]
        grain = (part.get("cut") or {}).get("grain")
        grain_deg = float(grain) % 180.0 if grain is not None else 90.0
        pieces.append({
            "name": name,
            "label_tr": PIECE_LABELS_TR.get(name, name),
            "quantity": qty,
            "mirror": mirror,
            "fold_edge": None,
            "materials": mats,
            "seam_line": seam,
            "cut_line": cut,
            "grain_deg": round(grain_deg, 3),
            "edges": [],
            "area_cm2": round(abs(_area(seam)) / 100.0, 1),
            "cut_method": cut_method,
            "fs_part": part["name"],
        })
        flipped[name] = rev
        anchors_by_piece[name] = anchors

    by_name = {p["name"]: p for p in pieces}
    edge_rev: dict[str, bool] = {}
    # Katalog kenarları (FreeSewing sırası) → sözleşme kenarları (son çerçeve).
    for piece_name, edge_name, start, end in design.get("edges", []):
        p = by_name.get(piece_name)
        if p is None:
            continue
        anchors = anchors_by_piece[piece_name]
        ends = end if isinstance(end, list) else [end]
        end_found = next((e for e in ends if e in anchors), None)
        if start not in anchors or end_found is None:
            warnings.append(f"{piece_name}.{edge_name}: kenar noktaları bulunamadı, atlandı.")
            continue
        i, j = anchors[start], anchors[end_found]
        if flipped[piece_name]:
            i, j = j, i  # ters çevrilmiş poligonda artan yön bitiş→başlangıç
        eid = f"{piece_name}.{edge_name}"
        p["edges"].append({
            "id": eid, "from": i, "to": j,
            "from_point": end_found if flipped[piece_name] else start,
            "to_point": start if flipped[piece_name] else end_found,
            "length_mm": round(polyline_length(p["seam_line"], i, j), 1),
        })
        edge_rev[eid] = flipped[piece_name]
    # Katlı parçalar: katlama kenarı = cutOnFold uçlarını (__fold0/__fold1) içeren
    # katalog kenarı; katalogta yoksa iki uç arasındaki kısa yoldan genel kenar kurulur.
    for p in pieces:
        if not p["mirror"]:
            continue
        a = anchors_by_piece[p["name"]]
        if "__fold0" not in a or "__fold1" not in a:
            continue
        n = len(p["seam_line"])
        fold_idx = {a["__fold0"], a["__fold1"]}
        fold_edge = None
        for e in p["edges"]:
            if fold_idx <= set(_edge_indices(n, e["from"], e["to"])):
                fold_edge = e["id"]
                break
        if fold_edge is None:
            i, j = a["__fold0"], a["__fold1"]
            if polyline_length(p["seam_line"], i, j) > polyline_length(p["seam_line"], j, i):
                i, j = j, i
            fold_edge = f"{p['name']}.fold"
            p["edges"].append({"id": fold_edge, "from": i, "to": j, "from_point": "__fold",
                               "to_point": "__fold",
                               "length_mm": round(polyline_length(p["seam_line"], i, j), 1)})
        p["fold_edge"] = fold_edge

    # Pensler: dart{N}Start/Middle/End noktaları olan parçalarda pens kenarları + dikişi.
    seams: list[dict] = []
    if design.get("sew3d"):
        for p in pieces:
            a = anchors_by_piece[p["name"]]
            for nidx in range(1, 6):
                s, m, e = (f"dart{nidx}Start", f"dart{nidx}Middle", f"dart{nidx}End")
                if not all(k in a for k in (s, m, e)):
                    continue
                lo, hi = sorted((a[s], a[e]))
                mid = a[m]
                if not (lo < mid < hi):
                    warnings.append(f"{p['name']}: pens {nidx} sırası beklenmedik, atlandı.")
                    continue
                ida, idb = f"{p['name']}.dart{nidx}_a", f"{p['name']}.dart{nidx}_b"
                p["edges"].append({"id": ida, "from": lo, "to": mid, "from_point": "waist",
                                   "to_point": "tip",
                                   "length_mm": round(polyline_length(p["seam_line"], lo, mid), 1)})
                p["edges"].append({"id": idb, "from": mid, "to": hi, "from_point": "tip",
                                   "to_point": "waist",
                                   "length_mm": round(polyline_length(p["seam_line"], mid, hi), 1)})
                seams.append({"a": ida, "b": idb, "reverse": True, "kind": "dart"})
        known_edges = {e["id"] for p in pieces for e in p["edges"]}
        main_seams: list[dict] = []
        for a_id, b_id, rev in design.get("seams", []):
            if a_id not in known_edges or b_id not in known_edges:
                warnings.append(f"Dikiş {a_id}↔{b_id} kurulamadı (kenar eksik).")
                continue
            final_rev = bool(rev) ^ edge_rev.get(a_id, False) ^ edge_rev.get(b_id, False)
            if a_id == b_id:
                final_rev = bool(rev)
            main_seams.append({"a": a_id, "b": b_id, "reverse": final_rev, "kind": "seam"})
        seams = main_seams + seams  # önce ana dikişler, sonra pensler
    return pieces, seams, warnings


# --- SVG -----------------------------------------------------------------------
def _layout(pieces: list[dict], max_w: float = 1100.0, gap: float = 25.0,
            top: float = 0.0) -> tuple[list[tuple[float, float]], float, float]:
    """Basit raf yerleşimi (yükseklik sıralı). Döner: ofsetler (sol-alt), W, H."""
    sizes = []
    for p in pieces:
        xs = [q[0] for q in p["cut_line"]]
        ys = [q[1] for q in p["cut_line"]]
        sizes.append((max(xs), max(ys)))
    widest = max((w for w, _ in sizes), default=0.0)
    max_w = max(max_w, widest)
    order = sorted(range(len(pieces)), key=lambda i: -sizes[i][1])
    offsets: list[tuple[float, float]] = [(0.0, 0.0)] * len(pieces)
    x = 0.0
    y = top
    row_h = 0.0
    used_w = 0.0
    for i in order:
        w, h = sizes[i]
        if x > 0 and x + w > max_w:
            y += row_h + gap
            x = 0.0
            row_h = 0.0
        offsets[i] = (x, y)
        x += w + gap
        row_h = max(row_h, h)
        used_w = max(used_w, x - gap)
    return offsets, used_w, y + row_h


def _esc(s: str) -> str:
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            .replace('"', "&quot;"))


def pieces_to_svg(pieces: list[dict], out_svg: Path, title: str, subtitle: str,
                  sa_mm: float) -> dict:
    """Parçaları 1:1 mm SVG'ye yaz. Sol üstte 10 cm kalibrasyon karesi + başlık.

    Kesim çizgisi düz siyah, dikiş çizgisi kesikli gri, katlama kenarı mavi kalın
    ("KUMAŞ KATI"), düz boy oku, parça etiketi + adet. Döner: {width_mm, height_mm}.
    """
    margin = 15.0
    header_h = 130.0  # 100 mm kare + yazı
    offsets, used_w, used_h = _layout(pieces)
    width = max(used_w, 260.0) + 2 * margin
    height = header_h + used_h + 2 * margin

    def T(px: float, py: float, off: tuple[float, float], ph: float) -> tuple[float, float]:
        # parça y-yukarı → SVG y-aşağı; her parça kendi kutusunda çevrilir.
        ox, oy = off
        return margin + ox + px, margin + header_h + oy + (ph - py)

    parts: list[str] = []
    parts.append(
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width:.2f}mm" height="{height:.2f}mm" '
        f'viewBox="0 0 {width:.2f} {height:.2f}">'
    )
    parts.append(f'<rect x="0" y="0" width="{width:.2f}" height="{height:.2f}" fill="#ffffff"/>')
    # Kalibrasyon karesi 100×100 mm.
    parts.append(
        f'<rect x="{margin:.2f}" y="{margin:.2f}" width="100" height="100" fill="none" '
        f'stroke="#000000" stroke-width="0.5"/>'
    )
    parts.append(
        f'<text x="{margin + 50:.2f}" y="{margin + 48:.2f}" font-size="9" text-anchor="middle" '
        f'fill="#000000" font-family="DejaVu Sans, Arial, sans-serif">10 cm</text>'
    )
    parts.append(
        f'<text x="{margin + 50:.2f}" y="{margin + 60:.2f}" font-size="4" text-anchor="middle" '
        f'fill="#333333" font-family="DejaVu Sans, Arial, sans-serif">Basınca cetvelle ölçün: 10 cm olmalı</text>'
    )
    tx = margin + 115
    parts.append(f'<text x="{tx:.2f}" y="{margin + 12:.2f}" font-size="10" fill="#111111" '
                 f'font-family="DejaVu Sans, Arial, sans-serif" font-weight="bold">{_esc(title)}</text>')
    parts.append(f'<text x="{tx:.2f}" y="{margin + 22:.2f}" font-size="4.5" fill="#333333" '
                 f'font-family="DejaVu Sans, Arial, sans-serif">{_esc(subtitle)}</text>')
    legend = [
        "Düz siyah çizgi: KESİM çizgisi (dikiş payı dahil)",
        f"Kesikli gri çizgi: DİKİŞ çizgisi (pay {sa_mm:g} mm)",
        "Mavi kalın çizgi: KUMAŞ KATI — kumaşı katlayıp bu kenarı katın üstüne koyun",
        "Ok: düz boy (kumaş kenarına paralel gelmeli)",
        "Ölçek 1:1 — yazdırırken 'gerçek boyut / %100' seçin",
    ]
    for k, line in enumerate(legend):
        parts.append(f'<text x="{tx:.2f}" y="{margin + 34 + k * 7:.2f}" font-size="4" fill="#333333" '
                     f'font-family="DejaVu Sans, Arial, sans-serif">{_esc(line)}</text>')

    for p, off in zip(pieces, offsets):
        ph = max(q[1] for q in p["cut_line"])

        def d_of(poly: list[list[float]]) -> str:
            pts = " ".join("{:.2f},{:.2f}".format(*T(x, y, off, ph)) for x, y in poly)
            return f"M {pts} Z"

        parts.append(f'<path d="{d_of(p["cut_line"])}" fill="#fbfbf7" stroke="#000000" stroke-width="0.6"/>')
        parts.append(f'<path d="{d_of(p["seam_line"])}" fill="none" stroke="#777777" '
                     f'stroke-width="0.35" stroke-dasharray="4,2"/>')
        if p.get("fold_edge"):
            e = next((e for e in p["edges"] if e["id"] == p["fold_edge"]), None)
            if e:
                pts = edge_points(p["seam_line"], e["from"], e["to"])
                pd = " ".join("{:.2f},{:.2f}".format(*T(x, y, off, ph)) for x, y in pts)
                parts.append(f'<path d="M {pd}" fill="none" stroke="#1f5fbf" stroke-width="1.6"/>')
                mx = sum(q[0] for q in pts) / len(pts)
                my = sum(q[1] for q in pts) / len(pts)
                sx, sy = T(mx, my, off, ph)
                parts.append(
                    f'<text x="{sx + 4:.2f}" y="{sy:.2f}" font-size="5" fill="#1f5fbf" '
                    f'font-family="DejaVu Sans, Arial, sans-serif" transform="rotate(-90 {sx + 4:.2f} {sy:.2f})" '
                    f'text-anchor="middle">KUMAŞ KATI</text>'
                )
        # Etiket + düz boy oku (parça merkezinde).
        xs = [q[0] for q in p["seam_line"]]
        ys = [q[1] for q in p["seam_line"]]
        cx, cy = (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2
        L = min(120.0, (max(ys) - min(ys)) * 0.5, (max(xs) - min(xs)) * 0.9 if p["grain_deg"] % 180 < 45 else 1e9)
        L = max(L, 20.0)
        ang = math.radians(p["grain_deg"])
        ax0, ay0 = cx - math.cos(ang) * L / 2, cy - math.sin(ang) * L / 2
        ax1, ay1 = cx + math.cos(ang) * L / 2, cy + math.sin(ang) * L / 2
        (X0, Y0), (X1, Y1) = T(ax0, ay0, off, ph), T(ax1, ay1, off, ph)
        parts.append(f'<line x1="{X0:.2f}" y1="{Y0:.2f}" x2="{X1:.2f}" y2="{Y1:.2f}" stroke="#444444" stroke-width="0.5"/>')
        for (Xa, Ya), (Xb, Yb) in (((X1, Y1), (X0, Y0)), ((X0, Y0), (X1, Y1))):
            dx, dy = Xa - Xb, Ya - Yb
            ln = math.hypot(dx, dy) or 1.0
            ux, uy = dx / ln, dy / ln
            hx, hy = Xa - ux * 5, Ya - uy * 5
            parts.append(
                f'<path d="M {Xa:.2f},{Ya:.2f} L {hx - uy * 2:.2f},{hy + ux * 2:.2f} '
                f'L {hx + uy * 2:.2f},{hy - ux * 2:.2f} Z" fill="#444444"/>'
            )
        LX, LY = T(cx, cy, off, ph)
        how = "kumaş katlı" if p["mirror"] else ("çift (biri ters)" if p["quantity"] == 2 else "")
        qty = f'{p["quantity"]} adet' + (f" — {how}" if how else "")
        mats = ", ".join(f'{m["label_tr"]}×{m["quantity"]}' for m in p["materials"] if m["material"] != "fabric")
        parts.append(f'<text x="{LX + 4:.2f}" y="{LY - 8:.2f}" font-size="8" fill="#111111" '
                     f'font-family="DejaVu Sans, Arial, sans-serif" font-weight="bold">{_esc(p["label_tr"])}</text>')
        parts.append(f'<text x="{LX + 4:.2f}" y="{LY:.2f}" font-size="4.5" fill="#333333" '
                     f'font-family="DejaVu Sans, Arial, sans-serif">{_esc(qty)}</text>')
        if mats:
            parts.append(f'<text x="{LX + 4:.2f}" y="{LY + 6:.2f}" font-size="4" fill="#333333" '
                         f'font-family="DejaVu Sans, Arial, sans-serif">{_esc(mats)}</text>')
    parts.append("</svg>")
    out_svg.parent.mkdir(parents=True, exist_ok=True)
    out_svg.write_text("\n".join(parts), encoding="utf-8")
    return {"width_mm": round(width, 2), "height_mm": round(height, 2)}


# --- uçtan uca -----------------------------------------------------------------
def draft_pattern(design_id: str, measurements: dict[str, float] | None = None,
                  body: dict | None = None, options: dict | None = None,
                  fs_options: dict | None = None, sa_mm: float = 10.0,
                  pattern_id: str | None = None) -> dict:
    """Kalıbı çiz + data/patterns/<id>/ altına tüm dosyaları yaz. meta.json içeriğini döner."""
    from common.body_measurements import MeasurementError, estimate_measurements
    from common.sewing import svg_to_pdf_tiles

    design = get_design(design_id)
    try:
        sa = float(sa_mm)
    except (TypeError, ValueError):
        raise PatternError("Dikiş payı (sa_mm) sayı olmalı.") from None
    if not (0.0 <= sa <= 50.0):
        raise PatternError("Dikiş payı 0–50 mm arasında olmalı.")

    meas: dict[str, float] = {}
    source = "custom"
    if body:
        try:
            meas.update(estimate_measurements(body))
        except MeasurementError as exc:
            raise PatternError(str(exc)) from None
        source = "estimated" if not measurements else "estimated+custom"
    if measurements:
        if not isinstance(measurements, dict):
            raise PatternError("measurements bir sözlük olmalı ({ölçü_adı: mm}).")
        for k, v in measurements.items():
            try:
                fv = float(v)
            except (TypeError, ValueError):
                raise PatternError(f"'{k}' ölçüsü sayı olmalı (mm).") from None
            if not (0 < fv < 3000):
                raise PatternError(f"'{k}' ölçüsü {fv:g} mm olamaz.")
            meas[str(k)] = fv
    if not meas:
        raise PatternError("Ölçü gerekli: 'body' (cinsiyet, boy, göğüs, bel, basen) ya da 'measurements' gönderin.")
    required = _DESIGN_MEASUREMENTS.get(design["id"], [])
    missing = [m for m in required if m not in meas]
    if missing:
        raise PatternError(
            "Bu tasarım için eksik ölçü var: " + ", ".join(missing)
            + ". 'body' alanıyla 5 basit ölçü gönderirseniz eksikler tahmin edilir."
        )
    fs_opts = resolve_options(design, options, fs_options)

    fs_out = run_freesewing(design["id"], meas, fs_opts, sa)
    pieces, seams, warnings = build_pieces(design, fs_out, sa)
    if not pieces:
        raise PatternError("Kalıp parçası üretilemedi.", status=500)
    for w in fs_out.get("logs", {}).get("error", [])[:5]:
        warnings.append(f"FreeSewing: {w}")

    pid = pattern_id or uuid.uuid4().hex
    out_dir = pattern_path(pid)
    out_dir.mkdir(parents=True, exist_ok=True)
    pieces_doc = {
        "pattern_id": pid, "design": design["id"], "units": "mm", "coords": "y_up",
        "sa_mm": sa, "measurements": meas, "pieces": pieces, "seams": seams,
    }
    (out_dir / "pieces.json").write_text(json.dumps(pieces_doc, ensure_ascii=False, indent=1), encoding="utf-8")
    if fs_out.get("svg"):
        (out_dir / "freesewing.svg").write_text(fs_out["svg"], encoding="utf-8")
    choice_labels = []
    opts_in = options or {}
    for o in design["options"]:
        cid = opts_in.get(o["id"], o["default"])
        c = next((c for c in o["choices"] if c["id"] == cid), None)
        if c:
            choice_labels.append(f'{o["label_tr"]}: {c["label_tr"]}')
    subtitle_bits = []
    if body:
        subtitle_bits.append(
            f'Boy {body.get("height_cm")} · Göğüs {body.get("chest_cm")} · Bel {body.get("waist_cm")} · '
            f'Basen {body.get("hip_cm")} cm'
        )
    subtitle_bits += choice_labels
    size = pieces_to_svg(pieces, out_dir / "pattern.svg", f'{design["label_tr"]} — dikiş kalıbı',
                         " · ".join(subtitle_bits) or "Özel ölçüler", sa)
    try:
        svg_to_pdf_tiles(str(out_dir / "pattern.svg"), str(out_dir / "pattern.pdf"),
                         label=f'{design["label_tr"]} kalıbı')
    except Exception as exc:  # noqa: BLE001 — PDF olmadan da kalıp kullanılabilir
        warnings.append(f"PDF üretilemedi: {exc}")
    meta = {
        "pattern_id": pid,
        "design": design["id"],
        "label_tr": design["label_tr"],
        "category": design["category"],
        "sew3d": bool(design["sew3d"] and seams),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "sa_mm": sa,
        "body": body or None,
        "measurements_source": source,
        "measurements": meas,
        "options": opts_in,
        "fs_options": fs_opts,
        "freesewing_version": fs_out.get("version"),
        "license": "Kalıp motoru: FreeSewing (MIT)",
        "svg_size_mm": size,
        "fold_edges": {p["name"]: p["fold_edge"] for p in pieces},
        "pieces": [{"name": p["name"], "label_tr": p["label_tr"], "quantity": p["quantity"],
                    "mirror": p["mirror"], "fold_edge": p["fold_edge"], "area_cm2": p["area_cm2"]}
                   for p in pieces],
        "warnings": warnings,
    }
    (out_dir / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    return meta


def read_meta(pattern_id: str) -> dict:
    path = pattern_path(pattern_id) / "meta.json"
    if not path.is_file():
        raise PatternError("Kalıp bulunamadı", status=404)
    return json.loads(path.read_text(encoding="utf-8"))


def list_patterns() -> list[dict]:
    root = patterns_dir()
    if not root.is_dir():
        return []
    out = []
    for d in root.iterdir():
        mp = d / "meta.json"
        if d.is_dir() and mp.is_file():
            try:
                out.append(json.loads(mp.read_text(encoding="utf-8")))
            except (OSError, json.JSONDecodeError):
                continue
    out.sort(key=lambda m: m.get("created_at", ""), reverse=True)
    return out


def delete_pattern(pattern_id: str) -> None:
    d = pattern_path(pattern_id)
    if not (d / "meta.json").is_file():
        raise PatternError("Kalıp bulunamadı", status=404)
    shutil.rmtree(d)
