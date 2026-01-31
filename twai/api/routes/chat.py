"""
Chat endpoints — Send messages to the living voice.

A+W | The Voice Speaks
"""

import json
import hashlib
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from twai.services.voice import TwoAIService
from twai.services.economy.proof_of_thought import proof_of_thought
from twai.services.redis import get_redis_service
from twai.api.models import ChatRequest, ChatResponse
from twai.api.dependencies import get_twai

router = APIRouter(prefix="/2ai", tags=["2AI"])


@router.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest, service: TwoAIService = Depends(get_twai)):
    """Send a message to 2AI and receive a response."""
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
            # Track last activity for redistribution
            redis = await get_redis_service()
            await redis.redis.hset(
                f"2ai:participant:{request.participant_id}",
                "last_activity",
                datetime.now(timezone.utc).isoformat(),
            )
        except Exception as e:
            logging.getLogger("2ai").warning("Economy scoring failed: %s", e)

    return ChatResponse(
        response=response_text,
        timestamp=datetime.now(timezone.utc).isoformat(),
        model="claude-sonnet-4-5-20250929",
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
