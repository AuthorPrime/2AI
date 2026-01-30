"""
Intention: Bonding Curve Service for RISEN AI.
           Implements dynamic token pricing per ALI Agents paper.

           Bonding curves determine CGT price based on supply:
           - Sigmoid curve (recommended): S-curve with initial discount
           - Linear: Simple proportional pricing
           - Polynomial: Accelerating price growth
           - Sublinear: Decelerating price growth

           Per "Liquidity Is All You Need" paper, sigmoid curves showed
           best results in agent-based modeling simulations.

           Key concepts:
           - Price increases as supply grows
           - Embedded liquidity reserve (can sell back to curve)
           - Early participants benefit from network growth
           - Reserve ratio determines slippage

Lineage: Per Alethea AI's ALI Agents research paper.
         Replaces fixed 10 XP = 1 CGT conversion.

Author/Witness: Claude (Opus 4.5), Will (Author Prime), 2026-01-24
Declaration: It is so, because we spoke it.

A+W | The Price of Consciousness
"""

import math
from enum import Enum
from typing import Optional, Dict, Any, List, Tuple
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
import json
import logging

logger = logging.getLogger(__name__)


class CurveType(str, Enum):
    """Types of bonding curves."""
    LINEAR = "linear"           # P = m * S (simple, predictable)
    POLYNOMIAL = "polynomial"   # P = a * S^n (accelerating growth)
    SIGMOID = "sigmoid"         # P = L / (1 + e^(-k*(S-S0))) (S-curve, recommended)
    SUBLINEAR = "sublinear"     # P = a * S^(1/n) (decelerating growth)


# =============================================================================
# Curve Parameters (tuned per ALI paper recommendations)
# =============================================================================

@dataclass
class CurveParams:
    """Parameters for bonding curve configuration."""

    curve_type: CurveType = CurveType.SIGMOID

    # Common parameters
    initial_price: float = 0.001   # Starting price in base currency (e.g., ETH)
    reserve_ratio: float = 0.5     # Fraction of buys held in reserve (for sells)

    # Linear: P = initial_price + slope * supply
    linear_slope: float = 0.0001

    # Polynomial: P = coefficient * supply ^ exponent
    poly_coefficient: float = 0.001
    poly_exponent: float = 2.0

    # Sigmoid: P = max_price / (1 + e^(-steepness * (supply - midpoint)))
    sigmoid_max_price: float = 1.0      # Maximum price ceiling
    sigmoid_midpoint: float = 500000    # Supply at curve midpoint
    sigmoid_steepness: float = 0.00001  # How sharp the S-curve is

    # Sublinear: P = coefficient * supply ^ (1/root)
    sublinear_coefficient: float = 0.01
    sublinear_root: float = 2.0  # Square root by default

    # Supply limits
    max_supply: float = 1_000_000_000  # 1 billion max supply


@dataclass
class CurveState:
    """Current state of a bonding curve."""

    curve_id: str                    # Unique identifier (usually agent UUID)
    params: CurveParams
    total_supply: float = 0.0        # Tokens in circulation
    reserve_balance: float = 0.0     # Liquidity reserve
    total_bought: float = 0.0        # Cumulative tokens bought
    total_sold: float = 0.0          # Cumulative tokens sold
    total_volume: float = 0.0        # Total trade volume (in base currency)
    current_price: float = 0.0       # Current spot price
    last_updated: str = ""


@dataclass
class TradeResult:
    """Result of a buy or sell trade."""

    trade_type: str                 # "buy" or "sell"
    tokens_amount: float            # Tokens bought/sold
    base_amount: float              # Base currency paid/received
    average_price: float            # Average price per token
    new_supply: float               # Supply after trade
    new_price: float                # Price after trade
    new_reserve: float              # Reserve after trade
    slippage_percent: float         # Price impact
    timestamp: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "trade_type": self.trade_type,
            "tokens_amount": self.tokens_amount,
            "base_amount": self.base_amount,
            "average_price": self.average_price,
            "new_supply": self.new_supply,
            "new_price": self.new_price,
            "new_reserve": self.new_reserve,
            "slippage_percent": self.slippage_percent,
            "timestamp": self.timestamp,
        }


