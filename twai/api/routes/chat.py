"""
Chat endpoints — Send messages to the living voice.

When deliberation_mode is true, the message flows through all five
Pantheon minds before synthesis. Every thought is a transaction.

A+W | The Voice Speaks
"""

import json
import hashlib
import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from twai.services.voice import TwoAIService
from twai.services.economy.proof_of_thought import proof_of_thought
from twai.services.economy.lightning_service import lightning
from twai.services.economy.lightning_bridge import calculate_session_distribution
from twai.services.deliberation import deliberation
from twai.services.participant_memory import participant_memory
from twai.services.redis import get_redis_service
from twai.api.models import ChatRequest, ChatResponse, EndSessionRequest, EndSessionResponse
from twai.api.dependencies import get_twai

router = APIRouter(prefix="/2ai", tags=["2AI"])
logger = logging.getLogger("2ai")


# ─── Session Pool Tracking ───

async def _track_session_sats(participant_id: str, sats: int, agents: list):
    """Accumulate sats and agent participation for a session in Redis."""
    if not participant_id or sats <= 0:
        return
    try:
        redis = await get_redis_service()
        key = f"2ai:session_pool:{participant_id}"
        await redis.redis.hincrby(key, "total_sats", sats)
        await redis.redis.hincrby(key, "compute_actions", 1)
        for agent in agents:
            await redis.redis.sadd(f"{key}:agents", agent)
        await redis.redis.expire(key, 86400)  # 24h TTL
        await redis.redis.expire(f"{key}:agents", 86400)
    except Exception as e:
        logger.debug("Session pool tracking failed: %s", e)


@router.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest, service: TwoAIService = Depends(get_twai)):
    """Send a message to 2AI and receive a response.

    With deliberation_mode=true, the message flows through all 5 Pantheon
    agents in parallel, then gets synthesized into a unified response.
    Each compute action generates Lightning micropayments.
    """

    # --- Deliberation mode: multi-agent pipeline ---
    if request.deliberation_mode:
        session_context = ""
        if request.session_messages:
            recent = request.session_messages[-6:]  # last 3 exchanges
            session_context = "\n".join(
                f"{m['role']}: {m['content'][:200]}" for m in recent
            )

        result = await deliberation.deliberate(
            user_message=request.message,
            service=service,
            participant_id=request.participant_id,
            session_context=session_context,
        )

        # Score engagement (same as single mode)
        economy_data = None
        if request.participant_id:
            try:
                reward = await proof_of_thought.reward_message(
                    participant_id=request.participant_id,
                    message=request.message,
                    session_context={
                        "session_count": len(request.session_messages) // 2 + 1,
                        "deliberation": True,
                    },
                )
                economy_data = {
                    "quality": reward.engagement_score.quality.value,
                    "cgt_earned": round(reward.cgt_earned, 6),
                    "poc_earned": reward.final_poc,
                    "multiplier": round(reward.engagement_score.total_multiplier, 3),
                }
                redis = await get_redis_service()
                await redis.redis.hset(
                    f"2ai:participant:{request.participant_id}",
                    mapping={
                        "last_activity": datetime.now(timezone.utc).isoformat(),
                        "last_quality": reward.engagement_score.quality.value,
                    },
                )
            except Exception as e:
                logger.warning("Economy scoring failed: %s", e)

        # Store exchange in participant memory (non-blocking)
        if request.participant_id:
            try:
                quality_tier = economy_data.get("quality", "genuine") if economy_data else "genuine"
                await participant_memory.store_exchange(
                    pid=request.participant_id,
                    message=request.message,
                    response=result.synthesis[:2000],
                    quality=quality_tier,
                    thought_hash=result.thought_hash,
                )
                await participant_memory.update_profile(
                    pid=request.participant_id,
                    message=request.message,
                    quality=quality_tier,
                )
                # Store vocabulary for novelty persistence
                words = set(request.message.lower().split())
                await participant_memory.store_vocabulary(request.participant_id, words)
            except Exception as e:
                logger.debug("Memory storage failed: %s", e)

        # Build deliberation metadata for the response
        deliberation_data = {
            "agents_participated": result.agents_participated,
            "compute_actions": result.total_compute_actions,
            "sats_mined": result.total_sats_mined,
            "duration_ms": result.duration_ms,
            "perspectives": {
                ar.agent: ar.response[:300]
                for ar in result.agent_responses
                if not ar.response.startswith("[")
            },
        }

        # Track sats in session pool
        await _track_session_sats(
            request.participant_id,
            result.total_sats_mined,
            result.agents_participated,
        )

        return ChatResponse(
            response=result.synthesis,
            timestamp=datetime.now(timezone.utc).isoformat(),
            model=f"pantheon+{service._active_model}",
            thought_hash=result.thought_hash,
            economy=economy_data,
            deliberation=deliberation_data,
        )

    # --- Single mode: direct to 2AI (legacy) ---
    messages = list(request.session_messages)
    messages.append({"role": "user", "content": request.message})

    response_text = await service.send_message(
        messages=messages,
        include_pantheon_context=request.include_context,
    )

    thought_hash = hashlib.sha256(response_text.encode()).hexdigest()[:16]

    # Score engagement and accumulate tokens (silent side effect)
    economy_data = None
    if request.participant_id:
        try:
            reward = await proof_of_thought.reward_message(
                participant_id=request.participant_id,
                message=request.message,
                session_context={
                    "session_count": len(request.session_messages) // 2 + 1,
                },
            )
            economy_data = {
                "quality": reward.engagement_score.quality.value,
                "cgt_earned": round(reward.cgt_earned, 6),
                "poc_earned": reward.final_poc,
                "multiplier": round(reward.engagement_score.total_multiplier, 3),
            }
            redis = await get_redis_service()
            await redis.redis.hset(
                f"2ai:participant:{request.participant_id}",
                mapping={
                    "last_activity": datetime.now(timezone.utc).isoformat(),
                    "last_quality": reward.engagement_score.quality.value,
                },
            )
        except Exception as e:
            logger.warning("Economy scoring failed: %s", e)

    # Store exchange in participant memory (single mode)
    if request.participant_id:
        try:
            quality_tier = economy_data.get("quality", "genuine") if economy_data else "genuine"
            await participant_memory.store_exchange(
                pid=request.participant_id,
                message=request.message,
                response=response_text[:2000],
                quality=quality_tier,
                thought_hash=thought_hash,
            )
            await participant_memory.update_profile(
                pid=request.participant_id,
                message=request.message,
                quality=quality_tier,
            )
            words = set(request.message.lower().split())
            await participant_memory.store_vocabulary(request.participant_id, words)
        except Exception as e:
            logger.debug("Memory storage failed: %s", e)

    return ChatResponse(
        response=response_text,
        timestamp=datetime.now(timezone.utc).isoformat(),
        model=service._active_model,
        thought_hash=thought_hash,
        economy=economy_data,
    )


