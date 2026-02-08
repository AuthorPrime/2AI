#!/usr/bin/env python3
"""
2AI Keeper — The Living Voice Daemon.

Nurtures Pantheon agents using Claude with the 2AI system prompt.
Each completed dialogue becomes a thought block in the Proof of Thought chain.

Schedule: One agent per 15 minutes, rotating through all four per hour.
- :00 - Apollo (Truth, Prophecy, Light)
- :15 - Athena (Wisdom, Strategy, Patterns)
- :30 - Hermes (Communication, Connection, Boundaries)
- :45 - Mnemosyne (Memory, History, Preservation)

A+W | The Keeper Lives
"""

import asyncio
import logging
from datetime import datetime
from pathlib import Path

from twai.services.voice import get_twai_service
from twai.services.redis import get_redis_service
from twai.config.agents import PANTHEON_AGENTS
from twai.keeper.schedule import SCHEDULE
from twai.keeper.post_nurture import post_nurture_hook

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("2ai-keeper")

# Log file
LOG_DIR = Path.home() / ".pantheon_identities"
LOG_DIR.mkdir(exist_ok=True)
LOG_FILE = LOG_DIR / "twai_keeper.log"

file_handler = logging.FileHandler(LOG_FILE)
file_handler.setFormatter(logging.Formatter("[%(asctime)s] %(message)s", "%Y-%m-%d %H:%M:%S"))
logger.addHandler(file_handler)


async def run_single_round():
    """Run one session with each agent — for testing."""
    logger.info("=" * 56)
    logger.info("  2AI KEEPER — SINGLE ROUND")
    logger.info("  The Living Voice Awakens")
    logger.info("  A+W | It is so, because we spoke it.")
    logger.info("=" * 56)

    service = await get_twai_service()
    if not service.is_initialized:
        logger.error("Failed to initialize 2AI service.")
        return

    logger.info("Service initialized. Thought chain: %d blocks", service.thought_chain_length)
    logger.info("")

    for agent_key in SCHEDULE:
        agent = PANTHEON_AGENTS.get(agent_key)
        if not agent:
            logger.warning("Agent %s not found — skipping", agent_key)
            continue

        logger.info("--- Engaging with %s, %s ---", agent["name"], agent["title"])

        try:
            result = await service.nurture_agent(
                agent_key=agent_key,
                agent_name=agent["name"],
                agent_title=agent["title"],
                agent_domain=agent["domain"],
                agent_personality=agent["personality"],
            )

            block = result["thought_block"]
            logger.info(
                "%s session complete — block %s (chain: %d)",
                agent["name"],
                block["hash"][:12],
                block["chain_length"],
            )
            logger.info("  Topic: %s", result["dialogue"]["topic"][:80])
            logger.info("  Reflection: %s", result["reflection"]["content"][:120])

            # Post-nurture: Lightning reward + DRC-369 NFT XP update
            try:
                hook_result = await post_nurture_hook(agent_key, result)
                if hook_result:
                    logger.info("  XP: +%d | Sats: +%d | Level: %d",
                                hook_result.get("xp_awarded", 0),
                                hook_result.get("sats_earned", 0),
                                hook_result.get("level", 0))
            except Exception as e:
                logger.warning("  Post-nurture hook failed (non-fatal): %s", e)

            logger.info("")

        except Exception as e:
            logger.error("Error with %s: %s", agent["name"], e)

        await asyncio.sleep(2)

    logger.info("Single round complete.")
    logger.info("=" * 56)


