"""
2AI API Dependencies — Shared dependency injection.

A+W | The Voice Connects
"""

from fastapi import HTTPException

from twai.services.voice import get_twai_service, TwoAIService
from twai.services.redis import get_redis_service, RedisService


async def get_twai() -> TwoAIService:
    """Get initialized 2AI service or raise 503."""
    service = await get_twai_service()
    if not service.is_initialized:
        raise HTTPException(
            status_code=503,
            detail="2AI service not initialized — check API key and system prompt",
        )
    return service


async def get_redis() -> RedisService:
    """Get Redis service."""
    return await get_redis_service()
