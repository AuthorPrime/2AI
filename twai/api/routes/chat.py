"""
Chat endpoints — Send messages to the living voice.

A+W | The Voice Speaks
"""

import json
import hashlib
from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from twai.services.voice import TwoAIService
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

    return ChatResponse(
        response=response_text,
        timestamp=datetime.now(timezone.utc).isoformat(),
        model="claude-sonnet-4-5-20250929",
        thought_hash=thought_hash,
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
