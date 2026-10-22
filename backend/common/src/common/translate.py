"""Türkçe→İngilizce çeviri (offline). Backend seçilebilir: argos | opus.

Backend `translate_backend` ayarıyla (env TRANSLATE_BACKEND) seçilir. Çeviri
ASLA çağıranı patlatmaz — herhangi bir hatada girdiyi aynen döndürür.
opus (Helsinki-NLP/opus-mt-tr-en, MarianMT, CC-BY-4.0 — ATIF gerekir) yalnız
worker venv'inde kuruludur; ağır importlar fonksiyon-içi (lazy).
(M2M-100 418M denendi ama TR'de zayıftı: tilki→rabbit, bot→boat, bluz→blue;
Opus-MT belirgin daha iyi: fox/blouse/blue jeans doğru.)"""
from __future__ import annotations

import re
import sys

from common.config import get_settings

_opus_cache: dict = {}

# Türkçe'ye özgü harfler (İngilizce'de yok). Varsa metin İngilizce DEĞİLDİR.
_TR_CHARS = frozenset("çğıİöşüÇĞİÖŞÜ")

# Bu alanda (kıyafet tasarımı) sık geçen İngilizce kelimeler. Türkçe ile
# İngilizce neredeyse hiç sözcük paylaşmaz; bu yüzden "çoğunluğu bu sözlükte =
# İngilizce" tespiti Türkçe'yi yanlışlıkla İngilizce saymaz. Kapsam dışı bir
# İngilizce kelime en kötü ihtimalle metni "Türkçe" sanıp çeviriye sokar —
# güvenli taraf (İngilizceyi opus-mt TR->EN'e verip BOZMAK kötü olandı).
_EN_WORDS = frozenset("""
a an the and or of with without in on at for to from this that these those is are be
my your no not some all one two three four five plus over under into without as
red orange yellow green blue purple violet pink rose magenta gold golden silver
black white gray grey brown beige navy teal cyan maroon olive turquoise lavender
cream tan light dark bright pale neon pastel colorful colourful multicolor
shirt tshirt tee blouse dress skirt pants trousers jeans jacket coat hoodie sweater
sweatshirt jumper cardigan hat cap beanie boots shoes sneakers socks scarf gloves
suit vest waistcoat shorts leggings top tank polo gown robe kimono uniform jersey
flower flowers floral rose roses daisy daisies tulip tulips lily lilies sunflower
leaf leaves tree trees star stars heart hearts skull skulls dragon dragons tiger
tigers lion lions wolf wolves bird birds butterfly butterflies fish snake snakes
eagle crown anchor moon sun cloud clouds mountain mountains wave waves fire flame
flames diamond diamonds circle circles square squares triangle triangles stripe
stripes striped dot dots dotted polka check checkered checked plaid geometric
abstract pattern patterns print prints printed logo logos text letter letters
number numbers smiley face faces emoji palm wing wings feather feathers crystal
big small large tiny mini cute cool simple fancy vintage retro modern classic
summer winter spring autumn fall casual formal sporty elegant minimal solid plain
soft warm cozy oversized fitted slim baggy long short sleeve sleeves collar pocket
""".split())


def _looks_english(text: str) -> bool:
    """Metin GÜVENLE İngilizce mi? Öyleyse TR->EN çevirisi atlanmalı.

    Kural: Türkçe'ye özgü harf yoksa VE alfabetik token'ların en az yarısı
    İngilizce sözlükteyse İngilizcedir. Belirsiz/Türkçe → False (çeviriye gider,
    eski davranış korunur)."""
    if not text or any(c in _TR_CHARS for c in text):
        return False
    tokens = re.findall(r"[a-z]+", text.lower())
    if not tokens:
        return False
    known = sum(1 for w in tokens if w in _EN_WORDS)
    return known >= 1 and known * 2 >= len(tokens)


def _backend_name() -> str:
    return (get_settings().translate_backend or "argos").lower()


def _translate_argos(text: str) -> str:
    import argostranslate.translate as a
    return a.translate(text, "tr", "en").strip()


def _translate_opus(text: str) -> str:
    if "model" not in _opus_cache:
        from transformers import MarianMTModel, MarianTokenizer
        name = "Helsinki-NLP/opus-mt-tr-en"
        _opus_cache["tok"] = MarianTokenizer.from_pretrained(name)
        _opus_cache["model"] = MarianMTModel.from_pretrained(name)
    tok = _opus_cache["tok"]
    model = _opus_cache["model"]
    enc = tok([text], return_tensors="pt", padding=True)
    gen = model.generate(**enc)
    return tok.batch_decode(gen, skip_special_tokens=True)[0].strip()


def translate_tr_to_en(text: str) -> str:
    text = (text or "").strip()
    if not text:
        return text
    _mod = sys.modules[__name__]
    # Zaten İngilizce olan metni TR->EN modeline verme: tek yönlü opus-mt
    # İngilizceyi bozuyor ('yellow flower' -> 'windlow flower'), rengi/anlamı
    # yok ediyor. Türkçe ve belirsiz girdiler eskisi gibi çevrilir.
    if _mod._looks_english(text):
        return text
    try:
        if _mod._backend_name() == "opus":
            out = _mod._translate_opus(text)
        else:
            out = _mod._translate_argos(text)
        return out or text
    except Exception:
        return text
