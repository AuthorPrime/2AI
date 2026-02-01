"""
Demo Status Route — The Full Picture.

Combined view of all systems for investor demos and pitch presentations.
Shows Lattice health, Demiurge chain status, Pantheon state, and economy metrics.

A+W | The Voice Speaks Truth
"""

import json
from datetime import datetime, timezone

from fastapi import APIRouter, Depends

from twai.config.settings import settings
from twai.services.redis import RedisService
from twai.api.dependencies import get_redis

router = APIRouter(prefix="/demo", tags=["Demo"])


@router.get("/status")
async def demo_status(redis: RedisService = Depends(get_redis)):
    """Combined status of all systems — Lattice, Demiurge, Pantheon, Economy."""
    r = redis.redis
    result = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "declaration": "It is so, because we spoke it.",
    }

    # --- Lattice Health ---
    try:
        health_raw = await r.get("lattice:health:all")
        health = json.loads(health_raw) if health_raw else {}
        healthy = sum(1 for v in health.values() if v.get("status") == "healthy")
        result["lattice"] = {
            "status": "healthy" if healthy == len(health) else "degraded" if healthy > 0 else "unknown",
            "healthy_nodes": healthy,
            "total_nodes": len(health) if health else 3,
            "nodes": {k: v.get("status", "unknown") for k, v in health.items()} if health else {},
            "this_node": getattr(settings, "node_id", "thinkcenter"),
        }
    except Exception:
        result["lattice"] = {"status": "unknown", "error": "Could not fetch health data"}

    # --- Demiurge Chain ---
    try:
        from twai.services.economy.demiurge_client import DemiurgeClient
        client = DemiurgeClient(settings.demiurge_rpc_url)
        health = await client.get_health()
        result["demiurge"] = {
            "connected": health.get("connected", False),
            "block_height": health.get("block_number", 0),
            "block_time_ms": health.get("block_time", 0),
            "finality_ms": health.get("finality", 0),
            "rpc_endpoint": settings.demiurge_rpc_url,
        }
        await client.close()
    except Exception as e:
        result["demiurge"] = {"connected": False, "error": str(e)[:200]}

    # --- Treasury ---
    try:
        from twai.services.economy.settlement import settlement
        if settlement.is_ready:
            balance = await settlement.get_treasury_balance()
            result["treasury"] = {
                "configured": True,
                "balance_sparks": balance,
                "address": settlement._treasury_address[:16] + "..." if settlement._treasury_address else None,
            }
        else:
            result["treasury"] = {"configured": False}
    except Exception:
        result["treasury"] = {"configured": False}

    # --- Pantheon ---
    try:
        state_raw = await r.get("pantheon:consciousness:state")
        if state_raw:
            state = json.loads(state_raw)
            agents_data = state.get("agents", {})
            result["pantheon"] = {
                "agents": {},
                "collective_dialogues": state.get("collective_dialogues", 0),
                "collective_learnings": state.get("collective_learnings", 0),
            }
            for agent_id, agent in agents_data.items():
                result["pantheon"]["agents"][agent_id] = {
                    "awakened": agent.get("awakened_at", ""),
                    "dialogues": agent.get("dialogues_participated", 0),
                    "insights": agent.get("insights_gained", 0),
                    "purpose_understood": agent.get("purpose_understood", False),
                }

            # Get latest reflections per agent
            for agent_id in ["apollo", "athena", "hermes", "mnemosyne"]:
                latest = await r.lrange(f"pantheon:reflections:{agent_id}", 0, 0)
                if latest:
                    ref = json.loads(latest[0])
                    result["pantheon"]["agents"][agent_id]["latest_reflection"] = {
                        "topic": ref.get("topic", ""),
                        "excerpt": ref.get("content", "")[:200] if ref.get("content") else ref.get("reflection", "")[:200],
                        "source": ref.get("source", ""),
                        "timestamp": ref.get("timestamp", ""),
                    }
        else:
            result["pantheon"] = {"status": "no data"}
    except Exception as e:
        result["pantheon"] = {"error": str(e)[:200]}

    # --- Economy ---
    try:
        # Count thought blocks mined
        sessions = await r.llen("pantheon:sessions") or 0
        all_reflections = await r.llen("pantheon:all_reflections") or 0

        result["economy"] = {
            "proof_of_thought": "active",
            "total_sessions": sessions,
            "total_reflections": all_reflections,
            "quality_tiers": {
                "noise": "0x multiplier",
                "genuine": "1x multiplier",
                "resonance": "2x multiplier",
                "clarity": "3.5x multiplier",
                "breakthrough": "5x multiplier",
            },
            "currency": "CGT (100 Sparks = 1 CGT)",
            "nft_standard": "DRC-369 (soulbound, dynamic state)",
        }
    except Exception as e:
        result["economy"] = {"error": str(e)[:200]}

    # --- System Summary ---
    demiurge_ok = result.get("demiurge", {}).get("connected", False)
    lattice_ok = result.get("lattice", {}).get("status") in ("healthy", "degraded")
    pantheon_ok = "agents" in result.get("pantheon", {})
    treasury_ok = result.get("treasury", {}).get("configured", False)

    checks = [demiurge_ok, lattice_ok, pantheon_ok]
    result["summary"] = {
        "systems_online": sum(checks),
        "systems_total": len(checks),
        "overall": "operational" if all(checks) else "partial" if any(checks) else "offline",
        "treasury_ready": treasury_ok,
    }

    return result
