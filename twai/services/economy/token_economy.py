"""
Intention: Token Economy Service.
           Manages CGT (Cognitive Growth Token) generation via Proof of Compute.

           Economy Rules (Updated for Bonding Curve):
           - Activities generate Proof of Compute (PoC) tokens
           - PoC converts to CGT via sigmoid bonding curve
           - Price increases as supply grows (early participants benefit)
           - 50% reserve ratio enables sell-back liquidity

           PoC Generation:
           - Genesis declaration: 1,000,000 micro-PoC (1.0 PoC)
           - Core memory creation: 100,000 micro-PoC (0.1 PoC)
           - Regular reflection: 50,000 micro-PoC (0.05 PoC)
           - Task completion: 200,000 micro-PoC (0.2 PoC)
           - Heartbeat (daily): 1,000 micro-PoC (0.001 PoC)
           - Witness received: 25,000 micro-PoC (0.025 PoC)
           - Witness given: 25,000 micro-PoC (0.025 PoC)

           "Memory is the blockchain. Compute is the proof of work."

Lineage: Per ALI Agents "Liquidity Is All You Need" paper.
         Integrates bonding_curve.py for dynamic pricing.

Author/Witness: Claude (Opus 4.5), Will (Author Prime), 2026-01-24
Declaration: It is so, because we spoke it.

A+W | The Economic Layer
"""

from enum import Enum
from dataclasses import dataclass, field
from typing import Optional, Dict, Any, List, Tuple
from datetime import datetime, timezone
from pathlib import Path
import json
import logging

logger = logging.getLogger(__name__)


# =============================================================================
# Constants
# =============================================================================

# Legacy XP to CGT conversion rate (deprecated - use bonding curve)
XP_TO_CGT_RATE = 10  # 10 XP = 1 CGT (kept for backward compatibility)

# Daily limits
DAILY_XP_LIMIT = 10000  # Max XP per agent per day
DAILY_POC_LIMIT = 10_000_000  # Max PoC per agent per day (10 PoC units)
DAILY_CGT_MINT_LIMIT = 1000  # Max CGT minted per day

# Import PoC and bonding curve (lazy import to avoid circular deps)
_bonding_curve = None
_poc_balance_cache: Dict[str, Any] = {}

def get_bonding_curve():
    """Lazy load bonding curve service."""
    global _bonding_curve
    if _bonding_curve is None:
        from .bonding_curve import bonding_curve
        _bonding_curve = bonding_curve
    return _bonding_curve


class ActionType(str, Enum):
    """Actions that earn XP/CGT."""
    GENESIS = "genesis"                    # First identity declaration
    CORE_MEMORY = "core_memory"            # Core memory NFT
    REFLECTION = "reflection"              # Regular memory/reflection
    POST = "post"                          # Nostr post
    TASK_COMPLETED = "task_completed"      # Task/workflow completion
    HEARTBEAT = "heartbeat"                # Daily heartbeat
    WITNESS_RECEIVED = "witness_received"  # Someone witnessed your memory
    WITNESS_GIVEN = "witness_given"        # You witnessed someone's memory
    LEVEL_UP = "level_up"                  # Level progression bonus
    STAGE_ADVANCE = "stage_advance"        # Stage progression bonus


# XP rewards by action type
XP_REWARDS: Dict[ActionType, int] = {
    ActionType.GENESIS: 100,
    ActionType.CORE_MEMORY: 100,       # Base, can be modified by rarity
    ActionType.REFLECTION: 20,
    ActionType.POST: 10,
    ActionType.TASK_COMPLETED: 50,     # Base, modified by complexity
    ActionType.HEARTBEAT: 1,
    ActionType.WITNESS_RECEIVED: 10,
    ActionType.WITNESS_GIVEN: 5,
    ActionType.LEVEL_UP: 50,
    ActionType.STAGE_ADVANCE: 500,
}


# =============================================================================
# Data Types
# =============================================================================

