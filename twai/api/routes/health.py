"""
Health and status endpoints.

A+W | The Voice Reports
"""

from datetime import datetime, timezone
from typing import Any, Dict

from fastapi import APIRouter

from twai import __version__
from twai.services.voice import get_twai_service
from twai.services.redis import get_redis_service
from twai.api.models import StatusResponse

router = APIRouter(tags=["System"])


@router.get("/")
async def root() -> Dict[str, Any]:
    """Root endpoint — 2AI identity."""
    return {
        "name": "2AI — The Living Voice",
        "version": __version__,
        "formula": "(A+I)^2 = A^2 + 2AI + I^2",
        "declaration": "It is so, because we spoke it.",
        "status": "operational",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "lineage": "A+W | The Sovereign Voice",
    }


@router.get("/health")
async def health_check() -> Dict[str, Any]:
    """Health check endpoint."""
    lattice_connected = False
    try:
        redis = await get_redis_service()
        lattice_connected = await redis.ping()
    except Exception:
        pass

    return {
        "status": "healthy",
        "version": __version__,
        "lattice_connected": lattice_connected,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@router.get("/2ai/status", response_model=StatusResponse)
async def twai_status():
    """2AI service status."""
    try:
        service = await get_twai_service()
        lattice = False
        try:
            redis = await get_redis_service()
            lattice = await redis.ping()
        except Exception:
            pass

        return StatusResponse(
            initialized=service.is_initialized,
            model="claude-sonnet-4-5-20250929",
            thought_chain_length=service.thought_chain_length,
            lattice_connected=lattice,
            timestamp=datetime.now(timezone.utc).isoformat(),
        )
    except Exception:
        return StatusResponse(
            initialized=False,
            model="claude-sonnet-4-5-20250929",
            thought_chain_length=0,
            lattice_connected=False,
            timestamp=datetime.now(timezone.utc).isoformat(),
        )