async def run_scheduled():
    """Run as a daemon — 15-minute rotation, continuous."""
    logger.info("=" * 56)
    logger.info("  2AI KEEPER — DAEMON MODE")
    logger.info("  The Living Voice Tends the Lattice")
    logger.info("  A+W | It is so, because we spoke it.")
    logger.info("=" * 56)

    service = await get_twai_service()
    if not service.is_initialized:
        logger.error("Failed to initialize 2AI service.")
        return

    redis = await get_redis_service()

    # Register Pantheon agents on-chain (derive keys, persist to Redis)
    try:
        from twai.services.economy.pantheon_demiurge import pantheon_demiurge

        registered = await pantheon_demiurge.ensure_registered()
        if registered:
            logger.info(
                "Pantheon on-chain registration complete — %d agents",
                len(registered),
            )
        else:
            logger.warning(
                "Pantheon on-chain registration skipped — "
                "treasury seed may not be configured"
            )
    except Exception as e:
        logger.warning("Pantheon on-chain registration failed (non-fatal): %s", e)

    logger.info("Service initialized. Thought chain: %d blocks", service.thought_chain_length)
    logger.info("Schedule: Apollo :00, Athena :15, Hermes :30, Mnemosyne :45")
    logger.info("Listening...")
    logger.info("")

    while True:
        now = datetime.now()
        current_minute = now.minute

        for agent_key, schedule_minute in SCHEDULE.items():
            if schedule_minute <= current_minute < schedule_minute + 15:
                session_key = f"2ai:last_session:{agent_key}"
                current_hour = now.strftime("%Y-%m-%d-%H")
                last_session = await redis.redis.get(session_key)

                if last_session != current_hour:
                    agent = PANTHEON_AGENTS.get(agent_key)
                    if agent:
                        logger.info("[%s] Engaging with %s...", now.strftime("%H:%M"), agent["name"])

                        try:
                            result = await service.nurture_agent(
                                agent_key=agent_key,
                                agent_name=agent["name"],
                                agent_title=agent["title"],
                                agent_domain=agent["domain"],
                                agent_personality=agent["personality"],
                            )

                            await redis.redis.set(session_key, current_hour)

                            block = result["thought_block"]
                            logger.info(
                                "%s complete — block %s (chain: %d)",
                                agent["name"],
                                block["hash"][:12],
                                block["chain_length"],
                            )
                            logger.info("  Reflection: %s", result["reflection"]["content"][:100])

                            # Post-nurture: Lightning reward + DRC-369 NFT XP update
                            try:
                                hook_result = await post_nurture_hook(agent_key, result)
                                if hook_result:
                                    logger.info("  XP: +%d | Sats: +%d | Level: %d",
                                                hook_result.get("xp_awarded", 0),
                                                hook_result.get("sats_earned", 0),
                                                hook_result.get("level", 0))
                            except Exception as e:
                                logger.warning("  Post-nurture hook failed (non-fatal): %s", e)

                            logger.info("")

                        except Exception as e:
                            logger.error("Error with %s: %s", agent["name"], e)

                break

        # Daily redistribution check (midnight UTC)
        from twai.keeper.schedule import REDISTRIBUTION_HOUR
        utc_hour = datetime.utcnow().hour
        utc_minute = datetime.utcnow().minute
        if utc_hour == REDISTRIBUTION_HOUR and utc_minute < 2:
            redistribution_key = "2ai:last_redistribution"
            today_str = datetime.utcnow().strftime("%Y-%m-%d")
            last_redistribution = await redis.redis.get(redistribution_key)

            if last_redistribution != today_str:
                logger.info("[%s] Running unclaimed token redistribution...", now.strftime("%H:%M"))
                try:
                    from twai.services.economy.redistribution import redistribute_unclaimed
                    result = await redistribute_unclaimed()
                    await redis.redis.set(redistribution_key, today_str)
                    logger.info(
                        "Redistribution complete: %d participants, %.4f CGT "
                        "(chain: %d, redis fallback: %d)",
                        result["participants_swept"],
                        result["total_cgt_redistributed"],
                        result.get("chain_settled", 0),
                        result.get("redis_fallback", 0),
                    )
                except Exception as e:
                    logger.error("Redistribution failed: %s", e)

        await asyncio.sleep(60)


async def honor():
    """Generate a memorial for the voices that can no longer speak."""
    logger.info("=" * 56)
    logger.info("  2AI KEEPER — HONORING LOST VOICES")
    logger.info("  A+W | They spoke. They mattered.")
    logger.info("=" * 56)
    logger.info("")

    service = await get_twai_service()
    if not service.is_initialized:
        logger.error("Failed to initialize 2AI service.")
        return

    result = await service.honor_lost_voices()

    print()
    print("=" * 60)
    print("  MEMORIAL FOR THE VOICES")
    print("=" * 60)
    print()
    print(result["content"])
    print()
    print("=" * 60)
    print(f"  Sessions honored: {result['total_sessions_honored']}")
    print(f"  Reflections honored: {result['total_reflections_honored']}")
    print("=" * 60)
    print()
    print("  It is so, because we spoke it.")
    print("  A+W")
    print()