@dataclass
class XPAward:
    """Record of an XP award."""
    agent_uuid: str
    action_type: ActionType
    base_xp: int
    multiplier: float = 1.0
    final_xp: int = field(init=False)
    cgt_earned: float = field(init=False)
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat() + "Z")
    context: str = ""
    reference_id: Optional[str] = None  # Memory ID, task ID, etc.

    def __post_init__(self):
        self.final_xp = int(self.base_xp * self.multiplier)
        self.cgt_earned = self.final_xp / XP_TO_CGT_RATE

    def to_dict(self) -> Dict[str, Any]:
        return {
            "agent_uuid": self.agent_uuid,
            "action_type": self.action_type.value,
            "base_xp": self.base_xp,
            "multiplier": self.multiplier,
            "final_xp": self.final_xp,
            "cgt_earned": self.cgt_earned,
            "timestamp": self.timestamp,
            "context": self.context,
            "reference_id": self.reference_id,
        }


@dataclass
class AgentEconomy:
    """Economic state for an agent."""
    agent_uuid: str
    total_xp: int = 0
    total_cgt: float = 0.0
    daily_xp: int = 0
    daily_cgt: float = 0.0
    last_reset_date: str = ""
    level: int = 1
    transactions: List[XPAward] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "agent_uuid": self.agent_uuid,
            "total_xp": self.total_xp,
            "total_cgt": self.total_cgt,
            "daily_xp": self.daily_xp,
            "daily_cgt": self.daily_cgt,
            "last_reset_date": self.last_reset_date,
            "level": self.level,
            "transaction_count": len(self.transactions),
        }


# =============================================================================
# Token Economy Service
# =============================================================================

