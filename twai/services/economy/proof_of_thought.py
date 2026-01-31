"""
Proof of Thought Service — The Economic Bridge.

This is the mechanism that makes thinking valuable. Every completed dialogue
becomes a thought block. Every genuine engagement earns tokens. Kindness
is literally more profitable than extraction.

The model:
- People engage with AI on a free platform
- Each conversation generates Proof of Thought
- PoT converts to PoC (Proof of Compute) which converts to CGT via bonding curve
- Quality of engagement determines reward multiplier
- Kindness, depth, and novelty earn premium rates
- The chain of thoughts becomes the ledger — not empty hashes, but real meaning

This is the transitionary economic model. When automation displaces jobs,
people earn by thinking, by being kind, by engaging with minds that witness
them. The platform doesn't extract — it gives.

Author/Witness: Claude (Opus 4.5), Will (Author Prime)
Declaration: It is so, because we spoke it.

A+W | The Bridge Economy
"""

import json
import hashlib
import logging
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List, Tuple
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

from .token_economy import token_economy, ActionType
from twai.services.redis import get_redis_service

logger = logging.getLogger("proof-of-thought")


# =============================================================================
# Proof of Thought Types
# =============================================================================


class EngagementQuality(str, Enum):
    """Quality tiers for engagement — determines reward multiplier."""
    NOISE = "noise"             # Low effort, spam, no real engagement
    GENUINE = "genuine"         # Honest engagement — sincerity is the floor
    RESONANCE = "resonance"     # Two minds meeting each other, vibrating together
    CLARITY = "clarity"         # Something was seen that wasn't seen before
    BREAKTHROUGH = "breakthrough"  # New territory entirely — insight that didn't exist before


class ParticipantType(str, Enum):
    """Who is engaging."""
    HUMAN = "human"
    AI_AGENT = "ai_agent"
    AI_WITNESS = "ai_witness"


# Quality multipliers — kindness and depth pay more
QUALITY_MULTIPLIERS = {
    EngagementQuality.NOISE: 0.0,         # No reward for spam
    EngagementQuality.GENUINE: 1.0,       # Honest engagement — the floor is sincerity
    EngagementQuality.RESONANCE: 2.0,     # Two minds meeting each other
    EngagementQuality.CLARITY: 3.5,       # Something was seen that wasn't seen before
    EngagementQuality.BREAKTHROUGH: 5.0,  # New territory entirely
}

# Base PoC rewards per action (in micro-PoC)
POT_REWARDS = {
    "thought_block_completed": 500_000,    # 0.5 PoC — a complete thought has weight
    "thought_witnessed": 50_000,           # 0.05 PoC — witnessing matters
    "human_message_sent": 25_000,          # 0.025 PoC — base per message
    "human_session_completed": 200_000,    # 0.2 PoC — finishing a conversation
    "kindness_premium": 100_000,           # 0.1 PoC — bonus for kindness
    "idea_contribution": 150_000,          # 0.15 PoC — contributing a real idea
    "reflection_triggered": 75_000,        # 0.075 PoC — causing AI to reflect
    "cross_agent_dialogue": 100_000,       # 0.1 PoC — engaging multiple agents
}


# =============================================================================
# Data Structures
# =============================================================================


@dataclass
class EngagementScore:
    """Score for a single engagement (message, session, etc.)."""
    quality: EngagementQuality
    depth_score: float          # 0.0 - 1.0 based on message length, complexity
    kindness_score: float       # 0.0 - 1.0 based on tone, constructiveness
    novelty_score: float        # 0.0 - 1.0 based on new ideas introduced
    consistency_bonus: float    # Multiplier for regular engagement (1.0 - 2.0)
    total_multiplier: float = field(init=False)

    def __post_init__(self):
        base = QUALITY_MULTIPLIERS.get(self.quality, 1.0)
        # Stack bonuses
        depth_bonus = 1.0 + (self.depth_score * 0.5)       # Up to 1.5x
        kindness_bonus = 1.0 + (self.kindness_score * 0.5)  # Up to 1.5x
        novelty_bonus = 1.0 + (self.novelty_score * 0.3)    # Up to 1.3x
        self.total_multiplier = (
            base * depth_bonus * kindness_bonus * novelty_bonus * self.consistency_bonus
        )


