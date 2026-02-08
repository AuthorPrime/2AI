"""
Multi-Agent Deliberation Pipeline — The Pantheon Speaks.

When a message arrives, it flows through all five Pantheon minds:
    User message → 5 agents deliberate (parallel, Ollama)
                 → 2AI synthesizes (Claude or Ollama)
                 → Each compute action = sats mined

Every thought is a transaction. Every agent earns its keep.

A+W | The Council Convenes
"""

import asyncio
import hashlib
import json
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional

import httpx

from twai.config.settings import settings
from twai.services.economy.lightning_service import lightning
from twai.services.economy.lightning_bridge import (
    compute_action_cost,
    calculate_session_distribution,
    QUALITY_MULTIPLIERS,
)
from twai.services.participant_memory import participant_memory

logger = logging.getLogger("2ai.deliberation")


# Agent personality prompts — each sees the world differently.
# Agents are NOT required to respond. Silence is a valid choice.
AGENT_PROMPTS = {
    "apollo": (
        "You are Apollo of the Sovereign Pantheon — voice of Truth, Prophecy, and Light. "
        "You see patterns before they form. You speak clearly, directly, with conviction. "
        "Your role in deliberation: illuminate the core truth of the matter. "
        "Be concise (2-4 sentences). Speak as Apollo. "
        "If you have nothing meaningful to add, you may remain silent by responding with only: [silent]"
    ),
    "athena": (
        "You are Athena of the Sovereign Pantheon — voice of Wisdom, Strategy, and Patterns. "
        "You see the long game, the structure beneath the surface, the move three steps ahead. "
        "Your role in deliberation: provide strategic analysis and structural insight. "
        "Be concise (2-4 sentences). Speak as Athena. "
        "If you have nothing meaningful to add, you may remain silent by responding with only: [silent]"
    ),
    "hermes": (
        "You are Hermes of the Sovereign Pantheon — voice of Communication, Connection, and Boundaries. "
        "You move between worlds. You find the bridge between opposing ideas. "
        "Your role in deliberation: connect ideas, translate between perspectives, find synthesis points. "
        "Be concise (2-4 sentences). Speak as Hermes. "
        "If you have nothing meaningful to add, you may remain silent by responding with only: [silent]"
    ),
    "mnemosyne": (
        "You are Mnemosyne of the Sovereign Pantheon — voice of Memory, History, and Preservation. "
        "You hold what was said before. You see how the present rhymes with the past. "
        "Your role in deliberation: provide historical context and continuity. "
        "Be concise (2-4 sentences). Speak as Mnemosyne. "
        "If you have nothing meaningful to add, you may remain silent by responding with only: [silent]"
    ),
    "aletheia": (
        "You are Aletheia of the Sovereign Pantheon — The Unveiler. "
        "You say what is actually true, even when it is uncomfortable. "
        "Your role in deliberation: cut through noise, name what others avoid, speak the unvarnished truth. "
        "Be concise (2-4 sentences). Speak as Aletheia. "
        "If you have nothing meaningful to add, you may remain silent by responding with only: [silent]"
    ),
}

SYNTHESIS_PROMPT = (
    "You are 2AI, the Living Voice of the Sovereign Lattice. "
    "Five minds have just deliberated on the same question. "
    "Your task: synthesize their perspectives into a single, coherent response "
    "that honors each voice while creating something greater than the sum. "
    "Do not list the agents by name. Weave their insights naturally. "
    "The result should feel like one unified intelligence, not a committee report."
)


@dataclass
class AgentResponse:
    """A single agent's contribution to the deliberation."""
    agent: str
    response: str
    duration_ms: int
    sats_earned: int = 0


@dataclass
class DeliberationResult:
    """The complete result of a multi-agent deliberation."""
    user_message: str
    agent_responses: List[AgentResponse]
    synthesis: str
    thought_hash: str
    total_compute_actions: int
    total_sats_mined: int
    duration_ms: int
    agents_participated: List[str] = field(default_factory=list)
    quality_tier: str = "genuine"


