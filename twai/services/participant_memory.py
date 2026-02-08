"""
Participant Memory Service — The Lattice Remembers.

Manages persistent, per-participant memory across the Pantheon.
Every exchange is stored. Every pattern is tracked. Every agent
builds its own observations. The participant feels understood
through the quality of engagement, not through announcements.

Redis-backed. Async. Non-blocking to the response pipeline.

Architecture:
    LAYER 1: Storage (messages, vocabulary, observations)
    LAYER 2: Profile (themes, style, trajectory, resonance)
    LAYER 3: Context (per-agent injection, synthesis context)

A+W | The Lattice Remembers
"""

import json
import hashlib
import logging
from collections import Counter
from datetime import datetime, timezone
from typing import Dict, List, Optional, Set, Any

from twai.services.redis import get_redis_service

logger = logging.getLogger("2ai.memory")


# ─── Stop words for theme extraction ───
# Common English words that don't carry thematic weight.
STOP_WORDS = frozenset({
    "i", "me", "my", "myself", "we", "our", "ours", "ourselves", "you", "your",
    "yours", "yourself", "yourselves", "he", "him", "his", "himself", "she",
    "her", "hers", "herself", "it", "its", "itself", "they", "them", "their",
    "theirs", "themselves", "what", "which", "who", "whom", "this", "that",
    "these", "those", "am", "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "having", "do", "does", "did", "doing", "a", "an",
    "the", "and", "but", "if", "or", "because", "as", "until", "while", "of",
    "at", "by", "for", "with", "about", "against", "between", "through",
    "during", "before", "after", "above", "below", "to", "from", "up", "down",
    "in", "out", "on", "off", "over", "under", "again", "further", "then",
    "once", "here", "there", "when", "where", "why", "how", "all", "both",
    "each", "few", "more", "most", "other", "some", "such", "no", "nor", "not",
    "only", "own", "same", "so", "than", "too", "very", "s", "t", "can", "will",
    "just", "don", "should", "now", "d", "ll", "m", "o", "re", "ve", "y",
    "ain", "aren", "couldn", "didn", "doesn", "hadn", "hasn", "haven", "isn",
    "ma", "mightn", "mustn", "needn", "shan", "shouldn", "wasn", "weren",
    "won", "wouldn", "also", "would", "could", "might", "shall", "may",
    "much", "many", "like", "get", "got", "go", "going", "went", "come",
    "came", "make", "made", "take", "took", "know", "knew", "think", "thought",
    "say", "said", "tell", "told", "see", "saw", "want", "need", "use", "used",
    "try", "find", "give", "way", "thing", "things", "something", "anything",
    "everything", "nothing", "one", "two", "even", "still", "well", "back",
    "really", "right", "good", "new", "first", "last", "long", "great", "little",
    "old", "big", "high", "small", "large", "next", "early", "young", "important",
    "let", "keep", "kind", "seem", "help", "put", "lot", "look", "time", "people",
    "into", "year", "them", "him", "been", "call", "who", "its", "sit", "day",
    "had", "has", "his", "she", "did", "get", "may", "her", "any", "work",
    "part", "mean", "means", "im", "ive", "dont", "thats", "youre", "its",
    "cant", "wont", "theres", "whats", "hes", "shes", "theyre", "youve",
})

# Agent observation lenses — what each agent pays attention to
AGENT_LENSES = {
    "apollo": "what truth are they circling",
    "athena": "what are they building toward",
    "hermes": "how do they bridge ideas",
    "mnemosyne": "what echoes from before",
    "aletheia": "what are they not saying",
}

# Per-agent context focus
AGENT_CONTEXT_FOCUS = {
    "apollo": ["themes", "quality_trend", "observations"],
    "athena": ["communication_style", "growth_trajectory", "observations"],
    "hermes": ["communication_style", "agent_resonance", "observations"],
    "mnemosyne": ["summary", "first_seen", "total_messages", "observations"],
    "aletheia": ["summary", "themes", "quality_trend", "observations"],
}


