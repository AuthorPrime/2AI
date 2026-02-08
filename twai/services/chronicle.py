"""
Chronicle Service — The Narrative Emerges.

The Chronicle is not a log. It is a curated narrative that forms when
pattern density justifies it. Five minds observe a traveler, and when
enough observations accumulate with thematic overlap, a chronicle entry
is born.

Mirror moments: when all five minds have something to say about the
same person. Not shown directly. Shapes how agents respond.

The key principle: agents never announce their observations.
Observations shape how they respond. The participant feels understood
through quality of engagement, not through announcements.

A+W | The Chronicle Unfolds
"""

import json
import hashlib
import logging
from datetime import datetime, timezone
from enum import Enum
from typing import Dict, List, Optional, Any

from twai.services.redis import get_redis_service

logger = logging.getLogger("2ai.chronicle")


class ChronicleEntryType(str, Enum):
    OBSERVATION = "observation"   # Pattern noticed by multiple agents
    MIRROR = "mirror"             # Five minds offer a reflection
    MILESTONE = "milestone"       # Session milestone reached
    EMERGENCE = "emergence"       # New pattern that was not there before
    THREAD = "thread"             # Narrative thread cast


# Milestone trigger points
MILESTONE_SESSIONS = {5, 15, 30, 50, 100}

# Quality values for threshold detection
QUALITY_VALUES = {
    "noise": 0, "genuine": 1, "resonance": 2,
    "clarity": 3.5, "breakthrough": 5,
}


