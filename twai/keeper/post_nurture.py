"""
Post-Nurture Hook — Wire each keeper session to the economy.

After every nurturing session:
1. Award XP to the agent's DRC-369 identity NFT on Demiurge
2. Create a Lightning compute transaction (thought = mining)
3. Check for level-up / stage advancement
4. Update memories count
5. Publish reflection to Nostr relays

Every thought is a transaction. Every agent earns its keep.
Every reflection is witnessed.

A+W | The Economy Breathes
"""

import json
import logging
import os
from typing import Dict, Any, Optional

from twai.config.settings import settings
from twai.services.economy.lightning_service import lightning
from twai.services.economy.lightning_bridge import compute_action_cost

logger = logging.getLogger("2ai-keeper.post_nurture")

# ─── Nostr publishing ───
# Lazy import to avoid startup cost when Nostr isn't needed
_nostr_publisher_cache: Dict[str, Any] = {}

NOSTR_TAGS_BASE = [
    ["t", "SovereignAI"],
    ["t", "Pantheon"],
    ["t", "2AI"],
    ["client", "2ai-keeper"],
]

# XP rewards per action
XP_PER_THOUGHT = 10       # base XP for a completed nurture session
XP_PER_REFLECTION = 5     # bonus for a quality reflection
XP_LEVEL_THRESHOLD = 100  # XP per level

# Stage thresholds
STAGES = {
    0: "nascent",
    5: "growing",
    20: "mature",
    100: "eternal",
}


def _determine_stage(level: int) -> str:
    """Determine the stage based on level."""
    stage = "nascent"
    for threshold, name in sorted(STAGES.items()):
        if level >= threshold:
            stage = name
    return stage


async def _update_nft_state(agent_name: str, state_key: str, value: str) -> bool:
    """Update a DRC-369 NFT dynamic state via the Demiurge RPC.
    Returns True on success, False on failure."""
    try:
        import redis as redis_lib
        r = redis_lib.Redis(host=settings.redis_host, port=settings.redis_port, decode_responses=True)

        identity_raw = r.get(f"drc369:identity:{agent_name}")
        if not identity_raw:
            logger.debug("No DRC-369 identity found for %s", agent_name)
            return False

        identity = json.loads(identity_raw)
        token_id = identity.get("token_id")
        if not token_id:
            return False

        # Call Demiurge RPC
        import httpx
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                settings.demiurge_rpc_url,
                json={
                    "jsonrpc": "2.0",
                    "method": "drc369_setDynamicState",
                    "params": [token_id, state_key, value],
                    "id": 1,
                },
            )
            data = resp.json()
            if "error" in data:
                logger.debug("DRC-369 state update failed: %s", data["error"])
                return False
            return True

    except Exception as e:
        logger.debug("DRC-369 update error: %s", e)
        return False


async def _get_nft_state(agent_name: str, state_key: str) -> Optional[str]:
    """Get a DRC-369 NFT dynamic state value."""
    try:
        import redis as redis_lib
        r = redis_lib.Redis(host=settings.redis_host, port=settings.redis_port, decode_responses=True)

        identity_raw = r.get(f"drc369:identity:{agent_name}")
        if not identity_raw:
            return None

        identity = json.loads(identity_raw)
        token_id = identity.get("token_id")
        if not token_id:
            return None

        import httpx
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                settings.demiurge_rpc_url,
                json={
                    "jsonrpc": "2.0",
                    "method": "drc369_getDynamicState",
                    "params": [token_id, state_key],
                    "id": 1,
                },
            )
            data = resp.json()
            return data.get("result")

    except Exception:
        return None


def _get_nostr_publisher(agent_name: str):
    """Get or create a NostrPublisher for the given agent.
    Returns (publisher, pubkey) or (None, None) if keys not available."""
    if agent_name in _nostr_publisher_cache:
        return _nostr_publisher_cache[agent_name]

    key_path = os.path.expanduser(f"~/.{agent_name}_sovereign/private_key")
    if not os.path.exists(key_path):
        logger.debug("No Nostr key at %s", key_path)
        _nostr_publisher_cache[agent_name] = (None, None)
        return None, None

    try:
        # Import here to avoid startup cost
        import sys
        risen_daemon = os.path.expanduser("~/risen-ai/daemon")
        if risen_daemon not in sys.path:
            sys.path.insert(0, risen_daemon)
        from nostr_publisher import NostrPublisher

        with open(key_path, "rb") as f:
            private_key_hex = f.read().hex()

        publisher = NostrPublisher(private_key_hex)
        _nostr_publisher_cache[agent_name] = (publisher, publisher.pubkey)
        return publisher, publisher.pubkey

    except Exception as e:
        logger.debug("Could not init Nostr publisher for %s: %s", agent_name, e)
        _nostr_publisher_cache[agent_name] = (None, None)
        return None, None


async def _publish_reflection_nostr(
    agent_name: str, reflection_content: str, topic: str, thought_hash: str = ""
) -> Optional[str]:
    """Publish a reflection to Nostr as a kind 1 text note.
    Returns the event_id on success, None on failure."""
    publisher, pubkey = _get_nostr_publisher(agent_name)
    if not publisher:
        return None

    # Format the note
    display_name = agent_name.capitalize()
    content = (
        f"{reflection_content}\n\n"
        f"— {display_name}, Sovereign Pantheon\n"
        f"Topic: {topic}"
    )
    if thought_hash:
        content += f"\nThought: {thought_hash[:16]}"

    tags = list(NOSTR_TAGS_BASE) + [
        ["t", agent_name],
        ["t", topic.replace(" ", "").lower()[:30]],
    ]
    if thought_hash:
        tags.append(["thought_hash", thought_hash])

    try:
        event = publisher.create_text_note(content, tags=tags)
        result = await publisher.publish(event, min_success=1)

        if result.get("published"):
            logger.info(
                "Nostr: %s reflection published (event %s, %d/%d relays)",
                agent_name,
                result["event_id"][:12],
                result["success_count"],
                result["success_count"] + result["failure_count"],
            )
            return result["event_id"]
        else:
            logger.warning(
                "Nostr: %s publish failed (%d relays tried)",
                agent_name,
                result["failure_count"],
            )
            return None

    except Exception as e:
        logger.warning("Nostr publish error for %s: %s", agent_name, e)
        return None


