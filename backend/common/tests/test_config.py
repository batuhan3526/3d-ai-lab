"""Config layer tests."""
from pathlib import Path

import pytest
from pydantic import ValidationError


def test_settings_loads_defaults(monkeypatch):
    """Settings should load with sane code defaults when no .env provided."""
    monkeypatch.delenv("APP_TOKEN", raising=False)
    monkeypatch.setenv("APP_TOKEN", "test-token-123")

    from common.config import Settings

    # _env_file=None → repo kökündeki gerçek .env yok sayılır; bu test
    # kod varsayılanlarını doğrular (çalıştıranın .env'ine bağlı değil).
    s = Settings(_env_file=None)
    assert s.app_token == "test-token-123"
    assert s.gateway_host == "0.0.0.0"
    assert s.gateway_port == 9000
    assert s.log_level == "INFO"


def test_settings_reads_env(monkeypatch):
    """Settings should pick up env overrides."""
    monkeypatch.setenv("APP_TOKEN", "override-token")
    monkeypatch.setenv("GATEWAY_PORT", "9999")
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")

    from common.config import Settings

    s = Settings()
    assert s.app_token == "override-token"
    assert s.gateway_port == 9999
    assert s.log_level == "DEBUG"


def test_settings_paths_are_absolute(monkeypatch):
    """Path-like settings should be Path objects and honour env overrides."""
    monkeypatch.setenv("APP_TOKEN", "x")
    monkeypatch.setenv("LOG_DIR", "/var/tmp/studio-logs")

    from common.config import Settings

    s = Settings()
    assert isinstance(s.log_dir, Path)
    assert s.log_dir == Path("/var/tmp/studio-logs")


def test_settings_app_token_required(monkeypatch):
    """Missing APP_TOKEN should raise."""
    monkeypatch.delenv("APP_TOKEN", raising=False)

    from common.config import Settings

    # _env_file=None ignores the repo-root .env so this exercises the
    # required-field contract regardless of the caller's working directory.
    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_settings_templates_dir_default(monkeypatch):
    """templates_dir Path olmalı, repo-göreli data/templates'a işaret etmeli."""
    monkeypatch.setenv("APP_TOKEN", "x")

    from common.config import _DATA, Settings

    s = Settings(_env_file=None)
    assert isinstance(s.templates_dir, Path)
    # Repo-göreli, taşınabilir varsayılan (makineye özgü mutlak sabit değil).
    assert s.templates_dir == _DATA / "templates"
    assert s.templates_dir.is_absolute()
    assert s.templates_dir.parts[-2:] == ("data", "templates")
    assert s.poly_pizza_api_key == ""


def test_settings_data_dir_env_relocates_paths(monkeypatch, tmp_path):
    """DATA_DIR tüm veri yollarını tek noktadan taşımalı (taşınabilirlik)."""
    monkeypatch.setenv("APP_TOKEN", "x")
    monkeypatch.setenv("DATA_DIR", str(tmp_path))

    # Module-level _DATA os.getenv'i import anında okuduğu için yeniden yükle.
    import importlib

    import common.config as cfg

    # reload modül sözlüğünü yeniden yazar; diğer modüller (common.patterns vb.) eski
    # get_settings'i tutmaya devam eder. Testten sonra orijinal nesneleri geri koy.
    saved = dict(cfg.__dict__)
    importlib.reload(cfg)
    try:
        s = cfg.Settings(_env_file=None)
        assert s.models_dir == tmp_path / "models"
        assert s.projects_dir == tmp_path / "projects"
        assert s.uploads_dir == tmp_path / "uploads"
        assert s.cache_dir == tmp_path / "cache"
        assert s.templates_dir == tmp_path / "templates"
        assert s.database_url == f"sqlite:///{(tmp_path / 'clothing.db').as_posix()}"
    finally:
        cfg.__dict__.clear()
        cfg.__dict__.update(saved)


def test_settings_new_portability_defaults(monkeypatch):
    """Tek-GPU ve HF alanları sözleşmedeki varsayılanlara sahip olmalı."""
    monkeypatch.setenv("APP_TOKEN", "x")
    monkeypatch.delenv("HF_TOKEN", raising=False)
    monkeypatch.delenv("HUGGINGFACE_HUB_TOKEN", raising=False)
    monkeypatch.delenv("DEFAULT_GPU", raising=False)
    monkeypatch.delenv("VISIBLE_GPUS", raising=False)

    from common.config import Settings

    s = Settings(_env_file=None)
    assert s.default_gpu == 0
    assert s.visible_gpus == ""
    assert s.hf_token == ""
    assert s.translate_backend == "none"
    assert s.database_url.startswith("sqlite:///")


def test_settings_hf_token_aliases(monkeypatch):
    """hf_token HF_TOKEN ve HUGGINGFACE_HUB_TOKEN alias'larından okunmalı."""
    from common.config import Settings

    monkeypatch.setenv("APP_TOKEN", "x")
    monkeypatch.delenv("HF_TOKEN", raising=False)
    monkeypatch.setenv("HUGGINGFACE_HUB_TOKEN", "hf_from_hub_alias")
    assert Settings(_env_file=None).hf_token == "hf_from_hub_alias"

    monkeypatch.setenv("HF_TOKEN", "hf_from_short_alias")
    assert Settings(_env_file=None).hf_token == "hf_from_short_alias"
