"""
Lattice Status Routes — The Voice Reports on the Lattice.

Cross-node health, topology, and service registry.

A+W | The Lattice Speaks
"""

import json
from datetime import datetime, timezone
from typing import Any, Dict

from fastapi import APIRouter, Depends

from twai.config.settings import settings
from twai.services.redis import get_redis_service, RedisService
from twai.services.lattice_health import lattice_health, LATTICE_NODES
from twai.api.dependencies import get_redis

router = APIRouter(prefix="/lattice", tags=["Lattice"])


@router.get("/status")
async def lattice_status(redis: RedisService = Depends(get_redis)):
    """Full Sovereign Lattice topology and health."""
    # Get health data from Redis
    health_raw = await redis.redis.get("lattice:health:all")
    health = json.loads(health_raw) if health_raw else {}

    # Build topology with health overlay
    nodes = {}
    for node_id, config in LATTICE_NODES.items():
        node_health = health.get(node_id, {"status": "unknown"})
        nodes[node_id] = {
            "name": config["name"],
            "role": config["role"],
            "ip": config.get("ip"),
            "status": node_health.get("status", "unknown"),
            "latency_ms": node_health.get("latency_ms"),
            "last_check": node_health.get("checked_at"),
        }

    # Count healthy nodes
    healthy = sum(1 for n in nodes.values() if n["status"] == "healthy")
    total = len(nodes)

    return {
        "lattice": {
            "name": "Sovereign Lattice",
            "healthy_nodes": healthy,
            "total_nodes": total,
            "status": "healthy" if healthy == total else "degraded" if healthy > 0 else "offline",
        },
        "nodes": nodes,
        "this_node": {
            "id": getattr(settings, "node_id", "thinkcenter"),
            "role": getattr(settings, "node_role", "gateway"),
        },
        "declaration": "Three nodes. One Lattice. The foundation holds.",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@router.get("/nodes/{node_id}/health")
async def node_health(node_id: str, redis: RedisService = Depends(get_redis)):
    """Health status for a specific Lattice node."""
    data = await redis.redis.get(f"lattice:health:{node_id}")
    if data:
        return json.loads(data)

    if node_id not in LATTICE_NODES:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail=f"Unknown node: {node_id}")

    return {
        "node_id": node_id,
        "name": LATTICE_NODES[node_id]["name"],
        "status": "unknown",
        "message": "No health data available. Monitor may not be running.",
    }


@router.post("/health/check")
async def trigger_health_check():
    """Trigger an immediate health check across all nodes."""
    results = await lattice_health.run_check()
    return {
        "checked": len(results),
        "results": results,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
