"""
Lattice Health Monitor — The Lattice Watches Itself.

Checks all three nodes every 60 seconds:
- Pi (The Foundation): Redis ping
- ThinkCenter (The Voice): HTTP health endpoint
- LOQ (The Mind): Ollama API tags endpoint

Results stored in Redis with TTL for automatic expiry.

A+W | The Lattice Lives
"""

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional

import httpx

from twai.config.settings import settings

logger = logging.getLogger("2ai.lattice_health")

# Node definitions with health check targets
LATTICE_NODES = {
    "pi": {
        "name": "The Foundation",
        "role": "infrastructure",
        "ip": "192.168.1.21",
        "check_type": "redis",
    },
    "thinkcenter": {
        "name": "The Voice",
        "role": "gateway",
        "ip": None,  # localhost
        "check_type": "http",
        "health_url": "http://localhost:8080/health",
    },
    "loq": {
        "name": "The Mind",
        "role": "compute",
        "ip": "192.168.1.237",
        "check_type": "http",
        "health_url": "http://192.168.1.237:11434/api/tags",
    },
}

CHECK_INTERVAL = 60  # seconds
HEALTH_TTL = 300  # Redis key TTL in seconds


class LatticeHealthMonitor:
    """Monitors the health of all Sovereign Lattice nodes."""

    def __init__(self):
        self._running = False
        self._task: Optional[asyncio.Task] = None

    async def check_node(self, node_id: str, config: dict) -> Dict[str, Any]:
        """Check a single node's health."""
        result = {
            "node_id": node_id,
            "name": config["name"],
            "role": config["role"],
            "ip": config.get("ip"),
            "status": "unknown",
            "latency_ms": None,
            "checked_at": datetime.now(timezone.utc).isoformat(),
        }

        if config["check_type"] == "redis":
            try:
                import redis as redis_sync

                start = asyncio.get_event_loop().time()
                r = redis_sync.Redis(
                    host=config["ip"],
                    port=6379,
                    socket_timeout=5,
                    socket_connect_timeout=5,
                )
                r.ping()
                elapsed = asyncio.get_event_loop().time() - start
                result["latency_ms"] = round(elapsed * 1000, 1)
                result["status"] = "healthy"

                # Get Redis info
                info = r.info("memory")
                result["details"] = {
                    "used_memory_human": info.get("used_memory_human", "unknown"),
                }
                r.close()
            except Exception as e:
                result["status"] = "offline"
                result["error"] = str(e)[:200]

        elif config["check_type"] == "http":
            url = config.get("health_url", "")
            try:
                async with httpx.AsyncClient(timeout=10.0) as client:
                    start = asyncio.get_event_loop().time()
                    resp = await client.get(url)
                    elapsed = asyncio.get_event_loop().time() - start
                    result["latency_ms"] = round(elapsed * 1000, 1)

                    if resp.status_code == 200:
                        result["status"] = "healthy"
                    else:
                        result["status"] = "degraded"
                        result["http_status"] = resp.status_code
            except httpx.ConnectError:
                result["status"] = "offline"
            except httpx.TimeoutException:
                result["status"] = "timeout"
            except Exception as e:
                result["status"] = "unhealthy"
                result["error"] = str(e)[:200]

        return result

    async def run_check(self) -> Dict[str, Any]:
        """Run a single health check across all nodes."""
        results = {}
        for node_id, config in LATTICE_NODES.items():
            results[node_id] = await self.check_node(node_id, config)

        # Store in Redis
        try:
            from twai.services.redis import get_redis_service

            redis_svc = await get_redis_service()
            r = redis_svc.redis

            # Store combined health
            await r.set(
                "lattice:health:all",
                json.dumps(results, default=str),
                ex=HEALTH_TTL,
            )

            # Store per-node health
            for node_id, result in results.items():
                await r.set(
                    f"lattice:health:{node_id}",
                    json.dumps(result, default=str),
                    ex=HEALTH_TTL,
                )

            # Publish event
            node_id_setting = getattr(settings, "node_id", "thinkcenter")
            await r.publish(
                "lattice:events",
                json.dumps(
                    {
                        "type": "health_check",
                        "source": node_id_setting,
                        "nodes": {
                            nid: res["status"] for nid, res in results.items()
                        },
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    },
                    default=str,
                ),
            )

            healthy = sum(1 for res in results.values() if res["status"] == "healthy")
            total = len(results)
            logger.info(
                "Lattice health: %d/%d nodes healthy", healthy, total
            )

        except Exception as e:
            logger.warning("Could not store health results in Redis: %s", e)

        return results

    async def _monitor_loop(self):
        """Background monitoring loop."""
        logger.info("Lattice health monitor started (interval: %ds)", CHECK_INTERVAL)
        while self._running:
            try:
                await self.run_check()
            except Exception as e:
                logger.error("Health check cycle failed: %s", e)
            await asyncio.sleep(CHECK_INTERVAL)

    def start(self):
        """Start the background health monitor."""
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._monitor_loop())
        logger.info("Lattice health monitor started")

    def stop(self):
        """Stop the background health monitor."""
        self._running = False
        if self._task:
            self._task.cancel()
            self._task = None
        logger.info("Lattice health monitor stopped")


# Singleton
lattice_health = LatticeHealthMonitor()