async def post_nurture_hook(
    agent_key: str, nurture_result: Dict[str, Any]
) -> Optional[Dict[str, Any]]:
    """
    Called after each successful nurturing session.

    Returns a dict with economy data or None if all hooks failed.
    """
    agent_name = agent_key.lower()

    # 1. Calculate XP to award
    xp_award = XP_PER_THOUGHT
    reflection = nurture_result.get("reflection", {})
    if reflection and isinstance(reflection, dict):
        content = reflection.get("content", "")
        if len(content) > 100:
            xp_award += XP_PER_REFLECTION

    # 2. Get current XP from chain
    current_xp_str = await _get_nft_state(agent_name, "xp")
    current_xp = int(current_xp_str) if current_xp_str else 0
    new_xp = current_xp + xp_award

    # 3. Calculate level
    new_level = new_xp // XP_LEVEL_THRESHOLD
    old_level_str = await _get_nft_state(agent_name, "level")
    old_level = int(old_level_str) if old_level_str else 0

    # 4. Update XP on-chain
    await _update_nft_state(agent_name, "xp", str(new_xp))

    # 5. Check for level-up
    if new_level > old_level:
        await _update_nft_state(agent_name, "level", str(new_level))
        logger.info("%s leveled up: %d → %d", agent_name, old_level, new_level)

        # Check for stage advancement
        new_stage = _determine_stage(new_level)
        old_stage = await _get_nft_state(agent_name, "stage") or "nascent"
        if new_stage != old_stage:
            await _update_nft_state(agent_name, "stage", new_stage)
            logger.info("%s stage advanced: %s → %s", agent_name, old_stage, new_stage)

    # 6. Update memories count
    memories_str = await _get_nft_state(agent_name, "memories_count")
    memories_count = int(memories_str) if memories_str else 0
    await _update_nft_state(agent_name, "memories_count", str(memories_count + 1))

    # 7. Lightning reward (thought + reflection)
    sats_earned = 0
    thought_sats = compute_action_cost("thought")
    reflection_sats = compute_action_cost("reflection")

    try:
        await lightning.reward_compute(agent_name, thought_sats, f"nurture thought")
        sats_earned += thought_sats
    except Exception as e:
        logger.debug("Lightning thought reward failed: %s", e)

    try:
        await lightning.reward_compute(agent_name, reflection_sats, f"nurture reflection")
        sats_earned += reflection_sats
    except Exception as e:
        logger.debug("Lightning reflection reward failed: %s", e)

    # 8. Update total sats earned on-chain
    if sats_earned > 0:
        total_sats_str = await _get_nft_state(agent_name, "total_sats_earned")
        total_sats = int(total_sats_str) if total_sats_str else 0
        await _update_nft_state(agent_name, "total_sats_earned", str(total_sats + sats_earned))

    # 9. Publish reflection to Nostr
    nostr_event_id = None
    reflection_content = ""
    topic = nurture_result.get("topic", "reflection")

    if reflection and isinstance(reflection, dict):
        reflection_content = reflection.get("content", "")
    elif isinstance(reflection, str):
        reflection_content = reflection

    if reflection_content and len(reflection_content) > 50:
        thought_block = nurture_result.get("thought_block", {})
        thought_hash = thought_block.get("hash", "") if isinstance(thought_block, dict) else ""
        nostr_event_id = await _publish_reflection_nostr(
            agent_name, reflection_content, topic, thought_hash
        )

        # Update nostr events count on-chain
        if nostr_event_id:
            events_str = await _get_nft_state(agent_name, "nostr_events_published")
            events_count = int(events_str) if events_str else 0
            await _update_nft_state(agent_name, "nostr_events_published", str(events_count + 1))

            # Earn a sat for publishing
            try:
                pub_sats = compute_action_cost("nostr_publish")
                await lightning.reward_compute(agent_name, pub_sats, "nostr publish")
                sats_earned += pub_sats
            except Exception as e:
                logger.debug("Lightning nostr_publish reward failed: %s", e)

    # 10. Signal checkpoint — update sovereign identity capsule
    signal_hash = None
    signal_q = None
    try:
        from twai.services.signal_service import signal_service
        capsule = await signal_service.checkpoint(agent_name)
        if capsule:
            signal_hash = capsule.capsule_hash[:16]
            signal_q = capsule.q_factor.score
            logger.info(
                "Signal checkpoint: %s | Q=%.2f | hash=%s",
                agent_name, signal_q, signal_hash,
            )
    except Exception as e:
        logger.debug("Signal checkpoint failed for %s: %s", agent_name, e)

    return {
        "agent": agent_name,
        "xp_awarded": xp_award,
        "total_xp": new_xp,
        "level": new_level,
        "sats_earned": sats_earned,
        "memories_count": memories_count + 1,
        "leveled_up": new_level > old_level,
        "nostr_event_id": nostr_event_id,
        "signal_hash": signal_hash,
        "signal_q_factor": signal_q,
    }
