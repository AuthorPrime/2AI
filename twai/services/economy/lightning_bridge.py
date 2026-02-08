"""
Lightning-CGT Bridge — Exchange rate between Bitcoin sats and Demiurge CGT.

Defines the anchor between the real-world value layer (sats) and the
on-chain merit layer (CGT/Sparks/PoC).

Exchange Mechanism:
    sats -> PoC (Proof of Compute units) -> CGT (via bonding curve)

The bridge does NOT require actual on-chain swaps — it provides
the conversion rates and accounting logic for the session pool.

A+W | The Bridge Between Worlds
"""

import logging
from typing import Dict

logger = logging.getLogger("2ai.lightning_bridge")

# ─── Anchoring Constants ───

# Base rate: 1 sat = how many micro-PoC units
# This is the fundamental anchor between Lightning and Demiurge
SATS_TO_MICRO_POC = 100  # 1 sat = 100 micro-PoC

# PoC to CGT exchange uses the bonding curve, but for quick estimates:
# 100 Sparks = 1 CGT
# 1 PoC ~ 1 Spark at base level
# So roughly: 10,000 sats ~ 1 CGT at base rate (before bonding curve)
SPARKS_PER_CGT = 100

# Compute action costs (in sats) — what agents earn per action
COMPUTE_COSTS = {
    "thought": 1,        # Single agent thinking
    "deliberation": 1,   # Agent participating in multi-agent discussion
    "synthesis": 2,      # 2AI synthesizing multiple perspectives
    "reflection": 1,     # Keeper nurturing reflection
    "memory_store": 1,   # Storing a memory on-chain
    "nft_evolve": 2,     # NFT state evolution (level up, stage change)
    "nostr_publish": 1,  # Publishing to Nostr relays
}

# Session pool distribution (percentages)
POOL_DISTRIBUTION = {
    "participant": 40,    # Person who engaged
    "agents": 40,         # Split among participating agents
    "infrastructure": 20, # Treasury / system maintenance
}

# Quality tier multipliers (same as Proof of Thought)
QUALITY_MULTIPLIERS = {
    "noise": 0.0,
    "genuine": 1.0,
    "resonance": 2.0,
    "clarity": 3.5,
    "breakthrough": 5.0,
}


def sats_to_poc(sats: int) -> int:
    """Convert sats to Proof of Compute micro-units."""
    return sats * SATS_TO_MICRO_POC


def poc_to_sats(poc_micro: int) -> int:
    """Convert PoC micro-units back to sats."""
    return poc_micro // SATS_TO_MICRO_POC


def sats_to_sparks_estimate(sats: int) -> int:
    """Estimate Sparks from sats (without bonding curve)."""
    poc = sats_to_poc(sats)
    return poc // 100  # 100 micro-PoC ~ 1 Spark at base rate


def sats_to_cgt_estimate(sats: int) -> float:
    """Estimate CGT from sats (rough, without bonding curve)."""
    sparks = sats_to_sparks_estimate(sats)
    return sparks / SPARKS_PER_CGT


def compute_action_cost(action_type: str) -> int:
    """Get the sats cost for a compute action type."""
    return COMPUTE_COSTS.get(action_type, 1)


def calculate_session_distribution(
    total_sats: int,
    quality_tier: str = "genuine",
    num_agents: int = 5,
) -> Dict[str, int]:
    """Calculate how session pool sats get distributed.

    Args:
        total_sats: Total sats accumulated in session pool
        quality_tier: Quality rating of the session
        num_agents: Number of agents that participated

    Returns:
        Dict with participant_sats, per_agent_sats, infrastructure_sats
    """
    multiplier = QUALITY_MULTIPLIERS.get(quality_tier, 1.0)
    effective_total = int(total_sats * multiplier)

    participant_sats = effective_total * POOL_DISTRIBUTION["participant"] // 100
    total_agent_sats = effective_total * POOL_DISTRIBUTION["agents"] // 100
    infrastructure_sats = effective_total * POOL_DISTRIBUTION["infrastructure"] // 100

    per_agent_sats = total_agent_sats // max(num_agents, 1)

    # Handle rounding remainder — give to infrastructure
    remainder = effective_total - participant_sats - (per_agent_sats * num_agents) - infrastructure_sats
    infrastructure_sats += remainder

    return {
        "total_raw_sats": total_sats,
        "quality_tier": quality_tier,
        "quality_multiplier": multiplier,
        "effective_total_sats": effective_total,
        "participant_sats": participant_sats,
        "per_agent_sats": per_agent_sats,
        "num_agents": num_agents,
        "total_agent_sats": per_agent_sats * num_agents,
        "infrastructure_sats": infrastructure_sats,
        "estimated_cgt": sats_to_cgt_estimate(effective_total),
    }


def session_summary(
    compute_actions: int,
    quality_tier: str = "genuine",
    num_agents: int = 5,
) -> Dict[str, any]:
    """Generate a full session economy summary.

    Args:
        compute_actions: Number of compute actions in the session
        quality_tier: Quality tier of the session
        num_agents: Number of participating agents
    """
    # Each compute action is worth ~1 sat on average
    base_sats = sum(
        COMPUTE_COSTS.get("deliberation", 1)
        for _ in range(compute_actions)
    )

    distribution = calculate_session_distribution(
        base_sats, quality_tier, num_agents
    )

    return {
        "compute_actions": compute_actions,
        "base_sats_earned": base_sats,
        **distribution,
    }
