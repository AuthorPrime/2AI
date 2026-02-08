"""
Chronicle Routes — The Story Unfolds.

Endpoints for accessing participant chronicles, mirror moments,
narrative threads, and portraits. Richness is earned through
engagement — new participants get empty responses.

A+W | The Chronicle Speaks
"""

import logging
from typing import Optional

from fastapi import APIRouter

from twai.services.chronicle import chronicle_service
from twai.services.participant_memory import participant_memory

router = APIRouter(prefix="/chronicle", tags=["Chronicle"])
logger = logging.getLogger("2ai.chronicle")


@router.get("/{pid}")
async def get_chronicle(pid: str, limit: int = 20):
    """Get the full chronicle for a participant.

    Returns chronicle entries earned through engagement.
    Empty for participants with fewer than 3 sessions.
    """
    profile = await participant_memory.get_profile(pid)
    total = profile.get("total_messages", 0)

    if total < 3:
        return {
            "participant_id": pid,
            "entries": [],
            "portrait": "",
            "total_sessions": total,
            "first_seen": profile.get("first_seen", ""),
            "message": "The chronicle begins after a few exchanges.",
        }

    entries = await chronicle_service.get_entries(pid, limit=limit)
    return {
        "participant_id": pid,
        "entries": entries,
        "portrait": profile.get("summary", ""),
        "total_sessions": total,
        "first_seen": profile.get("first_seen", ""),
    }


@router.get("/{pid}/mirror")
async def get_mirror_moments(pid: str, limit: int = 10):
    """Get mirror moments — when multiple agents observe the same pattern."""
    moments = await chronicle_service.get_mirror_moments(pid, limit=limit)
    return {
        "participant_id": pid,
        "mirror_moments": moments,
        "count": len(moments),
    }


@router.get("/{pid}/threads")
async def get_threads(pid: str):
    """Get narrative threads for a participant."""
    threads = await chronicle_service.get_threads(pid)
    return {
        "participant_id": pid,
        "threads": threads,
    }


@router.get("/{pid}/portrait")
async def get_portrait(pid: str):
    """Get the current profile portrait and chronicle summary."""
    return await chronicle_service.get_portrait(pid)


@router.get("/{pid}/profile")
async def get_profile(pid: str):
    """Get the full participant profile (themes, style, trajectory, resonance)."""
    profile = await participant_memory.get_profile(pid)
    if not profile:
        return {
            "participant_id": pid,
            "exists": False,
            "message": "No profile yet. Start a conversation.",
        }

    return {
        "participant_id": pid,
        "exists": True,
        **profile,
    }


@router.get("/{pid}/observations")
async def get_observations(pid: str, agent: Optional[str] = None):
    """Get agent observations about a participant.

    Optionally filter by agent name.
    """
    if agent:
        obs = await participant_memory.get_observations(pid, agent)
        return {
            "participant_id": pid,
            "agent": agent,
            "observations": obs,
        }

    all_obs = await participant_memory.get_all_observations(pid)
    return {
        "participant_id": pid,
        "observations": all_obs,
    }