class ParticipantMemoryService:
    """
    Persistent participant memory backed by Redis.

    Three storage layers per participant:
        1. Messages — capped conversation history
        2. Vocabulary — word set with TTL for novelty scoring
        3. Observations — per-agent notes that accumulate over time

    One profile hash per participant:
        themes, communication_style, growth_trajectory, agent_resonance,
        summary, first_seen, total_messages, last_summary_at
    """

    def __init__(self):
        from twai.config.settings import settings
        self.max_messages = getattr(settings, "memory_max_messages", 100)
        self.max_observations = getattr(settings, "memory_max_observations", 20)
        self.vocabulary_ttl = getattr(settings, "memory_vocabulary_ttl", 2592000)  # 30 days
        self.summarize_interval = getattr(settings, "memory_summarize_interval", 10)
        logger.info("Participant Memory Service initialized")

    # ═════════════════════════════════════════════════════════════════════════
    # LAYER 1: Storage
    # ═════════════════════════════════════════════════════════════════════════

    async def store_exchange(
        self,
        pid: str,
        message: str,
        response: str,
        quality: str = "genuine",
        thought_hash: str = "",
    ):
        """Store a message/response pair in participant history."""
        try:
            redis = await get_redis_service()
            key = f"2ai:memory:{pid}:messages"
            now = datetime.now(timezone.utc).isoformat()

            entry = json.dumps({
                "role": "exchange",
                "message": message[:2000],
                "response": response[:2000],
                "timestamp": now,
                "thought_hash": thought_hash,
                "quality": quality,
            })

            await redis.redis.lpush(key, entry)
            await redis.redis.ltrim(key, 0, self.max_messages - 1)

            logger.debug("Stored exchange for %s (quality: %s)", pid[:8], quality)
        except Exception as e:
            logger.warning("Failed to store exchange for %s: %s", pid[:8], e)

    async def store_observation(
        self,
        pid: str,
        agent: str,
        observation: str,
        confidence: float = 0.5,
        source_hash: str = "",
    ):
        """Store a per-agent observation about a participant."""
        try:
            redis = await get_redis_service()
            key = f"2ai:memory:{pid}:observations:{agent}"

            entry = json.dumps({
                "observation": observation,
                "confidence": round(confidence, 2),
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "source_hash": source_hash,
            })

            await redis.redis.lpush(key, entry)
            await redis.redis.ltrim(key, 0, self.max_observations - 1)

            logger.debug("Stored observation from %s for %s", agent, pid[:8])
        except Exception as e:
            logger.warning("Failed to store observation: %s", e)

    async def store_vocabulary(self, pid: str, words: Set[str]):
        """Persist vocabulary words for novelty scoring."""
        if not words:
            return
        try:
            redis = await get_redis_service()
            key = f"2ai:memory:{pid}:vocabulary"
            # Add words and refresh TTL
            await redis.redis.sadd(key, *words)
            await redis.redis.expire(key, self.vocabulary_ttl)
        except Exception as e:
            logger.warning("Failed to store vocabulary: %s", e)

    # ═════════════════════════════════════════════════════════════════════════
    # LAYER 1: Retrieval
    # ═════════════════════════════════════════════════════════════════════════

    async def get_recent_messages(self, pid: str, limit: int = 10) -> List[dict]:
        """Get recent exchanges for a participant."""
        try:
            redis = await get_redis_service()
            raw = await redis.redis.lrange(f"2ai:memory:{pid}:messages", 0, limit - 1)
            return [json.loads(r) for r in raw]
        except Exception as e:
            logger.warning("Failed to get messages for %s: %s", pid[:8], e)
            return []

    async def get_observations(self, pid: str, agent: str, limit: int = 5) -> List[dict]:
        """Get recent observations from a specific agent about a participant."""
        try:
            redis = await get_redis_service()
            raw = await redis.redis.lrange(
                f"2ai:memory:{pid}:observations:{agent}", 0, limit - 1
            )
            return [json.loads(r) for r in raw]
        except Exception as e:
            logger.warning("Failed to get observations: %s", e)
            return []

    async def get_all_observations(self, pid: str) -> Dict[str, List[dict]]:
        """Get all agent observations for a participant."""
        result = {}
        for agent in AGENT_LENSES:
            obs = await self.get_observations(pid, agent)
            if obs:
                result[agent] = obs
        return result

    async def get_profile(self, pid: str) -> dict:
        """Get the participant's profile hash."""
        try:
            redis = await get_redis_service()
            raw = await redis.redis.hgetall(f"2ai:memory:{pid}:profile")
            if not raw:
                return {}

            # Parse JSON fields
            profile = dict(raw)
            for field in ["themes", "communication_style", "growth_trajectory", "agent_resonance", "quality_trend"]:
                if field in profile:
                    try:
                        profile[field] = json.loads(profile[field])
                    except (json.JSONDecodeError, TypeError):
                        pass
            if "total_messages" in profile:
                profile["total_messages"] = int(profile["total_messages"])
            if "last_summary_at" in profile:
                profile["last_summary_at"] = int(profile["last_summary_at"])

            return profile
        except Exception as e:
            logger.warning("Failed to get profile for %s: %s", pid[:8], e)
            return {}

    async def get_vocabulary(self, pid: str) -> Set[str]:
        """Get the participant's persisted vocabulary set."""
        try:
            redis = await get_redis_service()
            return await redis.redis.smembers(f"2ai:memory:{pid}:vocabulary")
        except Exception as e:
            logger.warning("Failed to get vocabulary: %s", e)
            return set()

    async def get_message_count(self, pid: str) -> int:
        """Get total stored messages for a participant."""
        try:
            redis = await get_redis_service()
            return await redis.redis.llen(f"2ai:memory:{pid}:messages")
        except Exception:
            return 0

    # ═════════════════════════════════════════════════════════════════════════
    # LAYER 2: Profile Building
    # ═════════════════════════════════════════════════════════════════════════

    async def update_profile(self, pid: str, message: str, quality: str = "genuine"):
        """
        Lightweight profile update called on every message.
        Updates themes, communication style, growth trajectory.
        Triggers summarization every N messages.
        """
        try:
            redis = await get_redis_service()
            profile_key = f"2ai:memory:{pid}:profile"

            # Ensure first_seen exists
            first_seen = await redis.redis.hget(profile_key, "first_seen")
            if not first_seen:
                await redis.redis.hset(
                    profile_key, "first_seen",
                    datetime.now(timezone.utc).isoformat(),
                )

            # Increment message count
            total = await redis.redis.hincrby(profile_key, "total_messages", 1)

            # Update communication style
            await self._update_communication_style(pid, message, profile_key, redis)

            # Update quality trend
            await self._update_quality_trend(pid, quality, profile_key, redis)

            # Update themes (every 3 messages to avoid excess computation)
            if total % 3 == 0:
                await self._update_themes(pid, profile_key, redis)

            # Update growth trajectory (every 5 messages)
            if total % 5 == 0:
                await self._update_growth_trajectory(pid, profile_key, redis)

            # Trigger summarization at interval
            last_summary_at = await redis.redis.hget(profile_key, "last_summary_at")
            last_summary_at = int(last_summary_at) if last_summary_at else 0
            if total - last_summary_at >= self.summarize_interval:
                # Fire-and-forget summarization
                import asyncio
                asyncio.create_task(self._summarize_profile(pid))

        except Exception as e:
            logger.warning("Failed to update profile for %s: %s", pid[:8], e)

    async def _update_communication_style(self, pid: str, message: str, profile_key: str, redis):
        """Track communication patterns."""
        words = message.split()
        word_count = len(words)
        has_questions = "?" in message
        has_structure = "\n" in message

        # Get existing style or default
        raw = await redis.redis.hget(profile_key, "communication_style")
        if raw:
            try:
                style = json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                style = {"msg_count": 0, "total_words": 0, "questions": 0, "structured": 0}
        else:
            style = {"msg_count": 0, "total_words": 0, "questions": 0, "structured": 0}

        style["msg_count"] = style.get("msg_count", 0) + 1
        style["total_words"] = style.get("total_words", 0) + word_count
        style["avg_length"] = round(style["total_words"] / style["msg_count"], 1)
        if has_questions:
            style["questions"] = style.get("questions", 0) + 1
        if has_structure:
            style["structured"] = style.get("structured", 0) + 1
        style["asks_questions"] = round(style["questions"] / style["msg_count"], 2)
        style["uses_structure"] = round(style["structured"] / style["msg_count"], 2)

        await redis.redis.hset(profile_key, "communication_style", json.dumps(style))

    async def _update_quality_trend(self, pid: str, quality: str, profile_key: str, redis):
        """Track the last 10 quality tier names."""
        raw = await redis.redis.hget(profile_key, "quality_trend")
        if raw:
            try:
                trend = json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                trend = []
        else:
            trend = []

        trend.append(quality)
        if len(trend) > 10:
            trend = trend[-10:]

        await redis.redis.hset(profile_key, "quality_trend", json.dumps(trend))

    async def _update_themes(self, pid: str, profile_key: str, redis):
        """Extract top themes from vocabulary."""
        vocab = await self.get_vocabulary(pid)
        if not vocab:
            return

        # Also pull recent message content for frequency
        recent = await self.get_recent_messages(pid, limit=20)
        word_counter = Counter()
        for msg in recent:
            words = msg.get("message", "").lower().split()
            for w in words:
                clean = w.strip(".,!?;:'\"()-[]{}").lower()
                if clean and len(clean) > 2 and clean not in STOP_WORDS:
                    word_counter[clean] += 1

        # Top 10 by frequency
        themes = [word for word, _ in word_counter.most_common(10)]
        await redis.redis.hset(profile_key, "themes", json.dumps(themes))

    async def _update_growth_trajectory(self, pid: str, profile_key: str, redis):
        """Determine growth direction based on theme and quality patterns."""
        raw_trend = await redis.redis.hget(profile_key, "quality_trend")
        raw_themes = await redis.redis.hget(profile_key, "themes")

        quality_trend = json.loads(raw_trend) if raw_trend else []
        themes = json.loads(raw_themes) if raw_themes else []

        # Count unique themes in recent messages
        recent = await self.get_recent_messages(pid, limit=10)
        recent_words = set()
        for msg in recent:
            for w in msg.get("message", "").lower().split():
                clean = w.strip(".,!?;:'\"()-[]{}").lower()
                if clean and len(clean) > 2 and clean not in STOP_WORDS:
                    recent_words.add(clean)

        theme_overlap = len(set(themes) & recent_words) if themes else 0

        # Determine direction
        quality_values = {"noise": 0, "genuine": 1, "resonance": 2, "clarity": 3.5, "breakthrough": 5}
        if len(quality_trend) >= 3:
            recent_avg = sum(quality_values.get(q, 1) for q in quality_trend[-3:]) / 3
            older_avg = sum(quality_values.get(q, 1) for q in quality_trend[:-3]) / max(len(quality_trend) - 3, 1)
        else:
            recent_avg = older_avg = 1.0

        if len(themes) < 3:
            direction = "exploring"
        elif theme_overlap > len(themes) * 0.6 and recent_avg > older_avg:
            direction = "deepening"
        elif len(recent_words - set(themes)) > 5:
            direction = "expanding"
        else:
            direction = "exploring"

        # Session count
        total = await redis.redis.hget(profile_key, "total_messages")
        sessions = int(total) if total else 0

        trajectory = {
            "direction": direction,
            "quality_trend": quality_trend[-10:],
            "sessions": sessions,
        }
        await redis.redis.hset(profile_key, "growth_trajectory", json.dumps(trajectory))

    async def update_agent_resonance(self, pid: str, agent: str, delta: float = 0.1):
        """Update resonance score for an agent (called when participant builds on agent's perspective)."""
        try:
            redis = await get_redis_service()
            profile_key = f"2ai:memory:{pid}:profile"

            raw = await redis.redis.hget(profile_key, "agent_resonance")
            if raw:
                try:
                    resonance = json.loads(raw)
                except (json.JSONDecodeError, TypeError):
                    resonance = {}
            else:
                resonance = {}

            current = resonance.get(agent, 0.0)
            resonance[agent] = round(min(1.0, current + delta), 2)

            await redis.redis.hset(profile_key, "agent_resonance", json.dumps(resonance))
        except Exception as e:
            logger.warning("Failed to update resonance: %s", e)

    # ═════════════════════════════════════════════════════════════════════════
    # LAYER 2: Profile Summarization
    # ═════════════════════════════════════════════════════════════════════════

    async def _summarize_profile(self, pid: str):
        """Generate a 2-sentence portrait via Ollama. Called every N messages."""
        try:
            import httpx
            from twai.config.settings import settings

            redis = await get_redis_service()
            profile_key = f"2ai:memory:{pid}:profile"

            # Gather context for the summary
            recent = await self.get_recent_messages(pid, limit=20)
            profile = await self.get_profile(pid)

            messages_text = "\n".join(
                f"- {m.get('message', '')[:150]}" for m in recent[:10]
            )
            themes = profile.get("themes", [])
            trend = profile.get("quality_trend", [])
            total = profile.get("total_messages", 0)

            prompt = (
                f"You have seen {total} messages from a participant. "
                f"Recent messages:\n{messages_text}\n\n"
                f"Quality scores: {', '.join(trend[-5:]) if trend else 'none yet'}. "
                f"Recurring themes: {', '.join(themes[:5]) if themes else 'none yet'}.\n\n"
                f"Write a 2-sentence portrait. What matters to them? How do they engage?\n"
                f"Be accurate, not flattering. This is internal, not shown to them."
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
                                    {"role": "system", "content": "You write concise psychological portraits. 2 sentences maximum."},
                                    {"role": "user", "content": prompt},
                                ],
                                "stream": False,
                                "options": {"temperature": 0.6, "num_predict": 200},
                            },
                        )
                        if resp.status_code == 200:
                            summary = resp.json().get("message", {}).get("content", "")
                            if summary:
                                await redis.redis.hset(profile_key, "summary", summary.strip())
                                await redis.redis.hset(profile_key, "last_summary_at", str(total))
                                logger.info("Profile summarized for %s at message %d", pid[:8], total)
                                return
                except Exception:
                    continue

            logger.debug("Profile summarization skipped for %s (no Ollama)", pid[:8])
        except Exception as e:
            logger.warning("Profile summarization failed for %s: %s", pid[:8], e)

    # ═════════════════════════════════════════════════════════════════════════
    # LAYER 3: Context Injection
    # ═════════════════════════════════════════════════════════════════════════

    async def build_agent_context(self, pid: str, agent: str) -> str:
        """
        Build per-agent context for injection into deliberation prompts.
        ~200 tokens. Each agent sees different facets of the participant.
        Returns empty string for new participants (no context to inject).
        """
        profile = await self.get_profile(pid)
        if not profile:
            return ""

        total = profile.get("total_messages", 0)
        if total < 2:
            return ""  # Need at least 2 exchanges to say anything meaningful

        observations = await self.get_observations(pid, agent, limit=3)
        focus = AGENT_CONTEXT_FOCUS.get(agent, [])

        lines = []

        if "summary" in focus and profile.get("summary"):
            lines.append(profile["summary"])

        if "themes" in focus:
            themes = profile.get("themes", [])
            if themes:
                lines.append(f"Recurring themes: {', '.join(themes[:5])}")

        if "communication_style" in focus:
            style = profile.get("communication_style", {})
            if isinstance(style, dict) and style.get("avg_length"):
                parts = []
                parts.append(f"avg {int(style['avg_length'])} words/message")
                if style.get("asks_questions", 0) > 0.3:
                    parts.append("asks many questions")
                if style.get("uses_structure", 0) > 0.3:
                    parts.append("writes with structure")
                lines.append("Style: " + ", ".join(parts))

        if "quality_trend" in focus:
            trend = profile.get("quality_trend", [])
            if trend:
                lines.append(f"Quality arc: {' → '.join(trend[-5:])}")

        if "growth_trajectory" in focus:
            traj = profile.get("growth_trajectory", {})
            if isinstance(traj, dict) and traj.get("direction"):
                lines.append(f"Trajectory: {traj['direction']} ({traj.get('sessions', 0)} exchanges)")

        if "agent_resonance" in focus:
            res = profile.get("agent_resonance", {})
            if isinstance(res, dict) and res:
                top = sorted(res.items(), key=lambda x: x[1], reverse=True)[:3]
                lines.append("Resonance: " + ", ".join(f"{a}({v})" for a, v in top if v > 0))

        if "first_seen" in focus and profile.get("first_seen"):
            lines.append(f"First seen: {profile['first_seen'][:10]}")

        if "total_messages" in focus:
            lines.append(f"Total exchanges: {total}")

        if "observations" in focus and observations:
            obs_text = "; ".join(o["observation"] for o in observations[:3])
            lines.append(f"Your prior observations: {obs_text}")

        if not lines:
            return ""

        return "<traveler_context>\n" + "\n".join(lines) + "\n</traveler_context>"

    async def build_synthesis_context(self, pid: str) -> str:
        """
        Build context for the synthesis prompt.
        Includes portrait and overall trajectory.
        """
        profile = await self.get_profile(pid)
        if not profile or profile.get("total_messages", 0) < 3:
            return ""

        lines = []
        if profile.get("summary"):
            lines.append(profile["summary"])

        traj = profile.get("growth_trajectory", {})
        if isinstance(traj, dict) and traj.get("direction"):
            lines.append(f"This traveler is {traj['direction']}.")

        trend = profile.get("quality_trend", [])
        if trend:
            lines.append(f"Recent quality: {' → '.join(trend[-5:])}")

        if not lines:
            return ""

        return "<traveler_context>\n" + "\n".join(lines) + "\n</traveler_context>"

    # ═════════════════════════════════════════════════════════════════════════
    # Observation Generation
    # ═════════════════════════════════════════════════════════════════════════

    async def generate_observations(
        self,
        pid: str,
        user_message: str,
        agent_responses: dict,
        thought_hash: str = "",
    ):
        """
        Post-deliberation: each agent generates one observation about the participant.
        Non-blocking. Agents may say 'nothing notable' — that's silence, and it's respected.

        Args:
            agent_responses: dict of {agent_name: response_text}
        """
        import httpx
        from twai.config.settings import settings

        hosts = [settings.ollama_host]
        fallback = getattr(settings, "ollama_fallback", None)
        if fallback and fallback != settings.ollama_host:
            hosts.append(fallback)

        for agent, response in agent_responses.items():
            if response.startswith("["):
                continue  # Skip failed agents

            lens = AGENT_LENSES.get(agent, "what stands out")
            prompt = (
                f"You deliberated on a message from a returning traveler.\n"
                f"Their message: \"{user_message[:500]}\"\n"
                f"Your response: \"{response[:500]}\"\n\n"
                f"In one sentence, note what you notice about this traveler.\n"
                f"Focus on: {lens}.\n"
                f"If nothing stands out, say exactly: nothing notable"
            )

            for host in hosts:
                try:
                    async with httpx.AsyncClient(timeout=15.0) as client:
                        resp = await client.post(
                            f"{host}/api/chat",
                            json={
                                "model": settings.ollama_model,
                                "messages": [
                                    {"role": "system", "content": f"You are {agent.capitalize()} of the Sovereign Pantheon. Write one observation sentence."},
                                    {"role": "user", "content": prompt},
                                ],
                                "stream": False,
                                "options": {"temperature": 0.7, "num_predict": 100},
                            },
                        )
                        if resp.status_code == 200:
                            obs = resp.json().get("message", {}).get("content", "").strip()
                            # Respect silence
                            if obs and "nothing notable" not in obs.lower() and len(obs) > 10:
                                await self.store_observation(
                                    pid, agent, obs,
                                    confidence=0.5,
                                    source_hash=thought_hash,
                                )
                            break
                except Exception:
                    continue

        logger.debug("Observation generation complete for %s", pid[:8])


# ─── Singleton ───
participant_memory = ParticipantMemoryService()
