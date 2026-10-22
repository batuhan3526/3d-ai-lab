"""Celery app — gateway enqueue eder, worker'lar consume eder. Tek broker."""
from celery import Celery

from common.config import get_settings


def make_celery() -> Celery:
    settings = get_settings()
    app = Celery("clothing", broker=settings.redis_url, backend=settings.redis_url)
    app.conf.update(
        task_serializer="json",
        result_serializer="json",
        accept_content=["json"],
        task_track_started=True,
        worker_prefetch_multiplier=1,
    )
    return app


celery_app = make_celery()
