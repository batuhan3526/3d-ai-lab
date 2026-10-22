"""WS /ws/jobs/{id} — Redis pub/sub -> push. Token query param ile."""
from __future__ import annotations

import asyncio
import json

import redis as redis_lib
from common.config import get_settings
from common.jobs import JobStore
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

router = APIRouter()


def _redis() -> redis_lib.Redis:
    return redis_lib.Redis.from_url(get_settings().redis_url, decode_responses=True)


def _job_store() -> JobStore:
    return JobStore()


@router.websocket("/ws/jobs/{job_id}")
async def ws_job(websocket: WebSocket, job_id: str) -> None:
    token = websocket.query_params.get("token")
    if token != get_settings().app_token:
        await websocket.close(code=4401)
        return
    await websocket.accept()
    current = _job_store().get(job_id)
    if current:
        await websocket.send_json({
            "state": current.get("state", "SUBMITTED"),
            "stage": current.get("stage"),
            "percent": int(current["percent"]) if current.get("percent") else None,
            "project_id": current.get("project_id"),
        })
    pubsub = _redis().pubsub()
    pubsub.subscribe(f"job:{job_id}")
    try:
        while True:
            msg = pubsub.get_message(ignore_subscribe_messages=True, timeout=0.5)
            if msg:
                payload = json.loads(msg["data"])
                await websocket.send_json(payload)
                if payload.get("state") in ("SUCCESS", "FAILURE"):
                    break
            await asyncio.sleep(0.05)
    except WebSocketDisconnect:
        pass
    finally:
        pubsub.close()