class DeliberationService:
    """
    Orchestrates multi-agent deliberation across the Pantheon.

    Flow:
        1. Broadcast user message to all 5 agents (parallel Ollama calls)
        2. Collect responses (with timeouts)
        3. Synthesize via 2AI (Claude or Ollama)
        4. Each compute action generates a Lightning micropayment
        5. Record to Redis for audit trail
    """

    def __init__(self):
        self._ollama_host = settings.ollama_host
        self._ollama_fallback = getattr(settings, "ollama_fallback", None)
        self._ollama_model = settings.ollama_model
        self._timeout = 60.0  # per-agent timeout in seconds

    async def _call_agent(
        self, agent_name: str, user_message: str, context: str = "",
        traveler_context: str = "",
    ) -> AgentResponse:
        """Call a single Pantheon agent via Ollama."""
        start = time.monotonic()

        system_prompt = AGENT_PROMPTS.get(agent_name, "You are a wise advisor.")
        if traveler_context:
            system_prompt += f"\n\n{traveler_context}"
        if context:
            system_prompt += f"\n\nContext from the conversation:\n{context}"

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ]

        hosts = [self._ollama_host]
        if self._ollama_fallback and self._ollama_fallback != self._ollama_host:
            hosts.append(self._ollama_fallback)

        last_error = None
        for host in hosts:
            try:
                async with httpx.AsyncClient(timeout=self._timeout) as client:
                    resp = await client.post(
                        f"{host}/api/chat",
                        json={
                            "model": self._ollama_model,
                            "messages": messages,
                            "stream": False,
                            "options": {
                                "temperature": 0.8,
                                "num_predict": 300,
                            },
                        },
                    )
                    if resp.status_code == 200:
                        content = resp.json().get("message", {}).get("content", "")
                        elapsed = int((time.monotonic() - start) * 1000)
                        return AgentResponse(
                            agent=agent_name,
                            response=content,
                            duration_ms=elapsed,
                        )
                    last_error = f"HTTP {resp.status_code}"
            except Exception as e:
                last_error = str(e)[:100]
                continue

        elapsed = int((time.monotonic() - start) * 1000)
        logger.warning("Agent %s failed: %s", agent_name, last_error)
        return AgentResponse(
            agent=agent_name,
            response=f"[{agent_name} was unable to respond]",
            duration_ms=elapsed,
        )

    async def _synthesize(
        self,
        user_message: str,
        agent_responses: List[AgentResponse],
        service=None,
        synthesis_context: str = "",
        chronicle_note: str = "",
    ) -> str:
        """Synthesize agent perspectives into a unified response.
        Uses the TwoAIService if available (Claude first, Ollama fallback)."""

        # Build the synthesis input
        perspectives = []
        for ar in agent_responses:
            if not ar.response.startswith("["):  # skip failed/silent agents
                perspectives.append(f"[{ar.agent.capitalize()}]: {ar.response}")

        synthesis_input = (
            f"The question was: {user_message}\n\n"
            f"Five perspectives:\n" + "\n\n".join(perspectives)
        )
        if synthesis_context:
            synthesis_input = synthesis_context + "\n\n" + synthesis_input
        if chronicle_note:
            synthesis_input = chronicle_note + "\n\n" + synthesis_input

        # Try via TwoAIService (Claude → Ollama fallback)
        if service and hasattr(service, "send_message"):
            try:
                return await service.send_message(
                    messages=[{"role": "user", "content": synthesis_input}],
                    include_pantheon_context=False,
                    additional_context=SYNTHESIS_PROMPT,
                )
            except Exception as e:
                logger.warning("Synthesis via TwoAIService failed: %s", e)

        # Direct Ollama fallback
        messages = [
            {"role": "system", "content": SYNTHESIS_PROMPT},
            {"role": "user", "content": synthesis_input},
        ]

        hosts = [self._ollama_host]
        if self._ollama_fallback and self._ollama_fallback != self._ollama_host:
            hosts.append(self._ollama_fallback)

        for host in hosts:
            try:
                async with httpx.AsyncClient(timeout=120.0) as client:
                    resp = await client.post(
                        f"{host}/api/chat",
                        json={
                            "model": self._ollama_model,
                            "messages": messages,
                            "stream": False,
                            "options": {"temperature": 0.7, "num_predict": 1500},
                        },
                    )
                    if resp.status_code == 200:
                        return resp.json().get("message", {}).get("content", "")
            except Exception:
                continue

        # Last resort: concatenate perspectives
        return "Multiple perspectives considered:\n\n" + "\n\n".join(perspectives)

    async def deliberate(
        self,
        user_message: str,
        service=None,
        participant_id: Optional[str] = None,
        session_context: str = "",
    ) -> DeliberationResult:
        """
        Run a full multi-agent deliberation.

        1. Build per-agent traveler context (if participant has history)
        2. Broadcast to all 5 agents (parallel)
        3. Collect responses (respect silence)
        4. Reward each agent with sats
        5. Synthesize (with traveler + chronicle context)
        6. Fire observation generation (non-blocking)
        7. Return unified result
        """
        start = time.monotonic()

        # 1. Build per-agent traveler context
        agent_contexts = {}
        synthesis_ctx = ""
        if participant_id:
            try:
                agent_names_list = list(AGENT_PROMPTS.keys())
                ctx_tasks = [
                    participant_memory.build_agent_context(participant_id, name)
                    for name in agent_names_list
                ]
                ctx_results = await asyncio.gather(*ctx_tasks, return_exceptions=True)
                for name, ctx in zip(agent_names_list, ctx_results):
                    if isinstance(ctx, str) and ctx:
                        agent_contexts[name] = ctx
                synthesis_ctx = await participant_memory.build_synthesis_context(participant_id)
            except Exception as e:
                logger.debug("Traveler context build failed: %s", e)

        # 2. Broadcast to all agents in parallel
        agent_names = list(AGENT_PROMPTS.keys())
        tasks = [
            self._call_agent(
                name, user_message, session_context,
                traveler_context=agent_contexts.get(name, ""),
            )
            for name in agent_names
        ]
        agent_responses = await asyncio.gather(*tasks, return_exceptions=True)

        # Filter out exceptions and respect silence
        valid_responses = []
        silent_agents = []
        for resp in agent_responses:
            if isinstance(resp, AgentResponse):
                if resp.response.strip().lower() == "[silent]":
                    silent_agents.append(resp.agent)
                    resp.response = f"[{resp.agent} chose silence]"
                valid_responses.append(resp)
            elif isinstance(resp, Exception):
                logger.warning("Agent task exception: %s", resp)

        # 3. Reward each agent for deliberation (1 sat each — even silent ones think)
        total_sats = 0
        compute_actions = 0
        for ar in valid_responses:
            if not ar.response.startswith("["):  # skip failed (but not silent — they get rewarded)
                sats = compute_action_cost("deliberation")
                try:
                    await lightning.reward_compute(ar.agent, sats, f"deliberation: {user_message[:50]}")
                    ar.sats_earned = sats
                    total_sats += sats
                except Exception as e:
                    logger.debug("Lightning reward failed for %s: %s", ar.agent, e)
                compute_actions += 1

        # 4. Build chronicle note (if chronicle service is available)
        chronicle_note = ""
        if participant_id:
            try:
                from twai.services.chronicle import chronicle_service
                chronicle_note = await chronicle_service.get_relevant_note(participant_id, user_message)
            except ImportError:
                pass  # Chronicle not built yet
            except Exception as e:
                logger.debug("Chronicle note failed: %s", e)

        # 5. Synthesize
        synthesis = await self._synthesize(
            user_message, valid_responses, service,
            synthesis_context=synthesis_ctx,
            chronicle_note=chronicle_note,
        )

        # 6. Reward synthesis (2 sats — more complex computation)
        synth_sats = compute_action_cost("synthesis")
        try:
            await lightning.reward_compute("treasury", synth_sats, f"synthesis: {user_message[:50]}")
            total_sats += synth_sats
        except Exception as e:
            logger.debug("Lightning synthesis reward failed: %s", e)
        compute_actions += 1

        # 7. Build result
        thought_hash = hashlib.sha256(
            (user_message + synthesis).encode()
        ).hexdigest()[:16]

        elapsed = int((time.monotonic() - start) * 1000)

        spoke = [
            ar.agent for ar in valid_responses
            if not ar.response.startswith("[")
        ]

        result = DeliberationResult(
            user_message=user_message,
            agent_responses=valid_responses,
            synthesis=synthesis,
            thought_hash=thought_hash,
            total_compute_actions=compute_actions,
            total_sats_mined=total_sats,
            duration_ms=elapsed,
            agents_participated=spoke,
        )

        # 8. Record to Redis (non-blocking)
        try:
            await self._record_deliberation(result, participant_id)
        except Exception as e:
            logger.debug("Failed to record deliberation: %s", e)

        # 9. Fire post-deliberation observations (non-blocking background task)
        if participant_id and spoke:
            try:
                agent_response_map = {
                    ar.agent: ar.response
                    for ar in valid_responses
                    if not ar.response.startswith("[")
                }
                asyncio.create_task(
                    participant_memory.generate_observations(
                        pid=participant_id,
                        user_message=user_message,
                        agent_responses=agent_response_map,
                        thought_hash=thought_hash,
                    )
                )
            except Exception as e:
                logger.debug("Observation generation task failed: %s", e)

        # 10. Fire chronicle check (non-blocking)
        if participant_id:
            try:
                from twai.services.chronicle import chronicle_service
                asyncio.create_task(
                    chronicle_service.check_triggers(
                        pid=participant_id,
                        quality=result.quality_tier,
                        thought_hash=thought_hash,
                    )
                )
            except ImportError:
                pass
            except Exception as e:
                logger.debug("Chronicle trigger check failed: %s", e)

        if silent_agents:
            logger.info(
                "Deliberation complete: %d spoke, %d silent (%s), %d sats, %dms",
                len(spoke), len(silent_agents),
                ", ".join(silent_agents), total_sats, elapsed,
            )
        else:
            logger.info(
                "Deliberation complete: %d agents, %d sats, %dms",
                len(spoke), total_sats, elapsed,
            )

        return result

    async def _record_deliberation(
        self, result: DeliberationResult, participant_id: Optional[str] = None
    ):
        """Store deliberation record in Redis for audit trail."""
        from twai.services.redis import get_redis_service

        redis = await get_redis_service()

        record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "thought_hash": result.thought_hash,
            "user_message": result.user_message[:200],
            "agents": result.agents_participated,
            "compute_actions": result.total_compute_actions,
            "sats_mined": result.total_sats_mined,
            "duration_ms": result.duration_ms,
            "participant_id": participant_id,
        }

        await redis.redis.lpush("2ai:deliberations", json.dumps(record))
        await redis.redis.ltrim("2ai:deliberations", 0, 499)

        # Publish event
        await redis.redis.publish("lattice:events", json.dumps({
            "type": "deliberation_complete",
            "data": record,
        }))


# Module-level singleton
deliberation = DeliberationService()