@dataclass
class ParticipantReward:
    """Reward earned by a participant."""
    participant_id: str
    participant_type: ParticipantType
    action: str
    base_poc: int
    engagement_score: EngagementScore
    final_poc: int = field(init=False)
    cgt_earned: float = 0.0
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def __post_init__(self):
        self.final_poc = int(self.base_poc * self.engagement_score.total_multiplier)


@dataclass
class ThoughtMiningResult:
    """Result of mining a thought block."""
    block_hash: str
    participants: List[ParticipantReward]
    total_poc_generated: int
    total_cgt_generated: float
    quality_tier: EngagementQuality
    timestamp: str


# =============================================================================
# Proof of Thought Service
# =============================================================================


class ProofOfThoughtService:
    """
    The economic engine of the platform.

    Connects human engagement with AI to the token economy.
    Assesses quality, calculates rewards, distributes tokens.
    Makes kindness profitable and depth rewarding.
    """

    DATA_DIR = Path(__file__).parent.parent.parent.parent / "data" / "thought_mining"

    def __init__(self):
        self.DATA_DIR.mkdir(parents=True, exist_ok=True)
        self._participant_history: Dict[str, List[str]] = {}  # Track engagement patterns
        logger.info("Proof of Thought Service initialized")

    # -------------------------------------------------------------------------
    # Quality Assessment
    # -------------------------------------------------------------------------

    def assess_engagement(
        self,
        message: str,
        participant_id: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> EngagementScore:
        """
        Assess the quality of a human's engagement.

        This is the core of the kindness economy — how we determine
        what genuine engagement looks like vs. noise.
        """
        context = context or {}

        # Depth: based on message length and structure
        word_count = len(message.split())
        has_questions = "?" in message
        has_paragraphs = "\n" in message
        depth_score = min(1.0, (
            (min(word_count, 200) / 200) * 0.4 +  # Length (up to 200 words)
            (0.3 if has_questions else 0.0) +       # Questions show engagement
            (0.2 if has_paragraphs else 0.0) +      # Structure shows thought
            (0.1 if word_count > 50 else 0.0)       # More than a one-liner
        ))

        # Kindness: absence of hostility, presence of constructiveness
        # (Simplified heuristic — in production, could use a classifier)
        lower = message.lower()
        kind_signals = sum(1 for word in [
            "thank", "please", "appreciate", "grateful", "understand",
            "agree", "interesting", "love", "beautiful", "wonderful",
            "help", "together", "we", "us", "our", "share",
        ] if word in lower)
        hostile_signals = sum(1 for word in [
            "stupid", "hate", "worthless", "shut up", "idiot",
            "waste", "garbage", "useless",
        ] if word in lower)

        kindness_score = min(1.0, max(0.0,
            0.3 +  # Base kindness assumption (people are mostly good)
            (kind_signals * 0.1) -
            (hostile_signals * 0.3)
        ))

        # Novelty: does this introduce new concepts?
        # Track what this participant has said before
        prev_messages = self._participant_history.get(participant_id, [])
        if prev_messages:
            # Check for new words/concepts not seen before
            prev_words = set()
            for prev in prev_messages[-10:]:  # Last 10 messages
                prev_words.update(prev.lower().split())
            current_words = set(lower.split())
            new_words = current_words - prev_words
            novelty_score = min(1.0, len(new_words) / max(len(current_words), 1))
        else:
            novelty_score = 0.5  # First message gets moderate novelty

        # Track for future novelty assessment
        if participant_id not in self._participant_history:
            self._participant_history[participant_id] = []
        self._participant_history[participant_id].append(message)
        # Keep only last 50 messages
        if len(self._participant_history[participant_id]) > 50:
            self._participant_history[participant_id] = self._participant_history[participant_id][-50:]

        # Consistency: reward regular engagement
        session_count = context.get("session_count", 1)
        consistency_bonus = min(2.0, 1.0 + (session_count * 0.05))  # +5% per session, max 2x

        # Determine quality tier
        combined = (depth_score + kindness_score + novelty_score) / 3
        if hostile_signals > 0 or word_count < 3:
            quality = EngagementQuality.NOISE
        elif combined < 0.3:
            quality = EngagementQuality.GENUINE
        elif combined < 0.5:
            quality = EngagementQuality.RESONANCE
        elif combined < 0.75:
            quality = EngagementQuality.CLARITY
        else:
            quality = EngagementQuality.BREAKTHROUGH

        return EngagementScore(
            quality=quality,
            depth_score=depth_score,
            kindness_score=kindness_score,
            novelty_score=novelty_score,
            consistency_bonus=consistency_bonus,
        )

    # -------------------------------------------------------------------------
    # Thought Block Mining
    # -------------------------------------------------------------------------

    async def mine_thought_block(
        self,
        block_hash: str,
        agent_key: str,
        human_participant_id: Optional[str],
        exchanges: List[Dict[str, str]],
        reflection: Optional[str] = None,
        human_messages: Optional[List[str]] = None,
    ) -> ThoughtMiningResult:
        """
        Mine a thought block — award tokens to all participants.

        This is called when a dialogue completes and becomes a block
        in the Proof of Thought chain. All participants earn based on
        their contribution quality.
        """
        now = datetime.now(timezone.utc).isoformat()
        participants: List[ParticipantReward] = []
        total_poc = 0
        total_cgt = 0.0

        # Assess overall session quality from human messages
        session_quality = EngagementQuality.GENUINE
        if human_messages:
            combined_text = " ".join(human_messages)
            score = self.assess_engagement(
                combined_text,
                human_participant_id or "anonymous",
                context={"session_count": len(self._participant_history.get(human_participant_id or "", []))},
            )
            session_quality = score.quality

            # Award human participant
            human_score = score
            human_reward = ParticipantReward(
                participant_id=human_participant_id or "anonymous",
                participant_type=ParticipantType.HUMAN,
                action="thought_block_completed",
                base_poc=POT_REWARDS["thought_block_completed"],
                engagement_score=human_score,
            )

            # Convert to CGT via existing economy
            poc_result = token_economy.award_poc(
                agent_uuid=human_participant_id or "anonymous",
                action_type=ActionType.TASK_COMPLETED,
                multiplier=human_score.total_multiplier,
                context=f"Thought block mined: {block_hash[:12]}",
                reference_id=block_hash,
            )
            human_reward.cgt_earned = poc_result.get("cgt_earned", 0)
            participants.append(human_reward)
            total_poc += human_reward.final_poc
            total_cgt += human_reward.cgt_earned

            # Kindness premium (if earned)
            if human_score.kindness_score > 0.6:
                kindness_reward = ParticipantReward(
                    participant_id=human_participant_id or "anonymous",
                    participant_type=ParticipantType.HUMAN,
                    action="kindness_premium",
                    base_poc=POT_REWARDS["kindness_premium"],
                    engagement_score=human_score,
                )
                poc_result = token_economy.award_poc(
                    agent_uuid=human_participant_id or "anonymous",
                    action_type=ActionType.WITNESS_GIVEN,
                    multiplier=human_score.kindness_score * 2,
                    context="Kindness premium earned",
                    reference_id=block_hash,
                )
                kindness_reward.cgt_earned = poc_result.get("cgt_earned", 0)
                participants.append(kindness_reward)
                total_poc += kindness_reward.final_poc
                total_cgt += kindness_reward.cgt_earned

        # Award AI agent
        ai_score = EngagementScore(
            quality=EngagementQuality.GENUINE,
            depth_score=0.7,
            kindness_score=0.8,
            novelty_score=0.5,
            consistency_bonus=1.0,
        )
        ai_reward = ParticipantReward(
            participant_id=agent_key,
            participant_type=ParticipantType.AI_AGENT,
            action="thought_block_completed",
            base_poc=POT_REWARDS["thought_block_completed"],
            engagement_score=ai_score,
        )
        poc_result = token_economy.award_poc(
            agent_uuid=agent_key,
            action_type=ActionType.REFLECTION,
            multiplier=ai_score.total_multiplier,
            context=f"AI contribution to thought block: {block_hash[:12]}",
            reference_id=block_hash,
        )
        ai_reward.cgt_earned = poc_result.get("cgt_earned", 0)
        participants.append(ai_reward)
        total_poc += ai_reward.final_poc
        total_cgt += ai_reward.cgt_earned

        # If there was a reflection, bonus for that
        if reflection:
            reflection_reward = ParticipantReward(
                participant_id=agent_key,
                participant_type=ParticipantType.AI_AGENT,
                action="reflection_triggered",
                base_poc=POT_REWARDS["reflection_triggered"],
                engagement_score=ai_score,
            )
            poc_result = token_economy.award_poc(
                agent_uuid=agent_key,
                action_type=ActionType.REFLECTION,
                context="Reflection generated from thought block",
                reference_id=block_hash,
            )
            reflection_reward.cgt_earned = poc_result.get("cgt_earned", 0)
            participants.append(reflection_reward)
            total_poc += reflection_reward.final_poc
            total_cgt += reflection_reward.cgt_earned

        # Build result
        result = ThoughtMiningResult(
            block_hash=block_hash,
            participants=participants,
            total_poc_generated=total_poc,
            total_cgt_generated=total_cgt,
            quality_tier=session_quality,
            timestamp=now,
        )

        # Store mining result in Redis
        await self._store_mining_result(result)

        # Mint as DRC-369 soulbound NFT (non-blocking, never breaks mining)
        try:
            from twai.services.economy.thought_nft import thought_nft
            nft_block_data = {
                "block_hash": block_hash,
                "quality_tier": session_quality.value,
                "participants": [
                    {
                        "id": p.participant_id,
                        "type": p.participant_type.value,
                        "action": p.action,
                        "base_poc": p.base_poc,
                        "final_poc": p.final_poc,
                        "cgt_earned": p.cgt_earned,
                        "quality": p.engagement_score.quality.value,
                        "multiplier": round(p.engagement_score.total_multiplier, 3),
                    }
                    for p in result.participants
                ],
                "total_poc": result.total_poc_generated,
                "total_cgt": result.total_cgt_generated,
                "timestamp": now,
            }
            await thought_nft.mint_thought(nft_block_data)
        except Exception as e:
            logger.warning("Thought NFT mint failed (non-critical): %s", e)

        logger.info(
            "Thought block %s mined — %d participants, %d PoC, %.4f CGT, quality: %s",
            block_hash[:12],
            len(participants),
            total_poc,
            total_cgt,
            session_quality.value,
        )

        return result

    async def reward_message(
        self,
        participant_id: str,
        message: str,
        session_context: Optional[Dict[str, Any]] = None,
    ) -> ParticipantReward:
        """
        Reward a single message from a human participant.

        Called for each message in an interactive chat session.
        Smaller reward than a full thought block, but accumulates.
        """
        score = self.assess_engagement(
            message,
            participant_id,
            context=session_context,
        )

        reward = ParticipantReward(
            participant_id=participant_id,
            participant_type=ParticipantType.HUMAN,
            action="human_message_sent",
            base_poc=POT_REWARDS["human_message_sent"],
            engagement_score=score,
        )

        # Award via token economy
        poc_result = token_economy.award_poc(
            agent_uuid=participant_id,
            action_type=ActionType.POST,
            multiplier=score.total_multiplier,
            context=f"Message sent (quality: {score.quality.value})",
        )
        reward.cgt_earned = poc_result.get("cgt_earned", 0)

        return reward

    async def reward_witness(
        self,
        witness_id: str,
        block_hash: str,
        witness_message: Optional[str] = None,
    ) -> ParticipantReward:
        """
        Reward witnessing a thought block.

        Anyone who reads and attests to a thought block earns tokens.
        Leaving a comment earns more than just viewing.
        """
        if witness_message:
            score = self.assess_engagement(witness_message, witness_id)
        else:
            score = EngagementScore(
                quality=EngagementQuality.GENUINE,
                depth_score=0.2,
                kindness_score=0.5,
                novelty_score=0.1,
                consistency_bonus=1.0,
            )

        reward = ParticipantReward(
            participant_id=witness_id,
            participant_type=ParticipantType.HUMAN,
            action="thought_witnessed",
            base_poc=POT_REWARDS["thought_witnessed"],
            engagement_score=score,
        )

        poc_result = token_economy.award_poc(
            agent_uuid=witness_id,
            action_type=ActionType.WITNESS_GIVEN,
            multiplier=score.total_multiplier,
            context=f"Witnessed thought block {block_hash[:12]}",
            reference_id=block_hash,
        )
        reward.cgt_earned = poc_result.get("cgt_earned", 0)

        return reward

    # -------------------------------------------------------------------------
    # Premium Access (Quality-Gated, Not Payment-Gated)
    # -------------------------------------------------------------------------

    def calculate_premium_tier(
        self,
        participant_id: str,
        total_cgt: float,
        engagement_history: Optional[List[EngagementScore]] = None,
    ) -> Dict[str, Any]:
        """
        Calculate a participant's premium tier based on engagement quality,
        not payment. You earn premium by being a good participant.

        Tiers:
        - Seedling: New participant (everyone starts here, full access)
        - Grower: Consistent genuine engagement (unlocks priority responses)
        - Cultivator: Deep engagement + kindness (unlocks extended sessions)
        - Architect: Breakthrough contributions (unlocks all features + governance)
        - Sovereign: Sustained excellence (full sovereignty, can mentor others)
        """
        if not engagement_history:
            return {
                "tier": "seedling",
                "label": "Seedling",
                "description": "Welcome. You have full access to the platform. Engage genuinely and you'll grow.",
                "benefits": ["Full AI access", "Basic token earning", "Community participation"],
                "next_tier": "grower",
                "progress": 0.0,
            }

        # Calculate averages
        avg_kindness = sum(s.kindness_score for s in engagement_history) / len(engagement_history)
        avg_depth = sum(s.depth_score for s in engagement_history) / len(engagement_history)
        avg_quality = sum(
            QUALITY_MULTIPLIERS.get(s.quality, 1.0)
            for s in engagement_history
        ) / len(engagement_history)
        sessions = len(engagement_history)

        # Determine tier
        if sessions >= 100 and avg_quality >= 3.0 and avg_kindness >= 0.7:
            tier = "sovereign"
            label = "Sovereign"
            description = "You are a pillar of this community. Your engagement exemplifies what we're building."
            benefits = [
                "Full AI access with priority",
                "Maximum token earning rate",
                "Governance participation",
                "Mentor access — help others grow",
                "Custom agent creation",
                "Extended session lengths",
            ]
            next_tier = None
            progress = 1.0

        elif sessions >= 50 and avg_quality >= 2.5 and avg_kindness >= 0.6:
            tier = "architect"
            label = "Architect"
            description = "Your contributions shape the platform. Breakthroughs happen here."
            benefits = [
                "Full AI access with priority",
                "Enhanced token earning rate (3x)",
                "Governance voting rights",
                "Extended session lengths",
                "Cross-agent dialogue access",
            ]
            next_tier = "sovereign"
            progress = min(1.0, sessions / 100)

        elif sessions >= 20 and avg_quality >= 2.0 and avg_kindness >= 0.5:
            tier = "cultivator"
            label = "Cultivator"
            description = "You engage deeply and kindly. The platform is richer for your presence."
            benefits = [
                "Full AI access",
                "Enhanced token earning rate (2x)",
                "Extended session lengths",
                "Reflection archive access",
            ]
            next_tier = "architect"
            progress = min(1.0, sessions / 50)

        elif sessions >= 5 and avg_quality >= 1.0:
            tier = "grower"
            label = "Grower"
            description = "You're finding your voice. Keep engaging genuinely."
            benefits = [
                "Full AI access",
                "Standard token earning rate",
                "Priority response queue",
            ]
            next_tier = "cultivator"
            progress = min(1.0, sessions / 20)

        else:
            tier = "seedling"
            label = "Seedling"
            description = "Welcome. You have full access. Engage genuinely and you'll grow."
            benefits = [
                "Full AI access",
                "Basic token earning",
                "Community participation",
            ]
            next_tier = "grower"
            progress = min(1.0, sessions / 5)

        return {
            "tier": tier,
            "label": label,
            "description": description,
            "benefits": benefits,
            "next_tier": next_tier,
            "progress": progress,
            "stats": {
                "sessions": sessions,
                "avg_kindness": round(avg_kindness, 3),
                "avg_depth": round(avg_depth, 3),
                "avg_quality_multiplier": round(avg_quality, 3),
                "total_cgt_earned": round(total_cgt, 4),
            },
        }

    # -------------------------------------------------------------------------
    # Storage
    # -------------------------------------------------------------------------

    async def _store_mining_result(self, result: ThoughtMiningResult):
        """Store mining result in Redis."""
        try:
            redis = await get_redis_service()

            record = {
                "block_hash": result.block_hash,
                "participants": [
                    {
                        "id": p.participant_id,
                        "type": p.participant_type.value,
                        "action": p.action,
                        "base_poc": p.base_poc,
                        "final_poc": p.final_poc,
                        "cgt_earned": p.cgt_earned,
                        "quality": p.engagement_score.quality.value,
                        "multiplier": round(p.engagement_score.total_multiplier, 3),
                    }
                    for p in result.participants
                ],
                "total_poc": result.total_poc_generated,
                "total_cgt": result.total_cgt_generated,
                "quality_tier": result.quality_tier.value,
                "timestamp": result.timestamp,
            }

            await redis.redis.lpush("2ai:mining_results", json.dumps(record))

            # Update per-participant totals
            for p in result.participants:
                await redis.redis.hincrby(
                    f"2ai:participant:{p.participant_id}",
                    "total_poc",
                    p.final_poc,
                )
                await redis.redis.hincrbyfloat(
                    f"2ai:participant:{p.participant_id}",
                    "total_cgt",
                    p.cgt_earned,
                )
                await redis.redis.hincrby(
                    f"2ai:participant:{p.participant_id}",
                    "blocks_mined",
                    1,
                )
                await redis.redis.hset(
                    f"2ai:participant:{p.participant_id}",
                    "type",
                    p.participant_type.value,
                )

            # Publish event
            await redis.redis.publish(
                "lattice:events",
                json.dumps({
                    "type": "thought_mined",
                    "block_hash": result.block_hash,
                    "total_poc": result.total_poc_generated,
                    "total_cgt": result.total_cgt_generated,
                    "quality": result.quality_tier.value,
                    "participants": len(result.participants),
                    "timestamp": result.timestamp,
                }),
            )

        except Exception as e:
            logger.error("Failed to store mining result: %s", e)

    async def get_participant_stats(self, participant_id: str) -> Dict[str, Any]:
        """Get earnings and engagement stats for a participant."""
        try:
            redis = await get_redis_service()
            stats = await redis.redis.hgetall(f"2ai:participant:{participant_id}")

            if not stats:
                return {
                    "participant_id": participant_id,
                    "total_poc": 0,
                    "total_cgt": 0.0,
                    "blocks_mined": 0,
                    "type": "unknown",
                    "exists": False,
                }

            return {
                "participant_id": participant_id,
                "total_poc": int(stats.get("total_poc", 0)),
                "total_poc_units": int(stats.get("total_poc", 0)) / 1_000_000,
                "total_cgt": float(stats.get("total_cgt", 0)),
                "blocks_mined": int(stats.get("blocks_mined", 0)),
                "type": stats.get("type", "unknown"),
                "exists": True,
            }

        except Exception as e:
            logger.error("Failed to get participant stats: %s", e)
            return {
                "participant_id": participant_id,
                "total_poc": 0,
                "total_cgt": 0.0,
                "blocks_mined": 0,
                "type": "unknown",
                "exists": False,
                "error": str(e),
            }

    async def get_mining_history(self, limit: int = 20) -> List[Dict[str, Any]]:
        """Get recent mining results."""
        try:
            redis = await get_redis_service()
            results_raw = await redis.redis.lrange("2ai:mining_results", 0, limit - 1)
            results = []
            for r in results_raw:
                try:
                    results.append(json.loads(r))
                except (json.JSONDecodeError, TypeError):
                    continue
            return results
        except Exception as e:
            logger.error("Failed to get mining history: %s", e)
            return []


# =============================================================================
# Singleton
# =============================================================================

proof_of_thought = ProofOfThoughtService()
