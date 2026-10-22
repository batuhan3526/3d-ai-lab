"""Tek-nesne (standalone product) prompt kalıbı — TRELLIS'i karakter/sahne yerine
tek bir kıyafet nesnesine odaklar. Bkz M-A tasarım Bölüm 5 + canlı bulgu
(TRELLIS 'fox-themed boot'u 'tilki + çizme' diye harfi harfine üretiyordu)."""
from __future__ import annotations

GARMENT_EN: dict[str, str] = {
    "model": "object",  # jenerik tür (2026-07-12): giysi-dışı üretimlerin varsayılanı
    "tshirt": "t-shirt",
    "shirt": "shirt",
    "pants": "pants",
    "skirt": "skirt",
    "hat": "hat",
    "boots": "boot",
}


def build_object_prompt(description_en: str, garment_type: str) -> str:
    """Çevrilmiş İngilizce açıklamayı tek-nesne ürün kalıbına sarar."""
    garment = GARMENT_EN.get(garment_type, garment_type)
    desc = description_en.strip()
    return (
        f"a single {garment}, {desc}, standalone product object, centered, "
        "isolated on a plain background, studio product render"
    )
    # Olumsuzlama YOK: TRELLIS-text CLIP koşullu, "no person, no mannequin" bu kelimeleri
    # tersine EKLER → tişört yerine tam insan figürü (2026-10-18 A/B, sabit seed: 3/3 figür
    # vs olumsuzlamasız 2/2 tişört).
