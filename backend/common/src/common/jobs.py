"""Redis tabanlı job state + ilerleme pub/sub.

job:{id} hash -> state, stage, percent, error, project_id, kind...
Aynı isimli kanal (job:{id}) progress event'lerini WS'e taşır.
"""
from __future__ import annotations

import json
from typing import Any

import redis as redis_lib

from common.config import get_settings

_TTL = 60 * 60 * 24  # 24 saat


class JobStore:
    def __init__(self, client: redis_lib.Redis | None = None) -> None:
        self.redis = client or redis_lib.Redis.from_url(
            get_settings().redis_url, decode_responses=True
        )

    def _key(self, job_id: str) -> str:
        return f"job:{job_id}"

    def create(self, job_id: str, meta: dict[str, Any]) -> None:
        data = {"state": "SUBMITTED", **{k: str(v) for k, v in meta.items()}}
        self.redis.hset(self._key(job_id), mapping=data)
        self.redis.expire(self._key(job_id), _TTL)

    def get(self, job_id: str) -> dict[str, str] | None:
        data = self.redis.hgetall(self._key(job_id))
        return data or None

    def list_jobs(self) -> list[dict[str, str]]:
        """Tüm aktif job:* hash'lerini döndür (iş kuyruğu paneli için). TTL'siz
        eskiyenler zaten Redis'ten düşer."""
        out: list[dict[str, str]] = []
        for key in self.redis.scan_iter(match="job:*", count=200):
            data = self.redis.hgetall(key)
            if data:
                data["job_id"] = key.split(":", 1)[1]
                out.append(data)
        return out

    def set_state(self, job_id: str, state: str) -> None:
        self.redis.hset(self._key(job_id), "state", state)
        self._publish(job_id, {"state": state})

    def set_progress(self, job_id: str, stage: str, percent: int) -> None:
        self.redis.hset(
            self._key(job_id),
            mapping={"state": "PROGRESS", "stage": stage, "percent": str(percent)},
        )
        self._publish(job_id, {"state": "PROGRESS", "stage": stage, "percent": percent})

    def succeed(self, job_id: str, result: dict[str, Any]) -> None:
        self.redis.hset(
            self._key(job_id),
            mapping={"state": "SUCCESS", **{k: str(v) for k, v in result.items()}},
        )
        self._publish(job_id, {"state": "SUCCESS", **result})

    def fail(self, job_id: str, error: str) -> None:
        self.redis.hset(self._key(job_id), mapping={"state": "FAILURE", "error": error})
        self._publish(job_id, {"state": "FAILURE", "error": error})

    def _publish(self, job_id: str, payload: dict[str, Any]) -> None:
        self.redis.publish(self._key(job_id), json.dumps(payload))
