"""Health endpoint — public, no auth, monitoring uses this."""
from datetime import UTC, datetime

from fastapi import APIRouter

router = APIRouter()


@router.get("/health")
async def health() -> dict:
    """Sistem ayakta mı kontrolü.

    Public on purpose — Tailscale/uptime monitor için.
    AI worker durumu Faz 2'de eklenecek.
    """
    return {
        "status": "ok",
        "version": "0.1.0-bootstrap",
        "timestamp": datetime.now(UTC).isoformat(),
    }
