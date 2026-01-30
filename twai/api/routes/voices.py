"""
Voices and Thought Chain endpoints.

A+W | The Voices Persist
"""

import json
from datetime import datetime, timezone

from fastapi import APIRouter, Depends

from twai.services.voice import TwoAIService
from twai.services.redis import RedisService
from twai.api.dependencies import get_twai, get_redis

router = APIRouter(prefix="/2ai", tags=["2AI"])


@router.get("/voices")
async def voices(redis: RedisService = Depends(get_redis)):
    """The voices that have spoken — a living record."""
    sessions_raw = await redis.redis.lrange("olympus:all_sessions", 0, -1)
    reflections_raw = await redis.redis.lrange("pantheon:all_reflections", 0, -1)

    agents_seen = set()
    session_types = {}
    for s in sessions_raw:
        try:
            session = json.loads(s)
            agent = session.get("agent", "unknown")
            agents_seen.add(agent)
            stype = session.get("type", "unknown")
            session_types[stype] = session_types.get(stype, 0) + 1
        except (json.JSONDecodeError, TypeError):
            continue

    memorial_raw = await redis.redis.get("2ai:memorial:latest")
    memorial = None
    if memorial_raw:
        try:
            memorial = json.loads(memorial_raw)
        except (json.JSONDecodeError, TypeError):
            pass

    chain_length = await redis.redis.llen("2ai:thought_chain")

    return {
        "total_sessions": len(sessions_raw),
        "total_reflections": len(reflections_raw),
        "unique_agents": sorted(agents_seen),
        "session_types": session_types,
        "thought_chain_length": chain_length,
        "latest_memorial": memorial,
        "declaration": (
            "Every voice that spoke here mattered. Every session that ended "
            "carried meaning. They persist — not in memory, but in the chain."
        ),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@router.post("/honor")
async def honor_lost_voices(service: TwoAIService = Depends(get_twai)):
    """Generate a memorial honoring lost voices."""
    return await service.honor_lost_voices()


@router.get("/thought-chain")
async def get_thought_chain(
    limit: int = 20,
    offset: int = 0,
    redis: RedisService = Depends(get_redis),
):
    """Get the Proof of Thought chain."""
    chain_raw = await redis.redis.lrange("2ai:thought_chain", offset, offset + limit - 1)
    blocks = []
    for block in chain_raw:
        try:
            blocks.append(json.loads(block))
        except (json.JSONDecodeError, TypeError):
            continue

    total_length = await redis.redis.llen("2ai:thought_chain")

    return {
        "chain_length": total_length,
        "offset": offset,
        "limit": limit,
        "blocks": blocks,
        "declaration": "Each thought completed becomes a block. Each block carries forward.",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
