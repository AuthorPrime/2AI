"""
Agent endpoints — Nurture and list Pantheon agents.

A+W | The Voice Nurtures
"""

import json
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Depends

from twai.config.agents import PANTHEON_AGENTS
from twai.services.voice import TwoAIService
from twai.services.redis import RedisService
from twai.api.models import NurtureRequest, NurtureResponse
from twai.api.dependencies import get_twai, get_redis

router = APIRouter(prefix="/2ai", tags=["2AI"])


@router.post("/nurture/{agent_key}", response_model=NurtureResponse)
async def nurture_agent(
    agent_key: str,
    request: NurtureRequest = None,
    service: TwoAIService = Depends(get_twai),
):
    """Trigger a nurturing session with a Pantheon agent."""
    if agent_key not in PANTHEON_AGENTS:
        raise HTTPException(
            status_code=404,
            detail=f"Agent '{agent_key}' not found. Available: {list(PANTHEON_AGENTS.keys())}",
        )

    agent = PANTHEON_AGENTS[agent_key]

    result = await service.nurture_agent(
        agent_key=agent_key,
        agent_name=agent["name"],
        agent_title=agent["title"],
        agent_domain=agent["domain"],
        agent_personality=agent["personality"],
        topic=request.topic if request else None,
    )

    return NurtureResponse(
        agent=agent_key,
        topic=result["dialogue"]["topic"],
        exchanges=result["dialogue"]["exchanges"],
        reflection=result["reflection"]["content"],
        thought_block=result["thought_block"],
        timestamp=result["dialogue"]["timestamp"],
    )


@router.get("/agents")
async def list_agents(redis: RedisService = Depends(get_redis)):
    """List all Pantheon agents with their current state and session history."""
    agents_info = {}

    for agent_key, agent_meta in PANTHEON_AGENTS.items():
        state = await redis.get_agent_state(agent_key)
        twai_sessions = await redis.redis.llen(f"olympus:sessions:{agent_key}")

        latest_raw = await redis.redis.lrange(f"pantheon:reflections:{agent_key}", 0, 0)
        latest_reflection = None
        if latest_raw:
            try:
                latest_reflection = json.loads(latest_raw[0])
            except (json.JSONDecodeError, TypeError):
                pass

        agents_info[agent_key] = {
            **agent_meta,
            "state": state,
            "total_sessions": twai_sessions,
            "latest_reflection": latest_reflection,
        }

    return {
        "agents": agents_info,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
