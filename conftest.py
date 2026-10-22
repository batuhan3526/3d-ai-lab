"""Kök pytest konfigürasyonu — tüm backend paketleri için paylaşılan fixture'lar."""
import os

import pytest

# Worker modülleri import anında celery_app → Settings kurar; APP_TOKEN zorunlu.
# Temiz klonda (.env yokken) tüm testler tek komutla koşabilsin diye.
os.environ.setdefault("APP_TOKEN", "test-token-bootstrap")

# Testler yerel .env'den (port, CORS, GPU, yollar) bağımsız olsun: Settings yalnız
# ortam değişkenlerini ve kod varsayılanlarını okusun.
from common.config import Settings  # noqa: E402

Settings.model_config["env_file"] = None
import structlog


@pytest.fixture(autouse=True)
def _clear_settings_cache():
    """Test izolasyonu: get_settings() lru_cache'lidir. Bir test farklı env ile
    cache'i doldurursa sonraki test stale değer görür. Her testten önce/sonra temizle.
    """
    from common.config import get_settings
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture(autouse=True)
def _reset_structlog():
    """Test izolasyonu: structlog global bir singleton'dır.

    common/logging.py production'da `configure_logging()`'i bir kez gerçek
    stdout ile çağırır (doğru). Ama testlerde `test_logging` bunu capsys'in
    geçici stdout'una çağırıp `cache_logger_on_first_use=True` ile cache'ler;
    bu durum sonraki testlere sızıp log emit eden modüllerde
    "I/O operation on closed file" hatasına yol açar. Her testten önce/sonra
    reset_defaults() ile global yapılandırmayı temizleyerek bunu önleriz.
    """
    structlog.reset_defaults()
    yield
    structlog.reset_defaults()