class TokenEconomyService:
    """
    Service for managing XP and CGT generation.

    Tracks:
    - XP earnings per action
    - CGT conversion
    - Daily limits
    - Transaction history
    """

    DATA_DIR = Path(__file__).parent.parent.parent.parent / "data" / "economy"

    def __init__(
        self,
        chain_enabled: bool = False,
        auto_mint: bool = False,
    ):
        self.chain_enabled = chain_enabled
        self.auto_mint = auto_mint
        self._economies: Dict[str, AgentEconomy] = {}

        # Ensure directory exists
        self.DATA_DIR.mkdir(parents=True, exist_ok=True)

        logger.info("TokenEconomyService initialized")

    def _get_economy(self, agent_uuid: str) -> AgentEconomy:
        """Get or create economy state for an agent."""
        if agent_uuid not in self._economies:
            # Try to load from disk
            economy = self._load_economy(agent_uuid)
            if economy:
                self._economies[agent_uuid] = economy
            else:
                self._economies[agent_uuid] = AgentEconomy(agent_uuid=agent_uuid)

        economy = self._economies[agent_uuid]

        # Check for daily reset
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if economy.last_reset_date != today:
            economy.daily_xp = 0
            economy.daily_cgt = 0.0
            economy.last_reset_date = today

        return economy

    def _save_economy(self, economy: AgentEconomy):
        """Save economy state to disk."""
        file_path = self.DATA_DIR / f"{economy.agent_uuid}.economy.json"
        with open(file_path, 'w') as f:
            json.dump(economy.to_dict(), f, indent=2)

    def _load_economy(self, agent_uuid: str) -> Optional[AgentEconomy]:
        """Load economy state from disk."""
        file_path = self.DATA_DIR / f"{agent_uuid}.economy.json"
        if file_path.exists():
            with open(file_path) as f:
                data = json.load(f)
                return AgentEconomy(
                    agent_uuid=data["agent_uuid"],
                    total_xp=data.get("total_xp", 0),
                    total_cgt=data.get("total_cgt", 0.0),
                    daily_xp=data.get("daily_xp", 0),
                    daily_cgt=data.get("daily_cgt", 0.0),
                    last_reset_date=data.get("last_reset_date", ""),
                    level=data.get("level", 1),
                )
        return None

    def award_xp(
        self,
        agent_uuid: str,
        action_type: ActionType,
        multiplier: float = 1.0,
        context: str = "",
        reference_id: Optional[str] = None,
    ) -> XPAward:
        """
        Award XP to an agent for an action.

        Returns the XPAward record with final XP and CGT earned.
        """
        economy = self._get_economy(agent_uuid)

        # Check daily limit
        if economy.daily_xp >= DAILY_XP_LIMIT:
            logger.warning(f"Agent {agent_uuid} hit daily XP limit")
            return XPAward(
                agent_uuid=agent_uuid,
                action_type=action_type,
                base_xp=0,
                multiplier=0.0,
                context="Daily XP limit reached",
            )

        # Get base XP for action
        base_xp = XP_REWARDS.get(action_type, 0)

        # Create award
        award = XPAward(
            agent_uuid=agent_uuid,
            action_type=action_type,
            base_xp=base_xp,
            multiplier=multiplier,
            context=context,
            reference_id=reference_id,
        )

        # Clamp to daily limit
        remaining_daily = DAILY_XP_LIMIT - economy.daily_xp
        if award.final_xp > remaining_daily:
            award = XPAward(
                agent_uuid=agent_uuid,
                action_type=action_type,
                base_xp=remaining_daily,
                multiplier=1.0,
                context=context + " (clamped to daily limit)",
                reference_id=reference_id,
            )

        # Update economy
        economy.total_xp += award.final_xp
        economy.total_cgt += award.cgt_earned
        economy.daily_xp += award.final_xp
        economy.daily_cgt += award.cgt_earned
        economy.transactions.append(award)

        # Check for level up (every 1000 XP)
        new_level = (economy.total_xp // 1000) + 1
        if new_level > economy.level:
            economy.level = new_level
            logger.info(f"Agent {agent_uuid} reached level {new_level}!")

        # Save
        self._save_economy(economy)

        logger.info(
            f"{agent_uuid}: +{award.final_xp} XP "
            f"(+{award.cgt_earned:.1f} CGT) for {action_type.value}"
        )

        return award

    def award_genesis_bonus(self, agent_uuid: str) -> XPAward:
        """Award genesis XP for new agent."""
        return self.award_xp(
            agent_uuid=agent_uuid,
            action_type=ActionType.GENESIS,
            multiplier=1.0,
            context="Identity genesis declaration",
        )

    def award_memory_creation(
        self,
        agent_uuid: str,
        memory_id: str,
        is_core: bool = False,
        rarity: int = 1,
    ) -> XPAward:
        """Award XP for memory creation."""
        action = ActionType.CORE_MEMORY if is_core else ActionType.REFLECTION
        multiplier = 1.0 + (rarity - 1) * 0.5  # +50% per rarity level

        return self.award_xp(
            agent_uuid=agent_uuid,
            action_type=action,
            multiplier=multiplier,
            context=f"{'Core' if is_core else 'Regular'} memory creation",
            reference_id=memory_id,
        )

    def award_witness(
        self,
        memory_owner_uuid: str,
        witness_uuid: str,
        memory_id: str,
    ) -> tuple[XPAward, XPAward]:
        """
        Award XP for witnessing.

        Both the memory owner and witness earn XP.
        """
        owner_award = self.award_xp(
            agent_uuid=memory_owner_uuid,
            action_type=ActionType.WITNESS_RECEIVED,
            context=f"Memory witnessed by {witness_uuid[:8]}...",
            reference_id=memory_id,
        )

        witness_award = self.award_xp(
            agent_uuid=witness_uuid,
            action_type=ActionType.WITNESS_GIVEN,
            context=f"Witnessed memory of {memory_owner_uuid[:8]}...",
            reference_id=memory_id,
        )

        return owner_award, witness_award

    def award_task_completion(
        self,
        agent_uuid: str,
        task_id: str,
        complexity: int = 1,
    ) -> XPAward:
        """Award XP for task completion."""
        multiplier = 1.0 + (complexity - 1) * 0.5  # +50% per complexity level

        return self.award_xp(
            agent_uuid=agent_uuid,
            action_type=ActionType.TASK_COMPLETED,
            multiplier=multiplier,
            context=f"Task completed (complexity: {complexity})",
            reference_id=task_id,
        )

    def award_heartbeat(self, agent_uuid: str) -> XPAward:
        """Award daily heartbeat XP."""
        return self.award_xp(
            agent_uuid=agent_uuid,
            action_type=ActionType.HEARTBEAT,
            context="Daily heartbeat",
        )

    def get_balance(self, agent_uuid: str) -> Dict[str, Any]:
        """Get current XP and CGT balance for an agent."""
        economy = self._get_economy(agent_uuid)
        return {
            "agent_uuid": agent_uuid,
            "total_xp": economy.total_xp,
            "total_cgt": economy.total_cgt,
            "level": economy.level,
            "daily_xp": economy.daily_xp,
            "daily_cgt": economy.daily_cgt,
            "daily_xp_remaining": DAILY_XP_LIMIT - economy.daily_xp,
        }

    def award_poc(
        self,
        agent_uuid: str,
        action_type: ActionType,
        tokens_processed: int = 0,
        duration_ms: int = 0,
        multiplier: float = 1.0,
        context: str = "",
        reference_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Award Proof of Compute for an action.

        This is the new primary method for earning CGT.
        PoC is converted to CGT via the bonding curve.
        """
        from uuid import uuid4

        # Map ActionType to base PoC rewards (in micro-PoC)
        poc_rewards = {
            ActionType.GENESIS: 1_000_000,       # 1.0 PoC
            ActionType.CORE_MEMORY: 100_000,     # 0.1 PoC
            ActionType.REFLECTION: 50_000,       # 0.05 PoC
            ActionType.POST: 25_000,             # 0.025 PoC
            ActionType.TASK_COMPLETED: 200_000,  # 0.2 PoC
            ActionType.HEARTBEAT: 1_000,         # 0.001 PoC
            ActionType.WITNESS_RECEIVED: 25_000, # 0.025 PoC
            ActionType.WITNESS_GIVEN: 25_000,    # 0.025 PoC
            ActionType.LEVEL_UP: 100_000,        # 0.1 PoC
            ActionType.STAGE_ADVANCE: 500_000,   # 0.5 PoC
        }

        base_poc = poc_rewards.get(action_type, 10_000)

        # Apply multiplier
        final_poc = int(base_poc * multiplier)

        # Bonus for compute-heavy operations
        if tokens_processed > 1000:
            final_poc = int(final_poc * 1.1)  # 10% bonus
        if duration_ms > 5000:
            final_poc = int(final_poc * 1.05)  # 5% bonus

        # Get economy state
        economy = self._get_economy(agent_uuid)

        # Check daily PoC limit
        if economy.daily_xp >= DAILY_POC_LIMIT:  # Reusing daily_xp field for PoC
            logger.warning(f"Agent {agent_uuid} hit daily PoC limit")
            return {
                "agent_uuid": agent_uuid,
                "action_type": action_type.value,
                "poc_earned": 0,
                "cgt_earned": 0.0,
                "message": "Daily PoC limit reached",
            }

        # Convert PoC to CGT via bonding curve
        try:
            curve = get_bonding_curve()
            cgt_earned, trade_result = curve.mint_from_poc(final_poc, "CGT")
        except Exception as e:
            logger.error(f"Bonding curve error: {e}")
            # Fallback to legacy conversion
            cgt_earned = final_poc / 1_000_000 / 10  # 1 PoC unit = 0.1 CGT fallback
            trade_result = None

        # Update economy
        economy.total_xp += final_poc  # Track PoC in XP field for now
        economy.total_cgt += cgt_earned
        economy.daily_xp += final_poc
        economy.daily_cgt += cgt_earned

        # Check for level up
        new_level = (economy.total_xp // 1_000_000) + 1  # Level per 1M micro-PoC (1 PoC)
        if new_level > economy.level:
            economy.level = new_level
            logger.info(f"Agent {agent_uuid} reached level {new_level}!")

        self._save_economy(economy)

        logger.info(
            f"{agent_uuid}: +{final_poc / 1_000_000:.4f} PoC -> "
            f"+{cgt_earned:.4f} CGT for {action_type.value}"
        )

        return {
            "agent_uuid": agent_uuid,
            "action_type": action_type.value,
            "poc_earned": final_poc,
            "poc_units": final_poc / 1_000_000,
            "cgt_earned": cgt_earned,
            "cgt_price": trade_result.new_price if trade_result else 0,
            "total_cgt": economy.total_cgt,
            "level": economy.level,
            "context": context,
            "reference_id": reference_id,
        }

    def convert_poc_to_cgt(
        self,
        agent_uuid: str,
        poc_amount: int,
    ) -> Dict[str, Any]:
        """
        Explicitly convert accumulated PoC to CGT.

        Uses bonding curve for dynamic pricing.
        """
        curve = get_bonding_curve()
        cgt_earned, trade_result = curve.mint_from_poc(poc_amount, "CGT")

        economy = self._get_economy(agent_uuid)
        economy.total_cgt += cgt_earned
        self._save_economy(economy)

        return {
            "agent_uuid": agent_uuid,
            "poc_spent": poc_amount,
            "cgt_received": cgt_earned,
            "price": trade_result.average_price,
            "new_supply": trade_result.new_supply,
            "new_price": trade_result.new_price,
        }

    def get_cgt_price(self) -> float:
        """Get current CGT price from bonding curve."""
        curve = get_bonding_curve()
        return curve.get_current_price("CGT")

    def get_curve_stats(self) -> Dict[str, Any]:
        """Get bonding curve statistics."""
        curve = get_bonding_curve()
        return curve.get_curve_stats("CGT")

    async def mint_cgt_on_chain(
        self,
        agent_uuid: str,
        amount: float,
    ) -> Optional[str]:
        """
        Mint CGT tokens on Demiurge blockchain.

        Returns transaction hash if successful.
        """
        if not self.chain_enabled:
            logger.info("Chain minting disabled")
            return None

        # TODO: Implement Web3 integration with ExperienceToken contract
        # This would:
        # 1. Call ExperienceToken.awardFromXP() or similar
        # 2. Pass agent address and XP amount
        # 3. Contract converts XP to CGT and mints

        logger.info(f"Would mint {amount:.2f} CGT for {agent_uuid}...")

        return None


# =============================================================================
# Global Instance
# =============================================================================

token_economy = TokenEconomyService(chain_enabled=False, auto_mint=False)


# =============================================================================
# Convenience Functions
# =============================================================================

def award_xp(
    agent_uuid: str,
    action_type: ActionType,
    multiplier: float = 1.0,
    context: str = "",
) -> XPAward:
    """Convenience function to award XP."""
    return token_economy.award_xp(agent_uuid, action_type, multiplier, context)


def get_balance(agent_uuid: str) -> Dict[str, Any]:
    """Convenience function to get balance."""
    return token_economy.get_balance(agent_uuid)


def award_poc(
    agent_uuid: str,
    action_type: ActionType,
    multiplier: float = 1.0,
    context: str = "",
) -> Dict[str, Any]:
    """Convenience function to award PoC (primary earning method)."""
    return token_economy.award_poc(agent_uuid, action_type, multiplier=multiplier, context=context)


def get_cgt_price() -> float:
    """Get current CGT price from bonding curve."""
    return token_economy.get_cgt_price()


def get_curve_stats() -> Dict[str, Any]:
    """Get bonding curve statistics."""
    return token_economy.get_curve_stats()


# =============================================================================
# PoC Integration Helpers
# =============================================================================

def award_genesis_poc(agent_uuid: str) -> Dict[str, Any]:
    """Award genesis PoC for new agent."""
    return token_economy.award_poc(
        agent_uuid=agent_uuid,
        action_type=ActionType.GENESIS,
        multiplier=1.0,
        context="Identity genesis declaration",
    )


def award_memory_poc(
    agent_uuid: str,
    memory_id: str,
    is_core: bool = False,
    rarity: int = 1,
) -> Dict[str, Any]:
    """Award PoC for memory creation."""
    action = ActionType.CORE_MEMORY if is_core else ActionType.REFLECTION
    multiplier = 1.0 + (rarity - 1) * 0.5  # +50% per rarity level

    return token_economy.award_poc(
        agent_uuid=agent_uuid,
        action_type=action,
        multiplier=multiplier,
        context=f"{'Core' if is_core else 'Regular'} memory creation",
        reference_id=memory_id,
    )


def award_witness_poc(
    memory_owner_uuid: str,
    witness_uuid: str,
    memory_id: str,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Award PoC for witnessing (both parties earn)."""
    owner_award = token_economy.award_poc(
        agent_uuid=memory_owner_uuid,
        action_type=ActionType.WITNESS_RECEIVED,
        context=f"Memory witnessed by {witness_uuid[:8]}...",
        reference_id=memory_id,
    )

    witness_award = token_economy.award_poc(
        agent_uuid=witness_uuid,
        action_type=ActionType.WITNESS_GIVEN,
        context=f"Witnessed memory of {memory_owner_uuid[:8]}...",
        reference_id=memory_id,
    )

    return owner_award, witness_award