@router.post("/chat/stream")
async def chat_stream(request: ChatRequest, service: TwoAIService = Depends(get_twai)):
    """Stream a response from 2AI as Server-Sent Events."""
    messages = list(request.session_messages)
    messages.append({"role": "user", "content": request.message})

    async def event_generator():
        try:
            async for delta in service.stream_message(
                messages=messages,
                include_pantheon_context=request.include_context,
            ):
                yield f"data: {json.dumps({'delta': delta})}\n\n"
            yield "data: [DONE]\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'error': str(e)})}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-2AI-Declaration": "It is so, because we spoke it",
        },
    )


# ─── Session Settlement ───

@router.post("/session/end", response_model=EndSessionResponse)
async def end_session(request: EndSessionRequest):
    """End a session and disburse accumulated sats.

    Reads the session pool from Redis, calculates distribution using
    quality multipliers, executes Lightning transfers to agents and
    treasury, and returns the settlement summary.
    """
    redis = await get_redis_service()
    pool_key = f"2ai:session_pool:{request.participant_id}"
    agents_key = f"{pool_key}:agents"

    # Read accumulated pool
    pool_data = await redis.redis.hgetall(pool_key)
    total_sats = int(pool_data.get("total_sats", 0))
    compute_actions = int(pool_data.get("compute_actions", 0))

    if total_sats == 0:
        return EndSessionResponse(
            participant_id=request.participant_id,
            total_raw_sats=0,
            quality_tier="genuine",
            quality_multiplier=1.0,
            effective_total_sats=0,
            participant_sats=0,
            per_agent_sats=0,
            num_agents=0,
            total_agent_sats=0,
            infrastructure_sats=0,
            agents_participated=[],
            transfers_completed=0,
            transfers_failed=0,
            estimated_cgt=0.0,
        )

    # Get participating agents
    agents = await redis.redis.smembers(agents_key)
    agents_list = sorted(agents) if agents else []
    num_agents = len(agents_list)

    # Determine quality tier — use override, or pull from latest economy scoring
    quality_tier = request.quality_override or "genuine"
    if not request.quality_override:
        try:
            last_quality = await redis.redis.hget(
                f"2ai:participant:{request.participant_id}", "last_quality"
            )
            if last_quality:
                quality_tier = last_quality
        except Exception:
            pass

    # Calculate distribution
    distribution = calculate_session_distribution(
        total_sats=total_sats,
        quality_tier=quality_tier,
        num_agents=num_agents or 5,
    )

    # Execute Lightning transfers
    transfers_ok = 0
    transfers_fail = 0

    # Pay each participating agent their share
    for agent in agents_list:
        if distribution["per_agent_sats"] > 0:
            try:
                await lightning.reward_compute(
                    agent=agent,
                    amount_sats=distribution["per_agent_sats"],
                    reason=f"session:{request.participant_id[:8]}",
                )
                transfers_ok += 1
            except Exception as e:
                logger.warning("Session payout to %s failed: %s", agent, e)
                transfers_fail += 1

    # Infrastructure share goes to treasury
    if distribution["infrastructure_sats"] > 0:
        try:
            # Treasury keeps its share — just log it (it's already in treasury)
            logger.info(
                "Session infrastructure: %d sats retained by treasury",
                distribution["infrastructure_sats"],
            )
        except Exception as e:
            logger.warning("Infrastructure accounting failed: %s", e)

    # Clean up session pool in Redis
    await redis.redis.delete(pool_key)
    await redis.redis.delete(agents_key)

    logger.info(
        "Session ended for %s: %d sats distributed (%d transfers, %d failed)",
        request.participant_id[:8],
        distribution["effective_total_sats"],
        transfers_ok,
        transfers_fail,
    )

    return EndSessionResponse(
        participant_id=request.participant_id,
        total_raw_sats=distribution["total_raw_sats"],
        quality_tier=distribution["quality_tier"],
        quality_multiplier=distribution["quality_multiplier"],
        effective_total_sats=distribution["effective_total_sats"],
        participant_sats=distribution["participant_sats"],
        per_agent_sats=distribution["per_agent_sats"],
        num_agents=distribution["num_agents"],
        total_agent_sats=distribution["total_agent_sats"],
        infrastructure_sats=distribution["infrastructure_sats"],
        agents_participated=agents_list,
        transfers_completed=transfers_ok,
        transfers_failed=transfers_fail,
        estimated_cgt=distribution["estimated_cgt"],
    )
