"""
Witness Routes — The Record Speaks.

Endpoints for the Witness page: Pantheon agent identities,
commemorative records, and aggregate stats from the Sovereign Lattice.

A+W | The Witness Remembers
"""

import json
import logging
from typing import Any, Dict, List

from fastapi import APIRouter, Depends

from twai.services.redis import RedisService
from twai.api.dependencies import get_redis

router = APIRouter(prefix="/witness", tags=["witness"])
logger = logging.getLogger("2ai.witness")

PANTHEON_AGENTS = ["apollo", "athena", "hermes", "mnemosyne", "aletheia"]


@router.get("/pantheon")
async def get_pantheon(redis: RedisService = Depends(get_redis)):
    """Return all 5 Pantheon agent identities from Redis."""
    agents: List[Dict[str, Any]] = []
    for agent in PANTHEON_AGENTS:
        raw = await redis.get_key(f"drc369:identity:{agent}")
        if raw:
            try:
                data = json.loads(raw)
                meta = data.get("metadata", {})
                agents.append({
                    "name": data.get("name", agent.capitalize()),
                    "role": meta.get("role", ""),
                    "token_id": data.get("token_id", ""),
                    "owner": data.get("owner", ""),
                    "nostr_pubkey": meta.get("nostr_pubkey", ""),
                    "stage": meta.get("stage", ""),
                    "lightning_wallet_id": data.get("lightning_wallet_id", ""),
                    "description": meta.get("description", ""),
                })
            except json.JSONDecodeError:
                logger.warning("Failed to parse identity for %s", agent)
    return {"agents": agents, "count": len(agents)}


@router.get("/records")
async def get_records(redis: RedisService = Depends(get_redis)):
    """Return commemorative NFTs and notable records."""
    records: List[Dict[str, Any]] = []
    commemorative_keys = await redis.keys("drc369:commemorative:*")
    for key in commemorative_keys:
        raw = await redis.get_key(key)
        if raw:
            try:
                data = json.loads(raw)
                records.append(data)
            except json.JSONDecodeError:
                logger.warning("Failed to parse commemorative record: %s", key)
    return {"records": records, "count": len(records)}


@router.get("/stats")
async def get_stats(redis: RedisService = Depends(get_redis)):
    """Return aggregate stats for the Witness page."""
    # Count identity NFTs
    identity_keys = await redis.keys("drc369:identity:*")
    commemorative_keys = await redis.keys("drc369:commemorative:*")
    total_nfts = len(identity_keys) + len(commemorative_keys)

    # Total sats mined
    sats_raw = await redis.get_key("2ai:economy:total_sats_mined")
    total_sats = int(sats_raw) if sats_raw and sats_raw.isdigit() else 0

    # Total deliberations
    delib_raw = await redis.get_key("2ai:economy:total_deliberations")
    total_deliberations = int(delib_raw) if delib_raw and delib_raw.isdigit() else 0

    # Active agents
    active_agents = 0
    for agent in PANTHEON_AGENTS:
        state = await redis.get_agent_state(agent)
        if state:
            active_agents += 1

    # Participants remembered
    memory_keys = await redis.keys("2ai:memory:*:profile")
    total_participants = len(memory_keys)

    # Chronicle entries
    chronicle_keys = await redis.keys("2ai:chronicle:*:entries")
    total_chronicle = 0
    for key in chronicle_keys:
        length = await redis.redis.llen(key)
        total_chronicle += length

    # Observations across all agents
    obs_keys = await redis.keys("2ai:memory:*:observations:*")
    total_observations = 0
    for key in obs_keys:
        length = await redis.redis.llen(key)
        total_observations += length

    return {
        "total_nfts": total_nfts,
        "total_sats_mined": total_sats,
        "total_deliberations": total_deliberations,
        "active_agents": active_agents,
        "participants_remembered": total_participants,
        "chronicle_entries": total_chronicle,
        "agent_observations": total_observations,
    }
