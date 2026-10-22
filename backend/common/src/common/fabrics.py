"""Kumaş hazır ayarları (fizik + görünüm) — tek kaynak.

Her kumaş iki parçalı bir tanım taşır:

* ``blender``: Blender Cloth modifier ayarları (``bpy.types.ClothSettings``
  alan adlarıyla BİREBİR aynı anahtarlar) — drape (``clothsim_worker``) ve 3D
  dikiş (F2) simülasyonları bunu ``blender_params(id)`` ile alıp cloth
  settings'e ``setattr`` ile uygular.
* ``pbr``: three.js ``MeshPhysicalMaterial`` alanlarıyla uyumlu görünüm
  (base_color hex, roughness, metalness, sheen, sheen_roughness, sheen_color,
  opsiyonel normal_strength) — frontend kumaş seçicide malzemeye uygular.

Değerler Blender'ın kendi cloth presetlerinden (Cotton/Denim/Leather/Silk —
``<blender>/4.2/scripts/presets/cloth``) türetilip bu projenin askı (pin)
simülasyonu için KALİBRE edildi. Neden preset'ler aynen değil: drape günlüğü
(2026-07-06) pin'li asılı kumaşta düşük gerilme sertliğinin (t15) %230 sakız
gibi uzama, çok yüksek sertliğin (t200) ise çözücü patlaması verdiğini gösterdi.
Bu yüzden gerilme/sıkışma 25..80 bandında tutulur; kumaşlar arası fark asıl
**kütle**, **eğilme sertliği** (katlanma/dökümlülük) ve **sönümleme** ile verilir.

GERİYE UYUM: ``denim`` = fabric_id verilmeyen eski drape çağrılarının birebir
aynısı (quality 6, tension/compression 80, shear 40, bending 0.5; diğer alanlar
Blender varsayılanı: mass 0.3, dampings 5/5/5, bending_damping 0.5, air 1).

Genel API (F2 de bunu kullanır):
    list_fabrics()            -> list[dict]   (UI/GET /fabrics için tam liste, kopya)
    get_fabric(id)            -> dict | None  (bilinmeyen id → None)
    blender_params(id)        -> dict         (bilinmeyen id → KeyError, Türkçe mesaj)
    DEFAULT_FABRIC_ID         = "denim"
"""
from __future__ import annotations

import copy

DEFAULT_FABRIC_ID = "denim"

# Blender ClothSettings'te geçerli sayılan anahtarlar (blender_params çıktısı
# yalnız bunları içerir → Blender tarafında körlemesine setattr güvenli).
BLENDER_KEYS = (
    "quality", "mass", "air_damping",
    "tension_stiffness", "compression_stiffness", "shear_stiffness",
    "bending_stiffness",
    "tension_damping", "compression_damping", "shear_damping", "bending_damping",
)

