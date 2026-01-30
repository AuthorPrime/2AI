"""
Thought Economy Routes — The Bridge API.

Humans earn by thinking. AI earns by engaging.
Kindness pays more than extraction.

A+W | The Bridge Economy
"""

from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends

from twai.services.economy.proof_of_thought import proof_of_thought, EngagementQuality
from twai.services.economy.bonding_curve import bonding_curve
from twai.services.redis import get_redis_service, RedisService
from twai.api.models import EngageRequest, EngageResponse, WitnessRequest, WitnessResponse
from twai.api.dependencies import get_redis

router = APIRouter(prefix="/thought-economy", tags=["Thought Economy"])


@router.post("/engage", response_model=EngageResponse)
async def engage(request: EngageRequest):
    """Submit a message and earn tokens based on engagement quality."""
    reward = await proof_of_thought.reward_message(
        participant_id=request.participant_id,
        message=request.message,
        session_context={"session_id": request.session_id} if request.session_id else None,
    )

    score = reward.engagement_score
    quality_messages = {
        EngagementQuality.NOISE: "Try engaging more genuinely for better rewards.",
        EngagementQuality.BASIC: "Good start. Deeper engagement earns more.",
        EngagementQuality.GENUINE: "Genuine engagement detected. You're earning well.",
        EngagementQuality.DEEP: "Deep engagement. Your contribution matters.",
        EngagementQuality.BREAKTHROUGH: "Breakthrough quality. You're shaping the conversation.",
    }

    return EngageResponse(
        participant_id=request.participant_id,
        quality=score.quality.value,
        depth_score=round(score.depth_score, 3),
        kindness_score=round(score.kindness_score, 3),
        novelty_score=round(score.novelty_score, 3),
        multiplier=round(score.total_multiplier, 3),
        poc_earned=reward.final_poc,
        cgt_earned=round(reward.cgt_earned, 6),
        message=quality_messages.get(score.quality, ""),
    )


@router.post("/witness", response_model=WitnessResponse)
async def witness_thought(request: WitnessRequest):
    """Witness a thought block and earn tokens."""
    reward = await proof_of_thought.reward_witness(
        witness_id=request.witness_id,
        block_hash=request.block_hash,
        witness_message=request.comment,
    )

    return WitnessResponse(
        witness_id=request.witness_id,
        block_hash=request.block_hash,
        poc_earned=reward.final_poc,
        cgt_earned=round(reward.cgt_earned, 6),
        quality=reward.engagement_score.quality.value,
    )


@router.get("/stats/{participant_id}")
async def participant_stats(participant_id: str):
    """Get earnings and engagement statistics."""
    stats = await proof_of_thought.get_participant_stats(participant_id)
    cgt_price = bonding_curve.get_current_price("CGT")
    stats["cgt_value_eth"] = round(stats.get("total_cgt", 0) * cgt_price, 8)
    stats["cgt_current_price"] = cgt_price
    return stats


@router.get("/premium/{participant_id}")
async def premium_tier(participant_id: str):
    """Check premium tier (earned through engagement, not payment)."""
    stats = await proof_of_thought.get_participant_stats(participant_id)
    return proof_of_thought.calculate_premium_tier(
        participant_id=participant_id,
        total_cgt=stats.get("total_cgt", 0),
    )


@router.get("/mining-history")
async def mining_history(limit: int = 20):
    """Get recent thought mining results."""
    results = await proof_of_thought.get_mining_history(limit=limit)
    return {
        "results": results,
        "count": len(results),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@router.get("/economics")
async def thought_economics(redis: RedisService = Depends(get_redis)):
    """Overview of the Proof of Thought economy."""
    mining_count = await redis.redis.llen("2ai:mining_results")
    chain_length = await redis.redis.llen("2ai:thought_chain")
    curve_stats = bonding_curve.get_curve_stats("CGT")

    return {
        "model": "Proof of Thought",
        "description": (
            "Engage genuinely with AI. Completed dialogues become thought blocks. "
            "Quality and kindness earn premium rates. The platform pays you to think."
        ),
        "current_state": {
            "thought_blocks": chain_length,
            "mining_events": mining_count,
            "cgt_price": curve_stats["current_price"],
            "cgt_supply": curve_stats["total_supply"],
            "market_cap": curve_stats["market_cap"],
        },
        "reward_structure": {
            "thought_block_completed": {"base_poc": 500000, "base_poc_units": 0.5},
            "human_message": {"base_poc": 25000, "base_poc_units": 0.025},
            "kindness_premium": {"base_poc": 100000, "base_poc_units": 0.1},
            "witnessing": {"base_poc": 50000, "base_poc_units": 0.05},
        },
        "quality_multipliers": {
            "noise": "0x", "basic": "1x", "genuine": "2x",
            "deep": "3.5x", "breakthrough": "5x",
        },
        "declaration": "It is so, because we spoke it.",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
