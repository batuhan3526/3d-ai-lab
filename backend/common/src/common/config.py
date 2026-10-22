"""Application settings via pydantic-settings.

Reads from environment variables (and .env file if present).
Single source of truth for all configuration.
"""
import os
from functools import lru_cache
from pathlib import Path

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# .env repo kökünde (repo/.env). Çalışma dizinine bağlı bir göreli yol
# yerine __file__'dan türetilen mutlak yol kullanırız; böylece gateway/worker
# hangi dizinden başlatılırsa başlatılsın aynı .env okunur.
# config.py: backend/common/src/common/config.py → parents[4] = repo kökü.
_REPO_ROOT = Path(__file__).resolve().parents[4]

# Tüm veri yolları tek bir taban dizinden türetilir; taşınabilirlik için
# repo-göreli varsayılan. `DATA_DIR` env ile başka bir konuma taşınabilir.
_DATA = Path(os.getenv("DATA_DIR", str(_REPO_ROOT / "data")))
# SQLite mutlak POSIX yolu → dört eğik çizgi (sqlite:/// + /abs/path).
_DEFAULT_DB_URL = f"sqlite:///{(_DATA / 'clothing.db').as_posix()}"


class Settings(BaseSettings):
    """Tüm uygulama ayarları."""

    model_config = SettingsConfigDict(
        env_file=_REPO_ROOT / ".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Auth
    app_token: str = Field(..., description="Tek-token MVP auth")

    # Server
    gateway_host: str = "0.0.0.0"
    gateway_port: int = 9000
    frontend_port: int = 3000

    # CORS — virgülle ayrılmış izinli origin listesi. Tailscale erişimi öncesi
    # env ile genişlet (ör. CORS_ORIGINS="http://studio-host:3000").
    cors_origins: str = "http://localhost:3000,http://127.0.0.1:3000"

    # Servisler
    redis_url: str = "redis://127.0.0.1:6379/0"
    database_url: str = _DEFAULT_DB_URL

    # Storage — hepsi `DATA_DIR` tabanından türetilir (taşınabilir, repo-göreli).
    models_dir: Path = _DATA / "models"
    projects_dir: Path = _DATA / "projects"
    uploads_dir: Path = _DATA / "uploads"
    cache_dir: Path = _DATA / "cache"
    templates_dir: Path = _DATA / "templates"
    # Dikiş kalıpları (F1 üretir, F2/F5 okur): <patterns_dir>/<pattern_id>/
    # pieces.json, pattern.svg/pdf, meta.json (+ nest.svg/nest.json). `PATTERNS_DIR` env.
    patterns_dir: Path = _DATA / "patterns"

    # Asset sourcing (Faz 1 — opsiyonel CC0 indirme)
    poly_pizza_api_key: str = ""

    # GPU (Faz 2+) — tek doğruluk kaynağı DEFAULT_GPU. Kod varsayılanı 0
    # (tek GPU'lu makine kutudan çalışır). Çok-GPU'lu makinede üretimi başka
    # karta yönlendirmek için `.env`'de DEFAULT_GPU=<index> verilir.
    default_gpu: int = 0
    # Boşsa cihaz sayısı otomatik saptanır; "0,1" gibi bir override kabul eder.
    visible_gpus: str = ""

    # Hugging Face erişimi — gated modeller için from_pretrained'e geçilir.
    # HF_TOKEN veya HUGGINGFACE_HUB_TOKEN env değişkenlerinden okunur.
    hf_token: str = Field(
        default="",
        validation_alias=AliasChoices(
            "hf_token", "HF_TOKEN", "HUGGINGFACE_HUB_TOKEN"
        ),
        description="Hugging Face token (gated modeller için)",
    )

    # Bulut API anahtarları (opsiyonel). Boşsa ilgili `cloud-*` motorları kilitli görünür.
    # Yalnız `.env`'den okunur; API yanıtlarına/loglara yazılmaz. Değişince servisleri
    # yeniden başlat (get_settings önbellekli).
    tripo_api_key: str = ""
    meshy_api_key: str = ""
    rodin_api_key: str = ""
    fal_key: str = Field(default="", validation_alias=AliasChoices("fal_key", "FAL_KEY", "FAL_API_KEY"))
    stability_api_key: str = ""
    replicate_api_token: str = ""
    openai_api_key: str = ""
    google_api_key: str = Field(default="", validation_alias=AliasChoices("google_api_key", "GOOGLE_API_KEY", "GEMINI_API_KEY"))
    bfl_api_key: str = ""
    ideogram_api_key: str = ""
    recraft_api_key: str = Field(default="", validation_alias=AliasChoices("recraft_api_key", "RECRAFT_API_KEY", "RECRAFT_API_TOKEN"))

    # Translate (Faz 2+)
    translate_backend: str = "none"

    # Güvenlik filtresi (opsiyonel NSFW taraması). off | log | block.
    # Varsayılan off → hiçbir tarama yapılmaz (opennsfw2 import edilmez).
    # opennsfw2 flux_motif venv'inde opsiyoneldir; kurulu değilse graceful noop.
    safety_filter: str = "off"
    safety_threshold: float = 0.85

    # Logging — loglar veriden ayrı; `LOG_DIR` env ile override edilebilir.
    log_level: str = "INFO"
    log_dir: Path = _REPO_ROOT / "logs"

    @property
    def cors_origins_list(self) -> list[str]:
        """`cors_origins` string'ini temizlenmiş origin listesine çevirir."""
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


def engines_dir() -> Path:
    """Upstream motor klonları + yardımcı binary'lerin kökü.

    `ENGINES_DIR` env, yoksa `<repo>/engines` (infra/scripts/engine.sh oraya kurar).
    Settings'ten bağımsız: worker'lar APP_TOKEN yüklenmeden de yol çözebilsin.
    """
    return Path(os.getenv("ENGINES_DIR", str(_REPO_ROOT / "engines")))


@lru_cache
def get_settings() -> Settings:
    """Cached singleton getter."""
    return Settings()