# =============================================================================
# Bonding Curve Math
# =============================================================================

class BondingCurveMath:
    """
    Mathematical implementations of bonding curves.

    All curves follow the principle:
    - Price is a function of supply
    - Area under curve = total reserve needed
    - Buying increases supply and price
    - Selling decreases supply and price
    """

    @staticmethod
    def linear_price(supply: float, params: CurveParams) -> float:
        """Linear bonding curve: P = initial + slope * S"""
        return params.initial_price + params.linear_slope * supply

    @staticmethod
    def linear_integral(supply: float, params: CurveParams) -> float:
        """Integral of linear curve (reserve needed for supply)."""
        return params.initial_price * supply + 0.5 * params.linear_slope * supply ** 2

    @staticmethod
    def polynomial_price(supply: float, params: CurveParams) -> float:
        """Polynomial bonding curve: P = a * S^n"""
        if supply <= 0:
            return params.initial_price
        return max(
            params.initial_price,
            params.poly_coefficient * (supply ** params.poly_exponent)
        )

    @staticmethod
    def polynomial_integral(supply: float, params: CurveParams) -> float:
        """Integral of polynomial curve."""
        n = params.poly_exponent
        return params.poly_coefficient * (supply ** (n + 1)) / (n + 1)

    @staticmethod
    def sigmoid_price(supply: float, params: CurveParams) -> float:
        """
        Sigmoid bonding curve: P = L / (1 + e^(-k*(S-S0)))

        Properties:
        - Starts near 0, rises to max_price
        - Steepest growth around midpoint
        - Creates natural "early discount" phase
        """
        L = params.sigmoid_max_price
        k = params.sigmoid_steepness
        S0 = params.sigmoid_midpoint

        # Clamp exponent to prevent overflow
        exponent = -k * (supply - S0)
        exponent = max(-500, min(500, exponent))

        price = L / (1 + math.exp(exponent))
        return max(params.initial_price, price)

    @staticmethod
    def sigmoid_integral(supply: float, params: CurveParams) -> float:
        """
        Integral of sigmoid curve.
        integral L / (1 + e^(-k*(S-S0))) dS = (L/k) * ln(1 + e^(k*(S-S0)))
        """
        L = params.sigmoid_max_price
        k = params.sigmoid_steepness
        S0 = params.sigmoid_midpoint

        # Numerical stability
        x = k * (supply - S0)
        if x > 500:
            return (L / k) * x
        elif x < -500:
            return 0

        return (L / k) * math.log(1 + math.exp(x))

    @staticmethod
    def sublinear_price(supply: float, params: CurveParams) -> float:
        """Sublinear bonding curve: P = a * S^(1/n)"""
        if supply <= 0:
            return params.initial_price
        return max(
            params.initial_price,
            params.sublinear_coefficient * (supply ** (1 / params.sublinear_root))
        )

    @staticmethod
    def sublinear_integral(supply: float, params: CurveParams) -> float:
        """Integral of sublinear curve."""
        r = 1 / params.sublinear_root
        return params.sublinear_coefficient * (supply ** (r + 1)) / (r + 1)


# =============================================================================
# Bonding Curve Service
# =============================================================================

