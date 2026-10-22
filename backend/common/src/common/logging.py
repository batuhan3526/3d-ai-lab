"""Structlog tabanlı yapısal log altyapısı.

JSON formatında stdout'a (ve istenirse dosyaya) yazar.
"""
import logging
import sys

import structlog


def configure_logging(level: str = "INFO", json_output: bool = True) -> None:
    """Structlog'u uygulama için ayarla. Bir kere çağrılmalı."""
    log_level = getattr(logging, level.upper(), logging.INFO)

    timestamper = structlog.processors.TimeStamper(fmt="iso")

    shared_processors = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        timestamper,
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]

    if json_output:
        renderer = structlog.processors.JSONRenderer()
    else:
        renderer = structlog.dev.ConsoleRenderer(colors=True)

    structlog.configure(
        processors=shared_processors + [renderer],
        wrapper_class=structlog.make_filtering_bound_logger(log_level),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(file=sys.stdout),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    """Bind'lenebilir bir structlog logger döndür."""
    return structlog.get_logger(name)