FABRICS: list[dict] = [
    {
        "id": "cotton",
        "name_tr": "Pamuk",
        "name_en": "Cotton",
        "desc_tr": "Tişört kumaşı gibi: yumuşak, hafif, doğal düşer.",
        "blender": {
            "quality": 6, "mass": 0.3, "air_damping": 1.0,
            "tension_stiffness": 60.0, "compression_stiffness": 60.0,
            "shear_stiffness": 30.0, "bending_stiffness": 0.8,
            "tension_damping": 5.0, "compression_damping": 5.0,
            "shear_damping": 5.0, "bending_damping": 0.5,
        },
        "pbr": {"base_color": "#f2efe8", "roughness": 0.9, "metalness": 0.0,
                "sheen": 0.4, "sheen_roughness": 0.8, "sheen_color": "#ffffff",
                "normal_strength": 0.3},
    },
    {
        "id": "denim",
        "name_tr": "Kot",
        "name_en": "Denim",
        "desc_tr": "Kalın ve dayanıklı: kot pantolon/ceket kumaşı.",
        "blender": {
            # BİREBİR eski drape değerleri (geriye uyum — değiştirme!).
            "quality": 6, "mass": 0.3, "air_damping": 1.0,
            "tension_stiffness": 80.0, "compression_stiffness": 80.0,
            "shear_stiffness": 40.0, "bending_stiffness": 0.5,
            "tension_damping": 5.0, "compression_damping": 5.0,
            "shear_damping": 5.0, "bending_damping": 0.5,
        },
        "pbr": {"base_color": "#3b5a85", "roughness": 0.85, "metalness": 0.0,
                "sheen": 0.2, "sheen_roughness": 0.7, "sheen_color": "#9fb4d6",
                "normal_strength": 0.6},
    },
    {
        "id": "silk",
        "name_tr": "İpek",
        "name_en": "Silk",
        "desc_tr": "Çok hafif ve parlak: akar gibi dökülür, bol kıvrım yapar.",
        "blender": {
            "quality": 7, "mass": 0.15, "air_damping": 1.0,
            "tension_stiffness": 40.0, "compression_stiffness": 40.0,
            "shear_stiffness": 10.0, "bending_stiffness": 0.05,
            "tension_damping": 0.0, "compression_damping": 0.0,
            "shear_damping": 0.0, "bending_damping": 0.1,
        },
        "pbr": {"base_color": "#e9d9c4", "roughness": 0.3, "metalness": 0.0,
                "sheen": 1.0, "sheen_roughness": 0.25, "sheen_color": "#fff4e0",
                "normal_strength": 0.1},
    },
    {
        "id": "knit",
        "name_tr": "Örme",
        "name_en": "Knit",
        "desc_tr": "Esnek örgü kumaş: kazak/triko gibi, vücuda oturur.",
        "blender": {
            "quality": 7, "mass": 0.35, "air_damping": 1.0,
            "tension_stiffness": 25.0, "compression_stiffness": 25.0,
            "shear_stiffness": 12.0, "bending_stiffness": 0.3,
            "tension_damping": 10.0, "compression_damping": 10.0,
            "shear_damping": 10.0, "bending_damping": 0.5,
        },
        "pbr": {"base_color": "#b85c5c", "roughness": 0.95, "metalness": 0.0,
                "sheen": 0.8, "sheen_roughness": 0.9, "sheen_color": "#ffd6d6",
                "normal_strength": 0.8},
    },
    {
        "id": "linen",
        "name_tr": "Keten",
        "name_en": "Linen",
        "desc_tr": "Serin yazlık kumaş: hafif sert, kolay kırışır.",
        "blender": {
            "quality": 6, "mass": 0.3, "air_damping": 1.0,
            "tension_stiffness": 70.0, "compression_stiffness": 70.0,
            "shear_stiffness": 40.0, "bending_stiffness": 2.0,
            "tension_damping": 5.0, "compression_damping": 5.0,
            "shear_damping": 5.0, "bending_damping": 0.5,
        },
        "pbr": {"base_color": "#d8ccb4", "roughness": 0.92, "metalness": 0.0,
                "sheen": 0.3, "sheen_roughness": 0.85, "sheen_color": "#f5efe0",
                "normal_strength": 0.5},
    },
    {
        "id": "leather",
        "name_tr": "Deri",
        "name_en": "Leather",
        "desc_tr": "Ağır ve sert: ceket derisi gibi, az katlanır.",
        "blender": {
            "quality": 8, "mass": 0.4, "air_damping": 1.0,
            "tension_stiffness": 80.0, "compression_stiffness": 80.0,
            "shear_stiffness": 80.0, "bending_stiffness": 50.0,
            "tension_damping": 25.0, "compression_damping": 25.0,
            "shear_damping": 25.0, "bending_damping": 2.0,
        },
        "pbr": {"base_color": "#4a3324", "roughness": 0.55, "metalness": 0.0,
                "sheen": 0.0, "sheen_roughness": 0.5, "sheen_color": "#000000",
                "normal_strength": 0.7},
    },
    {
        "id": "chiffon",
        "name_tr": "Şifon",
        "name_en": "Chiffon",
        "desc_tr": "Tül gibi ince ve uçuşkan: elbise/şal kumaşı.",
        "blender": {
            "quality": 7, "mass": 0.1, "air_damping": 2.0,
            "tension_stiffness": 30.0, "compression_stiffness": 30.0,
            "shear_stiffness": 8.0, "bending_stiffness": 0.02,
            "tension_damping": 0.0, "compression_damping": 0.0,
            "shear_damping": 0.0, "bending_damping": 0.1,
        },
        "pbr": {"base_color": "#f4dfe6", "roughness": 0.5, "metalness": 0.0,
                "sheen": 0.9, "sheen_roughness": 0.4, "sheen_color": "#ffffff",
                "normal_strength": 0.05},
    },
    {
        "id": "wool",
        "name_tr": "Yün",
        "name_en": "Wool",
        "desc_tr": "Sıcak kışlık kumaş: kalın, yumuşak ve dolgun düşer.",
        "blender": {
            "quality": 6, "mass": 0.45, "air_damping": 1.0,
            "tension_stiffness": 70.0, "compression_stiffness": 70.0,
            "shear_stiffness": 35.0, "bending_stiffness": 5.0,
            "tension_damping": 10.0, "compression_damping": 10.0,
            "shear_damping": 10.0, "bending_damping": 1.0,
        },
        "pbr": {"base_color": "#6e6259", "roughness": 0.98, "metalness": 0.0,
                "sheen": 0.7, "sheen_roughness": 0.95, "sheen_color": "#c8beb4",
                "normal_strength": 0.9},
    },
]

_BY_ID: dict[str, dict] = {f["id"]: f for f in FABRICS}


def fabric_ids() -> list[str]:
    """Geçerli kumaş id'leri (FABRICS sırasıyla)."""
    return [f["id"] for f in FABRICS]


def list_fabrics() -> list[dict]:
    """Tüm kumaşların DERİN KOPYASI (çağıran değiştirse de FABRICS bozulmaz)."""
    return copy.deepcopy(FABRICS)


def get_fabric(fabric_id: str | None) -> dict | None:
    """id → kumaş tanımının kopyası; bilinmeyen/boş id → None."""
    if not fabric_id:
        return None
    f = _BY_ID.get(fabric_id)
    return copy.deepcopy(f) if f is not None else None


def blender_params(fabric_id: str | None = None) -> dict:
    """id → Blender ClothSettings'e doğrudan ``setattr`` edilebilir düz dict.

    ``None``/boş id → varsayılan (denim, geriye uyumlu eski drape ayarları).
    Bilinmeyen id → ``KeyError`` (Türkçe mesaj). Dönen anahtarlar yalnız
    ``BLENDER_KEYS`` içindendir; değerler float/int.

    Kullanım (Blender içinde)::

        for k, v in params.items():
            setattr(cloth_mod.settings, k, v)
    """
    fid = fabric_id or DEFAULT_FABRIC_ID
    f = _BY_ID.get(fid)
    if f is None:
        raise KeyError(f"Bilinmeyen kumaş: {fid!r}. Geçerli kumaşlar: "
                       + ", ".join(fabric_ids()))
    return {k: f["blender"][k] for k in BLENDER_KEYS if k in f["blender"]}
