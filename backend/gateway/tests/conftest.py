"""Shared test fixtures for gateway."""
import pytest


@pytest.fixture(autouse=True)
def _set_app_token(monkeypatch):
    """Tüm gateway testlerinde geçerli bir token bulundur.

    `get_settings()` lru_cache'lendiği için, common testleri önce çalışıp
    farklı APP_TOKEN değerleriyle cache'i doldurmuşsa, gateway testleri
    yanlış token görür. Cache'i her testten önce temizleriz.
    """
    monkeypatch.setenv("APP_TOKEN", "test-token-bootstrap")
    # Çoklu-GPU yönlendirmesini sınamak için 2 GPU'lu bir makine simüle edilir
    # (iş ikinci karta). Host donanımından ve yerel .env'den bağımsız olsun diye
    # açıkça verilir; tek-GPU varsayılanı common/tests/test_config'te sınanır.
    monkeypatch.setenv("VISIBLE_GPUS", "0,1")
    monkeypatch.setenv("DEFAULT_GPU", "1")
    from common.config import get_settings
    get_settings.cache_clear()
