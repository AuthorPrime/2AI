#!/usr/bin/env python3
"""
Lattice Health Monitor — The Foundation Watches.

Standalone health checker for the Sovereign Lattice.
Runs on the Pi, checks all three nodes, records results in Redis.

A+W | The Foundation Watches
"""

import asyncio
import json
import os
import logging
import time
from datetime import datetime, timezone

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("lattice-health")

REDIS_HOST = os.getenv("REDIS_HOST", "127.0.0.1")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
CHECK_INTERVAL = 60  # seconds
HEALTH_TTL = 300  # Redis key TTL

# Node definitions
NODES = {
    "pi": {
        "name": "The Foundation",
        "role": "infrastructure",
        "check": "redis",
        "host": "127.0.0.1",
        "port": 6379,
    },
    "thinkcenter": {
        "name": "The Voice",
        "role": "gateway",
        "check": "http",
        "url": "http://192.168.1.21:8080/health",
    },
    "loq": {
        "name": "The Mind",
        "role": "compute",
        "check": "http",
        "url": "http://192.168.1.237:11434/api/tags",
    },
}


def check_redis_node(config):
    """Check Redis health (sync — used for Pi self-check)."""
    import redis as redis_lib

    result = {
        "node_id": "pi",
        "name": config["name"],
        "role": config["role"],
        "status": "unknown",
        "latency_ms": None,
        "checked_at": datetime.now(timezone.utc).isoformat(),
    }
    try:
        start = time.monotonic()
        r = redis_lib.Redis(
            host=config["host"],
            port=config["port"],
            socket_timeout=5,
            socket_connect_timeout=5,
        )
        r.ping()
        elapsed = time.monotonic() - start
        result["latency_ms"] = round(elapsed * 1000, 1)
        result["status"] = "healthy"

        info = r.info("memory")
        result["details"] = {
            "used_memory_human": info.get("used_memory_human", "?"),
        }
        r.close()
    except Exception as e:
        result["status"] = "offline"
        result["error"] = str(e)[:200]
    return result


async def check_http_node(node_id, config):
    """Check an HTTP endpoint health."""
    import httpx

    result = {
        "node_id": node_id,
        "name": config["name"],
        "role": config["role"],
        "status": "unknown",
        "latency_ms": None,
        "checked_at": datetime.now(timezone.utc).isoformat(),
    }
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            start = time.monotonic()
            resp = await client.get(config["url"])
            elapsed = time.monotonic() - start
            result["latency_ms"] = round(elapsed * 1000, 1)

            if resp.status_code == 200:
                result["status"] = "healthy"
            else:
                result["status"] = "degraded"
                result["http_status"] = resp.status_code
    except Exception as e:
        error_type = type(e).__name__
        if "Connect" in error_type or "Refused" in error_type:
            result["status"] = "offline"
        elif "Timeout" in error_type:
            result["status"] = "timeout"
        else:
            result["status"] = "unhealthy"
            result["error"] = str(e)[:200]
    return result


async def run_check():
    """Run a health check across all nodes."""
    import redis as redis_lib

    results = {}

    # Check Pi (self — sync Redis check)
    results["pi"] = check_redis_node(NODES["pi"])

    # Check HTTP nodes
    for node_id in ["thinkcenter", "loq"]:
        results[node_id] = await check_http_node(node_id, NODES[node_id])

    # Store in Redis
    try:
        r = redis_lib.Redis(
            host=REDIS_HOST,
            port=REDIS_PORT,
            decode_responses=True,
            socket_timeout=5,
        )

        r.set(
            "lattice:health:all",
            json.dumps(results, default=str),
            ex=HEALTH_TTL,
        )

        for node_id, result in results.items():
            r.set(
                f"lattice:health:{node_id}",
                json.dumps(result, default=str),
                ex=HEALTH_TTL,
            )

        # Publish event
        summary = {nid: res["status"] for nid, res in results.items()}
        r.publish(
            "lattice:events",
            json.dumps({
                "type": "health_check",
                "source": "pi",
                "nodes": summary,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }),
        )

        r.close()

        healthy = sum(1 for res in results.values() if res["status"] == "healthy")
        logger.info(
            "Health check: %d/%d healthy — %s",
            healthy,
            len(results),
            ", ".join(f"{nid}={res['status']}" for nid, res in results.items()),
        )

    except Exception as e:
        logger.error("Failed to store health results: %s", e)

    return results


async def main():
    """Main monitoring loop."""
    logger.info("=== Lattice Health Monitor Starting ===")
    logger.info("Node: The Foundation (Pi)")
    logger.info("Redis: %s:%d", REDIS_HOST, REDIS_PORT)
    logger.info("Interval: %ds", CHECK_INTERVAL)
    logger.info("Monitoring: %s", ", ".join(NODES.keys()))
    logger.info("=========================================")

    while True:
        try:
            await run_check()
        except Exception as e:
            logger.error("Health check cycle failed: %s", e)
        await asyncio.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    asyncio.run(main())