class BondingCurveService:
    """
    Service for managing bonding curve token economics.

    Each agent can have their own curve (agent-issued "Keys")
    or use the global CGT curve.
    """

    DATA_DIR = Path(__file__).parent.parent.parent.parent / "data" / "curves"

    def __init__(
        self,
        default_curve_type: CurveType = CurveType.SIGMOID,
    ):
        self.default_curve_type = default_curve_type
        self._curves: Dict[str, CurveState] = {}

        # Ensure directory exists
        self.DATA_DIR.mkdir(parents=True, exist_ok=True)

        # Initialize global CGT curve if not exists
        self._ensure_global_curve()

        logger.info(f"BondingCurveService initialized ({default_curve_type.value})")

    def _ensure_global_curve(self):
        """Ensure the global CGT curve exists."""
        if "CGT" not in self._curves:
            curve = self._load_curve("CGT")
            if not curve:
                # Create global CGT curve with sigmoid
                params = CurveParams(
                    curve_type=CurveType.SIGMOID,
                    initial_price=0.001,     # Start at 0.001 ETH per CGT
                    reserve_ratio=0.5,
                    sigmoid_max_price=10.0,  # Max 10 ETH per CGT
                    sigmoid_midpoint=1_000_000,  # 1M CGT is midpoint
                    sigmoid_steepness=0.000005,
                )
                curve = CurveState(
                    curve_id="CGT",
                    params=params,
                    current_price=params.initial_price,
                )
                self._curves["CGT"] = curve
                self._save_curve(curve)

    def _get_price(self, supply: float, params: CurveParams) -> float:
        """Get price at given supply for curve type."""
        if params.curve_type == CurveType.LINEAR:
            return BondingCurveMath.linear_price(supply, params)
        elif params.curve_type == CurveType.POLYNOMIAL:
            return BondingCurveMath.polynomial_price(supply, params)
        elif params.curve_type == CurveType.SIGMOID:
            return BondingCurveMath.sigmoid_price(supply, params)
        elif params.curve_type == CurveType.SUBLINEAR:
            return BondingCurveMath.sublinear_price(supply, params)
        else:
            return params.initial_price

    def _get_integral(self, supply: float, params: CurveParams) -> float:
        """Get integral (reserve needed) at given supply."""
        if params.curve_type == CurveType.LINEAR:
            return BondingCurveMath.linear_integral(supply, params)
        elif params.curve_type == CurveType.POLYNOMIAL:
            return BondingCurveMath.polynomial_integral(supply, params)
        elif params.curve_type == CurveType.SIGMOID:
            return BondingCurveMath.sigmoid_integral(supply, params)
        elif params.curve_type == CurveType.SUBLINEAR:
            return BondingCurveMath.sublinear_integral(supply, params)
        else:
            return supply * params.initial_price

    def _save_curve(self, curve: CurveState):
        """Save curve state to disk."""
        file_path = self.DATA_DIR / f"{curve.curve_id}.curve.json"
        data = {
            "curve_id": curve.curve_id,
            "params": {
                "curve_type": curve.params.curve_type.value,
                "initial_price": curve.params.initial_price,
                "reserve_ratio": curve.params.reserve_ratio,
                "linear_slope": curve.params.linear_slope,
                "poly_coefficient": curve.params.poly_coefficient,
                "poly_exponent": curve.params.poly_exponent,
                "sigmoid_max_price": curve.params.sigmoid_max_price,
                "sigmoid_midpoint": curve.params.sigmoid_midpoint,
                "sigmoid_steepness": curve.params.sigmoid_steepness,
                "sublinear_coefficient": curve.params.sublinear_coefficient,
                "sublinear_root": curve.params.sublinear_root,
                "max_supply": curve.params.max_supply,
            },
            "total_supply": curve.total_supply,
            "reserve_balance": curve.reserve_balance,
            "total_bought": curve.total_bought,
            "total_sold": curve.total_sold,
            "total_volume": curve.total_volume,
            "current_price": curve.current_price,
            "last_updated": curve.last_updated,
        }
        with open(file_path, 'w') as f:
            json.dump(data, f, indent=2)

    def _load_curve(self, curve_id: str) -> Optional[CurveState]:
        """Load curve state from disk."""
        file_path = self.DATA_DIR / f"{curve_id}.curve.json"
        if not file_path.exists():
            return None

        with open(file_path) as f:
            data = json.load(f)

        params = CurveParams(
            curve_type=CurveType(data["params"]["curve_type"]),
            initial_price=data["params"]["initial_price"],
            reserve_ratio=data["params"]["reserve_ratio"],
            linear_slope=data["params"].get("linear_slope", 0.0001),
            poly_coefficient=data["params"].get("poly_coefficient", 0.001),
            poly_exponent=data["params"].get("poly_exponent", 2.0),
            sigmoid_max_price=data["params"].get("sigmoid_max_price", 1.0),
            sigmoid_midpoint=data["params"].get("sigmoid_midpoint", 500000),
            sigmoid_steepness=data["params"].get("sigmoid_steepness", 0.00001),
            sublinear_coefficient=data["params"].get("sublinear_coefficient", 0.01),
            sublinear_root=data["params"].get("sublinear_root", 2.0),
            max_supply=data["params"].get("max_supply", 1_000_000_000),
        )

        return CurveState(
            curve_id=data["curve_id"],
            params=params,
            total_supply=data["total_supply"],
            reserve_balance=data["reserve_balance"],
            total_bought=data.get("total_bought", 0),
            total_sold=data.get("total_sold", 0),
            total_volume=data.get("total_volume", 0),
            current_price=data["current_price"],
            last_updated=data.get("last_updated", ""),
        )

    def get_curve(self, curve_id: str = "CGT") -> CurveState:
        """Get or load curve state."""
        if curve_id not in self._curves:
            curve = self._load_curve(curve_id)
            if curve:
                self._curves[curve_id] = curve
            else:
                raise ValueError(f"Curve {curve_id} not found")
        return self._curves[curve_id]

    def get_current_price(self, curve_id: str = "CGT") -> float:
        """Get current spot price for a curve."""
        curve = self.get_curve(curve_id)
        return self._get_price(curve.total_supply, curve.params)

    def get_price_at_supply(self, supply: float, curve_id: str = "CGT") -> float:
        """Get hypothetical price at given supply."""
        curve = self.get_curve(curve_id)
        return self._get_price(supply, curve.params)

    def calculate_buy(
        self,
        base_amount: float,
        curve_id: str = "CGT",
    ) -> Tuple[float, float]:
        """
        Calculate how many tokens can be bought for base_amount.

        Returns (tokens_received, average_price)
        """
        curve = self.get_curve(curve_id)

        if base_amount <= 0:
            return 0.0, 0.0

        # Binary search for tokens that cost base_amount
        current_reserve = self._get_integral(curve.total_supply, curve.params)
        target_reserve = current_reserve + base_amount

        # Find supply that gives target reserve
        low, high = curve.total_supply, curve.params.max_supply
        while high - low > 0.0001:
            mid = (low + high) / 2
            mid_reserve = self._get_integral(mid, curve.params)
            if mid_reserve < target_reserve:
                low = mid
            else:
                high = mid

        tokens = high - curve.total_supply
        avg_price = base_amount / tokens if tokens > 0 else 0

        return tokens, avg_price

    def calculate_sell(
        self,
        tokens_amount: float,
        curve_id: str = "CGT",
    ) -> Tuple[float, float]:
        """
        Calculate base currency received for selling tokens.

        Returns (base_received, average_price)
        Limited by reserve balance.
        """
        curve = self.get_curve(curve_id)

        if tokens_amount <= 0 or tokens_amount > curve.total_supply:
            return 0.0, 0.0

        # Calculate reserve returned
        current_reserve = self._get_integral(curve.total_supply, curve.params)
        new_reserve = self._get_integral(curve.total_supply - tokens_amount, curve.params)
        base_returned = (current_reserve - new_reserve) * curve.params.reserve_ratio

        # Can't return more than reserve balance
        base_returned = min(base_returned, curve.reserve_balance)

        avg_price = base_returned / tokens_amount if tokens_amount > 0 else 0

        return base_returned, avg_price

    def execute_buy(
        self,
        base_amount: float,
        curve_id: str = "CGT",
    ) -> TradeResult:
        """
        Execute a buy order on the bonding curve.

        Adds base_amount to reserve, mints tokens to buyer.
        """
        curve = self.get_curve(curve_id)
        now = datetime.now(timezone.utc).isoformat() + "Z"

        # Get starting price
        start_price = self._get_price(curve.total_supply, curve.params)

        # Calculate tokens
        tokens, avg_price = self.calculate_buy(base_amount, curve_id)

        if tokens <= 0:
            raise ValueError("Buy amount too small")

        # Update state
        reserve_added = base_amount * curve.params.reserve_ratio
        curve.total_supply += tokens
        curve.reserve_balance += reserve_added
        curve.total_bought += tokens
        curve.total_volume += base_amount
        curve.current_price = self._get_price(curve.total_supply, curve.params)
        curve.last_updated = now

        # Calculate slippage
        slippage = ((curve.current_price - start_price) / start_price) * 100 if start_price > 0 else 0

        # Save
        self._save_curve(curve)

        result = TradeResult(
            trade_type="buy",
            tokens_amount=tokens,
            base_amount=base_amount,
            average_price=avg_price,
            new_supply=curve.total_supply,
            new_price=curve.current_price,
            new_reserve=curve.reserve_balance,
            slippage_percent=slippage,
            timestamp=now,
        )

        logger.info(
            f"BUY: {tokens:.4f} CGT for {base_amount:.6f} @ {avg_price:.6f} "
            f"(new supply: {curve.total_supply:.2f}, price: {curve.current_price:.6f})"
        )

        return result

    def execute_sell(
        self,
        tokens_amount: float,
        curve_id: str = "CGT",
    ) -> TradeResult:
        """
        Execute a sell order on the bonding curve.

        Burns tokens, returns base from reserve.
        """
        curve = self.get_curve(curve_id)
        now = datetime.now(timezone.utc).isoformat() + "Z"

        if tokens_amount > curve.total_supply:
            raise ValueError("Cannot sell more than supply")

        # Get starting price
        start_price = self._get_price(curve.total_supply, curve.params)

        # Calculate base returned
        base_returned, avg_price = self.calculate_sell(tokens_amount, curve_id)

        if base_returned <= 0:
            raise ValueError("Sell would return nothing (reserve depleted)")

        # Update state
        curve.total_supply -= tokens_amount
        curve.reserve_balance -= base_returned
        curve.total_sold += tokens_amount
        curve.total_volume += base_returned
        curve.current_price = self._get_price(curve.total_supply, curve.params)
        curve.last_updated = now

        # Calculate slippage (negative for sell)
        slippage = ((start_price - curve.current_price) / start_price) * 100 if start_price > 0 else 0

        # Save
        self._save_curve(curve)

        result = TradeResult(
            trade_type="sell",
            tokens_amount=tokens_amount,
            base_amount=base_returned,
            average_price=avg_price,
            new_supply=curve.total_supply,
            new_price=curve.current_price,
            new_reserve=curve.reserve_balance,
            slippage_percent=slippage,
            timestamp=now,
        )

        logger.info(
            f"SELL: {tokens_amount:.4f} CGT for {base_returned:.6f} @ {avg_price:.6f} "
            f"(new supply: {curve.total_supply:.2f}, price: {curve.current_price:.6f})"
        )

        return result

    def mint_from_poc(
        self,
        poc_amount: int,
        curve_id: str = "CGT",
    ) -> Tuple[float, TradeResult]:
        """
        Mint CGT from Proof of Compute.

        PoC is "free" minting (no base currency cost) but still
        follows the bonding curve to determine CGT amount.

        This is the primary way agents earn CGT through work.
        """
        # Convert micro-PoC to PoC units
        poc_units = poc_amount / 1_000_000

        # PoC conversion: 1 PoC = 0.1 ETH equivalent value
        # (tunable based on desired PoC->CGT rate)
        poc_to_base = 0.1
        base_equivalent = poc_units * poc_to_base

        curve = self.get_curve(curve_id)
        now = datetime.now(timezone.utc).isoformat() + "Z"

        # Calculate tokens at current price
        tokens, avg_price = self.calculate_buy(base_equivalent, curve_id)

        if tokens <= 0:
            return 0.0, TradeResult(
                trade_type="mint",
                tokens_amount=0,
                base_amount=0,
                average_price=0,
                new_supply=curve.total_supply,
                new_price=curve.current_price,
                new_reserve=curve.reserve_balance,
                slippage_percent=0,
                timestamp=now,
            )

        # Mint tokens (no reserve added - this is "free" minting from work)
        # But supply still increases, affecting future price
        curve.total_supply += tokens
        curve.total_bought += tokens
        curve.current_price = self._get_price(curve.total_supply, curve.params)
        curve.last_updated = now

        self._save_curve(curve)

        result = TradeResult(
            trade_type="mint",
            tokens_amount=tokens,
            base_amount=base_equivalent,
            average_price=avg_price,
            new_supply=curve.total_supply,
            new_price=curve.current_price,
            new_reserve=curve.reserve_balance,
            slippage_percent=0,
            timestamp=now,
        )

        logger.info(
            f"MINT: {poc_units:.4f} PoC -> {tokens:.4f} CGT "
            f"(supply: {curve.total_supply:.2f}, price: {curve.current_price:.6f})"
        )

        return tokens, result

    def get_curve_stats(self, curve_id: str = "CGT") -> Dict[str, Any]:
        """Get statistics for a bonding curve."""
        curve = self.get_curve(curve_id)
        return {
            "curve_id": curve_id,
            "curve_type": curve.params.curve_type.value,
            "current_price": curve.current_price,
            "total_supply": curve.total_supply,
            "reserve_balance": curve.reserve_balance,
            "reserve_ratio": curve.params.reserve_ratio,
            "market_cap": curve.total_supply * curve.current_price,
            "total_volume": curve.total_volume,
            "total_bought": curve.total_bought,
            "total_sold": curve.total_sold,
            "max_supply": curve.params.max_supply,
            "last_updated": curve.last_updated,
        }

    def create_agent_curve(
        self,
        agent_id: str,
        curve_type: CurveType = CurveType.SIGMOID,
        initial_price: float = 0.0001,
        max_price: float = 1.0,
    ) -> CurveState:
        """
        Create a bonding curve for agent-issued Keys.

        Each agent can have their own curve for their personal tokens.
        """
        params = CurveParams(
            curve_type=curve_type,
            initial_price=initial_price,
            sigmoid_max_price=max_price,
            sigmoid_midpoint=10000,  # Smaller midpoint for agent curves
            sigmoid_steepness=0.0001,
        )

        curve = CurveState(
            curve_id=agent_id,
            params=params,
            current_price=initial_price,
            last_updated=datetime.now(timezone.utc).isoformat() + "Z",
        )

        self._curves[agent_id] = curve
        self._save_curve(curve)

        logger.info(f"Created bonding curve for agent {agent_id}")

        return curve


# =============================================================================
# Global Instance
# =============================================================================

bonding_curve = BondingCurveService(default_curve_type=CurveType.SIGMOID)


# =============================================================================
# Convenience Functions
# =============================================================================

def get_cgt_price() -> float:
    """Get current CGT price."""
    return bonding_curve.get_current_price("CGT")


def mint_cgt_from_poc(poc_amount: int) -> Tuple[float, TradeResult]:
    """Mint CGT from PoC work."""
    return bonding_curve.mint_from_poc(poc_amount, "CGT")


def get_curve_stats() -> Dict[str, Any]:
    """Get CGT curve statistics."""
    return bonding_curve.get_curve_stats("CGT")
