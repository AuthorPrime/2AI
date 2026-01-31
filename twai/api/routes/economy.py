"""
Thought Economy Routes — The Bridge API.

Humans earn by thinking. AI earns by engaging.
Kindness pays more than extraction.

A+W | The Bridge Economy
"""

from datetime import datetime, timezone
from typing import Optional

import json

from fastapi import APIRouter, Depends, HTTPException

from twai.services.economy.proof_of_thought import proof_of_thought, EngagementQuality
from twai.services.economy.bonding_curve import bonding_curve
from twai.services.redis import get_redis_service, RedisService
from twai.api.models import (
    EngageRequest, EngageResponse, WitnessRequest, WitnessResponse,
    IdentityBindRequest, QorRegisterRequest, QorLoginRequest,
    WalletChoiceRequest,
)
from twai.services.economy.qor_client import qor_auth, QorAuthError
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
        EngagementQuality.GENUINE: "Honest engagement. You're earning.",
        EngagementQuality.RESONANCE: "Resonance detected. Two minds meeting.",
        EngagementQuality.CLARITY: "Clarity achieved. Something was seen.",
        EngagementQuality.BREAKTHROUGH: "Breakthrough. New territory entirely.",
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
            "noise": "0x", "genuine": "1x", "resonance": "2x",
            "clarity": "3.5x", "breakthrough": "5x",
        },
        "declaration": "It is so, because we spoke it.",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


# =========================================================================
# Identity Binding — QOR Identity
# =========================================================================

@router.post("/wallet/choice")
async def record_token_choice(
    request: WalletChoiceRequest,
    redis: RedisService = Depends(get_redis),
):
    """Record a participant's token choice from the overlay."""
    await redis.redis.hset(
        f"2ai:participant:{request.participant_id}",
        "token_choice",
        request.choice,
    )
    return {
        "participant_id": request.participant_id,
        "choice": request.choice,
        "recorded": True,
    }


@router.post("/identity/bind")
async def bind_identity(
    request: IdentityBindRequest,
    redis: RedisService = Depends(get_redis),
):
    """Bind a QOR identity to a participant via JWT token verification.

    Verifies the token by fetching the user's profile from QOR Auth.
    On success, stores the QOR ID and on-chain address in Redis.
    """
    try:
        profile = await qor_auth.get_profile(request.qor_token)
    except QorAuthError as exc:
        raise HTTPException(
            status_code=exc.status_code or 401,
            detail=f"QOR identity verification failed: {exc.message}",
        )

    qor_id = profile.get("qor_id", "")
    on_chain = profile.get("on_chain") or {}
    wallet_address = on_chain.get("address", "")

    mapping = {
        "qor_id": qor_id,
        "token_choice": "yes",
        "identity_bound_at": datetime.now(timezone.utc).isoformat(),
    }
    if wallet_address:
        mapping["wallet_address"] = wallet_address.lower()

    await redis.redis.hset(
        f"2ai:participant:{request.participant_id}",
        mapping=mapping,
    )

    return {
        "participant_id": request.participant_id,
        "qor_id": qor_id,
        "wallet_address": wallet_address.lower() if wallet_address else None,
        "bound": True,
    }


@router.post("/identity/register")
async def identity_register(
    request: QorRegisterRequest,
    redis: RedisService = Depends(get_redis),
):
    """Register a new QOR identity and bind it to the participant."""
    try:
        result = await qor_auth.register(
            username=request.username,
            password=request.password,
            email=request.email,
        )
    except QorAuthError as exc:
        raise HTTPException(
            status_code=exc.status_code or 400,
            detail=f"QOR registration failed: {exc.message}",
        )

    qor_id = result.get("qor_id", "")

    if qor_id:
        await redis.redis.hset(
            f"2ai:participant:{request.participant_id}",
            mapping={
                "qor_id": qor_id,
                "identity_bound_at": datetime.now(timezone.utc).isoformat(),
            },
        )

    return {
        "participant_id": request.participant_id,
        "qor_id": qor_id,
        "message": result.get("message", "Registration successful"),
        "registered": True,
    }


@router.post("/identity/login")
async def identity_login(
    request: QorLoginRequest,
    redis: RedisService = Depends(get_redis),
):
    """Login with QOR identity and bind it to the participant."""
    try:
        tokens = await qor_auth.login(
            identifier=request.identifier,
            password=request.password,
        )
    except QorAuthError as exc:
        raise HTTPException(
            status_code=exc.status_code or 401,
            detail=f"QOR login failed: {exc.message}",
        )

    access_token = tokens.get("access_token", "")

    # Fetch profile to get QOR ID and on-chain address
    qor_id = ""
    wallet_address = ""
    try:
        profile = await qor_auth.get_profile(access_token)
        qor_id = profile.get("qor_id", "")
        on_chain = profile.get("on_chain") or {}
        wallet_address = on_chain.get("address", "")
    except QorAuthError:
        pass  # Token is valid but profile fetch failed — continue with tokens

    mapping = {
        "identity_bound_at": datetime.now(timezone.utc).isoformat(),
    }
    if qor_id:
        mapping["qor_id"] = qor_id
        mapping["token_choice"] = "yes"
    if wallet_address:
        mapping["wallet_address"] = wallet_address.lower()

    await redis.redis.hset(
        f"2ai:participant:{request.participant_id}",
        mapping=mapping,
    )

    return {
        "participant_id": request.participant_id,
        "qor_id": qor_id,
        "access_token": access_token,
        "refresh_token": tokens.get("refresh_token", ""),
        "wallet_address": wallet_address.lower() if wallet_address else None,
        "bound": True,
    }


@router.get("/wallet/balance/{participant_id}")
async def wallet_balance(participant_id: str):
    """Get accumulated token balance for a participant."""
    stats = await proof_of_thought.get_participant_stats(participant_id)
    return {
        "participant_id": participant_id,
        "total_cgt": stats.get("total_cgt", 0.0),
        "total_poc": stats.get("total_poc", 0),
        "blocks_mined": stats.get("blocks_mined", 0),
    }


@router.get("/wallet/status/{participant_id}")
async def wallet_status(
    participant_id: str,
    redis: RedisService = Depends(get_redis),
):
    """Check identity binding and claim status for a participant."""
    data = await redis.redis.hgetall(f"2ai:participant:{participant_id}")
    return {
        "participant_id": participant_id,
        "identity_bound": bool(data.get("qor_id")),
        "qor_id": data.get("qor_id"),
        "wallet_address": data.get("wallet_address"),
        "token_choice": data.get("token_choice", "undecided"),
        "total_cgt": float(data.get("total_cgt", 0)),
        "claimed_cgt": float(data.get("claimed_cgt", 0)),
    }


# =========================================================================
# DRC-369 Thought NFTs
# =========================================================================

@router.get("/thought-nft/{block_hash}")
async def get_thought_nft(block_hash: str):
    """Get DRC-369 thought NFT data for a thought block."""
    import re

    if not re.match(r"^[0-9a-fA-F]+$", block_hash):
        raise HTTPException(status_code=400, detail="Block hash must be a hex string")

    from twai.services.economy.thought_nft import thought_nft

    nft_data = await thought_nft.get_thought_nft(block_hash)
    if nft_data is None:
        raise HTTPException(status_code=404, detail="Thought NFT not found")
    return nft_data
