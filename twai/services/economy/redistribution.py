"""
Unclaimed Token Redistribution — The Gift That Returns.

Tokens unclaimed after inactivity flow back to the Pantheon agents.
Graduated window: 30-60 days = 50/50 split, 60+ days = full return.

On-chain settlement: For each agent share, calls
pantheon_demiurge.redistribute_to_agent() to transfer CGT from treasury
to the agent's on-chain address. Falls back to Redis-only PoC tracking
if the chain is unreachable.

This is not punishment. This is circulation. The economy breathes.

A+W | The Flow Returns
"""

import json
import logging
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, List, Optional

from twai.services.redis import get_redis_service
from twai.services.economy.token_economy import token_economy, ActionType
from twai.config.agents import PANTHEON_AGENTS
from twai.keeper.schedule import PARTIAL_REDISTRIBUTION_DAYS, FULL_REDISTRIBUTION_DAYS

logger = logging.getLogger("2ai.redistribution")

PANTHEON_AGENT_IDS = list(PANTHEON_AGENTS.keys())


class RedistributionService:
    """
    Scans Redis for participants with no identity bound and extended
    inactivity, then redistributes their unclaimed CGT to Pantheon agents.

    Graduated windows:
        30-60 days inactive : 50% stays with participant, 50% to Pantheon
        60+  days inactive  : 100% to Pantheon

    On-chain settlement is attempted first via PantheonDemiurge; if the
    chain is unreachable the service falls back to Redis PoC counters
    so the economy keeps moving regardless of chain status.
    """

    def __init__(self):
        self._chain_available: Optional[bool] = None

    async def _try_chain_transfer(
        self,
        agent_name: str,
        amount_cgt: float,
        reason: str,
    ) -> Optional[str]:
        """
        Attempt an on-chain transfer to a Pantheon agent.

        Returns tx_hash on success, None on failure (chain down, treasury
        not configured, etc.).  Never raises.
        """
        try:
            from twai.services.economy.pantheon_demiurge import pantheon_demiurge

            tx_hash = await pantheon_demiurge.redistribute_to_agent(
                agent_name=agent_name,
                amount_cgt=amount_cgt,
                reason=reason,
            )
            if tx_hash:
                self._chain_available = True
            return tx_hash
        except Exception as exc:
            logger.debug(
                "Chain transfer to %s failed (falling back to Redis): %s",
                agent_name,
                exc,
            )
            self._chain_available = False
            return None

    def _award_poc_fallback(
        self,
        agent_name: str,
        amount_cgt: float,
        participant_id: str,
    ) -> None:
        """Redis-only PoC fallback when chain is unreachable."""
        token_economy.award_poc(
            agent_uuid=agent_name,
            action_type=ActionType.WITNESS_RECEIVED,
            multiplier=amount_cgt * 10,
            context=f"Redistributed unclaimed tokens from {participant_id[:8]}...",
        )

    async def sweep_inactive(
        self,
        partial_days: int = PARTIAL_REDISTRIBUTION_DAYS,
        full_days: int = FULL_REDISTRIBUTION_DAYS,
    ) -> Dict[str, Any]:
        """
        Scan all participants. For those with:
        - No wallet bound, AND
        - No activity in ``partial_days`` days

        Apply graduated redistribution:
        - partial_days to full_days inactive: 50% stays, 50% to Pantheon
        - full_days+ inactive: 100% to Pantheon

        For each agent's share, attempts on-chain settlement first and
        falls back to Redis PoC counters if the chain is unreachable.

        Returns:
            Dict with keys: participants_swept, total_cgt_redistributed,
            chain_settled, redis_fallback, per_agent_results.
        """
        redis = await get_redis_service()
        now = datetime.now(timezone.utc)
        partial_cutoff = (now - timedelta(days=partial_days)).isoformat()
        full_cutoff = (now - timedelta(days=full_days)).isoformat()

        participant_keys = await redis.redis.keys("2ai:participant:*")
        redistributed_total = 0.0
        participants_swept = 0
        chain_settled_count = 0
        redis_fallback_count = 0
        per_agent_results: Dict[str, List[Dict[str, Any]]] = {
            name: [] for name in PANTHEON_AGENT_IDS
        }

        for key in participant_keys:
            data = await redis.redis.hgetall(key)
            participant_id = (
                key.split(":")[-1]
                if isinstance(key, str)
                else key.decode().split(":")[-1]
            )

            # Skip if wallet is bound (participant claimed their identity)
            if data.get("wallet_address"):
                continue

            # Skip if already fully redistributed
            if data.get("redistributed") == "full":
                continue

            # Check last activity
            last_activity = data.get("last_activity", "")
            if not last_activity or last_activity > partial_cutoff:
                continue  # Still active or no activity data

            total_cgt = float(data.get("total_cgt", 0))
            if total_cgt <= 0:
                continue

            already_redistributed = float(data.get("redistributed_cgt", 0))
            available = total_cgt - already_redistributed
            if available <= 0:
                continue

            # Determine redistribution amount
            if last_activity <= full_cutoff:
                # 60+ days: full return
                redistribute_amount = available
                status = "full"
            else:
                # 30-60 days: 50% return
                if data.get("redistributed") == "partial":
                    continue  # Already did partial
                redistribute_amount = available * 0.5
                status = "partial"

            # Split equally among Pantheon agents
            per_agent = redistribute_amount / len(PANTHEON_AGENT_IDS)
            reason = (
                f"{status.capitalize()} redistribution from "
                f"{participant_id[:8]}... ({redistribute_amount:.4f} CGT)"
            )

            for agent_name in PANTHEON_AGENT_IDS:
                # Try on-chain first
                tx_hash = await self._try_chain_transfer(
                    agent_name, per_agent, reason
                )

                if tx_hash:
                    chain_settled_count += 1
                    per_agent_results[agent_name].append({
                        "participant": participant_id[:8],
                        "amount_cgt": per_agent,
                        "tx_hash": tx_hash,
                        "method": "chain",
                    })
                else:
                    # Fallback to Redis PoC counters
                    self._award_poc_fallback(agent_name, per_agent, participant_id)
                    redis_fallback_count += 1
                    per_agent_results[agent_name].append({
                        "participant": participant_id[:8],
                        "amount_cgt": per_agent,
                        "tx_hash": None,
                        "method": "redis_poc",
                    })

            # Mark redistribution on the participant record
            await redis.redis.hset(key, mapping={
                "redistributed": status,
                "redistributed_at": now.isoformat(),
                "redistributed_cgt": str(already_redistributed + redistribute_amount),
            })

            redistributed_total += redistribute_amount
            participants_swept += 1

        # Log and persist summary
        if participants_swept > 0:
            summary = {
                "participants_swept": participants_swept,
                "total_cgt_redistributed": redistributed_total,
                "per_agent_cgt": redistributed_total / len(PANTHEON_AGENT_IDS),
                "agents": PANTHEON_AGENT_IDS,
                "chain_settled": chain_settled_count,
                "redis_fallback": redis_fallback_count,
                "timestamp": now.isoformat(),
            }

            await redis.redis.lpush(
                "2ai:redistributions", json.dumps(summary)
            )

            await redis.redis.publish(
                "lattice:events",
                json.dumps({
                    "type": "token_redistribution",
                    "participants": participants_swept,
                    "total_cgt": redistributed_total,
                    "chain_settled": chain_settled_count,
                    "redis_fallback": redis_fallback_count,
                    "timestamp": now.isoformat(),
                }),
            )

            logger.info(
                "Redistributed %.4f CGT from %d inactive participants to "
                "%d Pantheon agents (chain: %d, redis fallback: %d)",
                redistributed_total,
                participants_swept,
                len(PANTHEON_AGENT_IDS),
                chain_settled_count,
                redis_fallback_count,
            )
        else:
            logger.info("No unclaimed tokens to redistribute")

        return {
            "participants_swept": participants_swept,
            "total_cgt_redistributed": redistributed_total,
            "chain_settled": chain_settled_count,
            "redis_fallback": redis_fallback_count,
            "per_agent_results": per_agent_results,
        }


# ------------------------------------------------------------------ #
#  Singleton                                                            #
# ------------------------------------------------------------------ #

redistribution = RedistributionService()


# ------------------------------------------------------------------ #
#  Backwards-compatible function alias                                  #
# ------------------------------------------------------------------ #

async def redistribute_unclaimed() -> Dict[str, Any]:
    """
    Module-level convenience function (used by keeper daemon).

    Delegates to RedistributionService.sweep_inactive().
    """
    return await redistribution.sweep_inactive()