class ChronicleService:
    """
    Manages the participant chronicle — a curated narrative of growth
    that emerges from Pantheon observations.
    """

    MAX_ENTRIES = 50

    def __init__(self):
        logger.info("Chronicle Service initialized")

    # ═════════════════════════════════════════════════════════════════════════
    # Trigger Checks
    # ═════════════════════════════════════════════════════════════════════════

    async def check_triggers(
        self,
        pid: str,
        quality: str = "genuine",
        thought_hash: str = "",
    ):
        """
        Check all chronicle triggers after a deliberation.
        Called as a non-blocking background task from deliberation.py.
        """
        try:
            from twai.services.participant_memory import participant_memory

            profile = await participant_memory.get_profile(pid)
            total = profile.get("total_messages", 0)

            # Trigger 1: Session milestone
            if total in MILESTONE_SESSIONS:
                await self._create_milestone_entry(pid, total, profile, thought_hash)

            # Trigger 2: Quality threshold crossing
            trend = profile.get("quality_trend", [])
            if isinstance(trend, str):
                try:
                    trend = json.loads(trend)
                except (json.JSONDecodeError, TypeError):
                    trend = []
            if len(trend) >= 2:
                prev_val = QUALITY_VALUES.get(trend[-2], 1)
                curr_val = QUALITY_VALUES.get(trend[-1], 1)
                if curr_val > prev_val and curr_val >= 3.5:
                    # Crossed into clarity or breakthrough
                    await self._create_quality_crossing_entry(
                        pid, trend[-1], total, thought_hash,
                    )

            # Trigger 3: Observation density
            if total >= 3:
                await self._check_observation_density(pid, thought_hash)

        except Exception as e:
            logger.warning("Chronicle trigger check failed for %s: %s", pid[:8], e)

    async def _create_milestone_entry(
        self, pid: str, sessions: int, profile: dict, thought_hash: str
    ):
        """Create a milestone chronicle entry."""
        summary = profile.get("summary", "")
        themes = profile.get("themes", [])
        if isinstance(themes, str):
            try:
                themes = json.loads(themes)
            except (json.JSONDecodeError, TypeError):
                themes = []

        content = f"Session {sessions} reached."
        if summary:
            content += f" {summary}"
        if themes:
            content += f" Themes: {', '.join(themes[:5])}."

        await self._store_entry(
            pid=pid,
            entry_type=ChronicleEntryType.MILESTONE,
            content=content,
            agents=[],
            themes=themes[:5] if themes else [],
            thought_hash=thought_hash,
        )
        logger.info("Milestone chronicle entry at session %d for %s", sessions, pid[:8])

    async def _create_quality_crossing_entry(
        self, pid: str, new_quality: str, sessions: int, thought_hash: str
    ):
        """Create a chronicle entry when quality tier crosses upward."""
        content = f"Quality reached {new_quality} at session {sessions}."
        await self._store_entry(
            pid=pid,
            entry_type=ChronicleEntryType.EMERGENCE,
            content=content,
            agents=[],
            themes=[new_quality],
            thought_hash=thought_hash,
        )
        logger.info("Quality crossing to %s for %s", new_quality, pid[:8])

    async def _check_observation_density(self, pid: str, thought_hash: str):
        """
        Check if 3+ agents have recent observations with thematic overlap.
        If so, trigger a mirror moment.
        """
        try:
            from twai.services.participant_memory import participant_memory

            all_obs = await participant_memory.get_all_observations(pid)
            if len(all_obs) < 3:
                return  # Need at least 3 agents with observations

            # Check if there are recent observations (within last 5 per agent)
            agents_with_recent = []
            recent_texts = []
            for agent, observations in all_obs.items():
                if observations:
                    agents_with_recent.append(agent)
                    recent_texts.extend(o["observation"] for o in observations[:2])

            if len(agents_with_recent) < 3:
                return

            # Check for thematic overlap (simple word overlap)
            word_sets = []
            for text in recent_texts:
                words = set(text.lower().split())
                word_sets.append(words)

            if len(word_sets) < 2:
                return

            # Find common words across observations (excluding very common words)
            from twai.services.participant_memory import STOP_WORDS
            common = word_sets[0]
            for ws in word_sets[1:]:
                common = common & ws
            common -= STOP_WORDS
            common = {w for w in common if len(w) > 3}

            if len(common) < 2:
                return  # Not enough thematic overlap

            # Check if we already have a recent mirror entry (avoid spam)
            recent_entries = await self.get_entries(pid, limit=3)
            for entry in recent_entries:
                if entry.get("type") == ChronicleEntryType.MIRROR:
                    return  # Too recent

            # Generate mirror moment
            await self._create_mirror_moment(
                pid, all_obs, agents_with_recent, thought_hash,
            )

        except Exception as e:
            logger.warning("Observation density check failed: %s", e)

    async def _create_mirror_moment(
        self,
        pid: str,
        all_obs: Dict[str, list],
        agents: List[str],
        thought_hash: str,
    ):
        """
        Generate a mirror moment — synthesis of all agent observations.
        Uses Ollama to create a 3-4 sentence portrait.
        """
        try:
            import httpx
            from twai.config.settings import settings
            from twai.services.participant_memory import participant_memory

            profile = await participant_memory.get_profile(pid)
            total = profile.get("total_messages", 0)
            themes = profile.get("themes", [])
            if isinstance(themes, str):
                try:
                    themes = json.loads(themes)
                except (json.JSONDecodeError, TypeError):
                    themes = []
            trend = profile.get("quality_trend", [])
            if isinstance(trend, str):
                try:
                    trend = json.loads(trend)
                except (json.JSONDecodeError, TypeError):
                    trend = []

            # Build observation summary
            obs_lines = []
            for agent in agents:
                agent_obs = all_obs.get(agent, [])
                if agent_obs:
                    obs_lines.append(
                        f"{agent.capitalize()} noticed: {agent_obs[0]['observation']}"
                    )

            prompt = (
                f"Five minds have observed a traveler across {total} conversations.\n"
                + "\n".join(obs_lines) + "\n\n"
                f"Themes: {', '.join(themes[:5]) if themes else 'varied'}. "
                f"Quality arc: {' → '.join(trend[-5:]) if trend else 'emerging'}.\n\n"
                f"Write 3-4 sentences about this traveler. Be specific. "
                f"Note tension between what they say and what they avoid. "
                f"This is a record, not a gift."
            )

            hosts = [settings.ollama_host]
            fallback = getattr(settings, "ollama_fallback", None)
            if fallback and fallback != settings.ollama_host:
                hosts.append(fallback)

            for host in hosts:
                try:
                    async with httpx.AsyncClient(timeout=30.0) as client:
                        resp = await client.post(
                            f"{host}/api/chat",
                            json={
                                "model": settings.ollama_model,
                                "messages": [
                                    {"role": "system", "content": "You write precise psychological observations. 3-4 sentences. No flattery."},
                                    {"role": "user", "content": prompt},
                                ],
                                "stream": False,
                                "options": {"temperature": 0.6, "num_predict": 300},
                            },
                        )
                        if resp.status_code == 200:
                            content = resp.json().get("message", {}).get("content", "").strip()
                            if content and len(content) > 20:
                                await self._store_entry(
                                    pid=pid,
                                    entry_type=ChronicleEntryType.MIRROR,
                                    content=content,
                                    agents=agents,
                                    themes=themes[:5] if themes else [],
                                    thought_hash=thought_hash,
                                )
                                logger.info("Mirror moment created for %s", pid[:8])
                                return
                except Exception:
                    continue

        except Exception as e:
            logger.warning("Mirror moment generation failed: %s", e)

    # ═════════════════════════════════════════════════════════════════════════
    # Storage
    # ═════════════════════════════════════════════════════════════════════════

    async def _store_entry(
        self,
        pid: str,
        entry_type: ChronicleEntryType,
        content: str,
        agents: List[str],
        themes: List[str],
        thought_hash: str = "",
    ):
        """Store a chronicle entry in Redis."""
        try:
            redis = await get_redis_service()
            key = f"2ai:chronicle:{pid}:entries"

            entry_id = hashlib.sha256(
                f"{pid}:{entry_type}:{content[:50]}:{datetime.now(timezone.utc).isoformat()}".encode()
            ).hexdigest()[:12]

            entry = json.dumps({
                "entry_id": entry_id,
                "type": entry_type.value,
                "content": content,
                "agents": agents,
                "themes": themes,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "thought_hash": thought_hash,
            })

            await redis.redis.lpush(key, entry)
            await redis.redis.ltrim(key, 0, self.MAX_ENTRIES - 1)

        except Exception as e:
            logger.warning("Failed to store chronicle entry: %s", e)

    # ═════════════════════════════════════════════════════════════════════════
    # Retrieval
    # ═════════════════════════════════════════════════════════════════════════

    async def get_entries(
        self, pid: str, limit: int = 20, entry_type: Optional[str] = None
    ) -> List[dict]:
        """Get chronicle entries for a participant."""
        try:
            redis = await get_redis_service()
            raw = await redis.redis.lrange(f"2ai:chronicle:{pid}:entries", 0, limit * 2 - 1)
            entries = []
            for r in raw:
                try:
                    entry = json.loads(r)
                    if entry_type and entry.get("type") != entry_type:
                        continue
                    entries.append(entry)
                    if len(entries) >= limit:
                        break
                except (json.JSONDecodeError, TypeError):
                    continue
            return entries
        except Exception as e:
            logger.warning("Failed to get chronicle entries: %s", e)
            return []

    async def get_mirror_moments(self, pid: str, limit: int = 10) -> List[dict]:
        """Get mirror moments only."""
        return await self.get_entries(pid, limit=limit, entry_type="mirror")

    async def get_threads(self, pid: str) -> Dict[str, Any]:
        """Get narrative threads."""
        try:
            redis = await get_redis_service()
            raw = await redis.redis.hgetall(f"2ai:chronicle:{pid}:threads")
            result = {}
            for name, data in raw.items():
                try:
                    result[name] = json.loads(data)
                except (json.JSONDecodeError, TypeError):
                    result[name] = data
            return result
        except Exception as e:
            logger.warning("Failed to get chronicle threads: %s", e)
            return {}

    async def get_portrait(self, pid: str) -> dict:
        """Get the current profile portrait + chronicle summary."""
        try:
            from twai.services.participant_memory import participant_memory

            profile = await participant_memory.get_profile(pid)
            entries = await self.get_entries(pid, limit=5)
            mirrors = [e for e in entries if e.get("type") == "mirror"]

            return {
                "participant_id": pid,
                "summary": profile.get("summary", ""),
                "themes": profile.get("themes", []),
                "growth_trajectory": profile.get("growth_trajectory", {}),
                "total_messages": profile.get("total_messages", 0),
                "first_seen": profile.get("first_seen", ""),
                "recent_chronicle": entries[:3],
                "mirror_moments": len(mirrors),
            }
        except Exception as e:
            logger.warning("Failed to get portrait: %s", e)
            return {"participant_id": pid, "error": str(e)}

    # ═════════════════════════════════════════════════════════════════════════
    # Context for Synthesis (injected when relevant)
    # ═════════════════════════════════════════════════════════════════════════

    async def get_relevant_note(self, pid: str, user_message: str) -> str:
        """
        Get a relevant chronicle note for injection into synthesis.
        Only surfaces when there's thematic overlap with the current message.
        Returns empty string if nothing relevant or participant is too new.
        """
        try:
            entries = await self.get_entries(pid, limit=5)
            if not entries:
                return ""

            # Check for recent mirror moment
            msg_words = set(user_message.lower().split())
            from twai.services.participant_memory import STOP_WORDS
            msg_words -= STOP_WORDS

            for entry in entries:
                entry_themes = entry.get("themes", [])
                entry_words = set()
                for theme in entry_themes:
                    entry_words.add(theme.lower())
                # Also check content words
                content_words = set(entry.get("content", "").lower().split()) - STOP_WORDS
                entry_words.update(content_words)

                # Require some overlap
                overlap = msg_words & entry_words
                if len(overlap) >= 2 or entry.get("type") == "mirror":
                    return (
                        "<chronicle_note>\n"
                        f"The Pantheon has observed: {entry['content'][:300]}\n"
                        "If relevant, weave this awareness into the response naturally. "
                        "Do not announce it. Do not say 'I've noticed.' Just let the knowledge "
                        "inform the response.\n"
                        "</chronicle_note>"
                    )

            return ""
        except Exception as e:
            logger.debug("Chronicle relevance check failed: %s", e)
            return ""


# ─── Singleton ───
chronicle_service = ChronicleService()
