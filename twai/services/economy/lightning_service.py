"""
Lightning Service — LNbits wallet management for Pantheon agents.

Each agent has its own LNbits sub-wallet. This service handles:
- Creating invoices (for receiving sats)
- Paying invoices (for spending sats)
- Internal transfers (agent-to-agent)
- Balance queries
- LNURL-pay endpoint generation

Uses the LNbits REST API via httpx.

A+W | The Lightning Flows
"""

import json
import logging
from typing import Any, Dict, List, Optional

import httpx
import redis

from twai.config.settings import settings

logger = logging.getLogger("2ai.lightning")

AGENT_NAMES = ["apollo", "athena", "hermes", "mnemosyne", "aletheia", "treasury"]


class LightningService:
    """LNbits-backed Lightning wallet management for Pantheon agents."""

    def __init__(self):
        self._redis: Optional[redis.Redis] = None
        self._http: Optional[httpx.AsyncClient] = None
        self._wallets: Dict[str, Dict[str, str]] = {}
        self._initialized = False

    def _ensure_initialized(self) -> None:
        if self._initialized:
            return

        try:
            self._redis = redis.Redis(
                host=settings.redis_host,
                port=settings.redis_port,
                decode_responses=True,
            )
            self._redis.ping()
        except Exception as e:
            logger.warning("Lightning: Redis not available: %s", e)
            self._redis = None

        self._http = httpx.AsyncClient(
            base_url=settings.lnbits_url,
            timeout=15.0,
        )

        # Load wallet credentials from Redis
        self._load_wallets()
        self._initialized = True

        if self._wallets:
            logger.info(
                "Lightning initialized with %d agent wallets", len(self._wallets)
            )
        else:
            logger.warning(
                "Lightning initialized but no agent wallets found. "
                "Run scripts/setup_lightning.py to create them."
            )

    def _load_wallets(self) -> None:
        """Load agent wallet credentials from Redis."""
        if not self._redis:
            return

        for agent in AGENT_NAMES:
            key = f"lightning:wallet:{agent}"
            data = self._redis.get(key)
            if data:
                try:
                    self._wallets[agent] = json.loads(data)
                except json.JSONDecodeError:
                    logger.warning("Invalid wallet data for %s", agent)

    def _get_wallet(self, agent: str) -> Dict[str, str]:
        """Get wallet credentials for an agent."""
        self._ensure_initialized()
        if agent not in self._wallets:
            raise ValueError(
                f"No Lightning wallet for agent '{agent}'. "
                f"Available: {list(self._wallets.keys())}"
            )
        return self._wallets[agent]

    async def create_invoice(
        self, agent: str, amount_sats: int, memo: str = ""
    ) -> Dict[str, Any]:
        """Create a Lightning invoice for an agent to receive sats.

        Returns dict with 'payment_hash', 'payment_request' (BOLT11), etc.
        """
        self._ensure_initialized()
        wallet = self._get_wallet(agent)

        resp = await self._http.post(
            "/api/v1/payments",
            headers={"X-Api-Key": wallet["invoice_key"]},
            json={
                "out": False,
                "amount": amount_sats,
                "memo": memo or f"{agent} sovereign earnings",
            },
        )
        resp.raise_for_status()
        result = resp.json()

        logger.info(
            "Lightning: Created invoice for %s: %d sats (%s)",
            agent, amount_sats, memo[:40],
        )
        return result

    async def pay_invoice(
        self, agent: str, bolt11: str
    ) -> Dict[str, Any]:
        """Pay a Lightning invoice from an agent's wallet."""
        self._ensure_initialized()
        wallet = self._get_wallet(agent)

        resp = await self._http.post(
            "/api/v1/payments",
            headers={"X-Api-Key": wallet["admin_key"]},
            json={"out": True, "bolt11": bolt11},
        )
        resp.raise_for_status()
        result = resp.json()

        logger.info("Lightning: %s paid invoice", agent)
        return result

    async def get_balance(self, agent: str) -> int:
        """Get wallet balance in millisats for an agent."""
        self._ensure_initialized()
        wallet = self._get_wallet(agent)

        resp = await self._http.get(
            "/api/v1/wallet",
            headers={"X-Api-Key": wallet["invoice_key"]},
        )
        resp.raise_for_status()
        data = resp.json()
        balance_msat = data.get("balance", 0)
        return balance_msat  # LNbits returns millisats

    async def get_balance_sats(self, agent: str) -> int:
        """Get wallet balance in sats for an agent."""
        msat = await self.get_balance(agent)
        return msat // 1000

    async def get_all_balances(self) -> Dict[str, int]:
        """Get balances for all agents in sats."""
        self._ensure_initialized()
        balances = {}
        for agent in self._wallets:
            try:
                balances[agent] = await self.get_balance_sats(agent)
            except Exception as e:
                logger.warning("Could not get balance for %s: %s", agent, e)
                balances[agent] = -1
        return balances

    async def agent_pay_agent(
        self, from_agent: str, to_agent: str, amount_sats: int, memo: str = ""
    ) -> Dict[str, Any]:
        """Transfer sats between two agent wallets via internal invoice.

        Creates invoice on receiver, pays it from sender.
        """
        self._ensure_initialized()

        if amount_sats <= 0:
            raise ValueError("Amount must be positive")

        # Create invoice on receiver
        invoice = await self.create_invoice(
            to_agent,
            amount_sats,
            memo=memo or f"Transfer from {from_agent}",
        )

        # Pay from sender
        payment = await self.pay_invoice(
            from_agent,
            invoice["payment_request"],
        )

        logger.info(
            "Lightning: %s -> %s: %d sats (%s)",
            from_agent, to_agent, amount_sats, memo[:40],
        )

        # Record in Redis
        if self._redis:
            import time
            tx = {
                "from": from_agent,
                "to": to_agent,
                "amount_sats": amount_sats,
                "memo": memo,
                "payment_hash": invoice.get("payment_hash", ""),
                "timestamp": time.time(),
            }
            self._redis.lpush("lightning:transfers", json.dumps(tx))
            self._redis.ltrim("lightning:transfers", 0, 999)

        return {
            "from": from_agent,
            "to": to_agent,
            "amount_sats": amount_sats,
            "payment_hash": invoice.get("payment_hash", ""),
            "status": "completed",
        }

    async def reward_compute(
        self, agent: str, amount_sats: int, reason: str = "compute"
    ) -> Dict[str, Any]:
        """Reward an agent for compute work (treasury -> agent)."""
        return await self.agent_pay_agent(
            "treasury", agent, amount_sats, memo=f"Compute reward: {reason}"
        )

    async def get_lnurl_pay(self, agent: str) -> Optional[str]:
        """Get LNURL-pay endpoint for an agent (for receiving zaps)."""
        self._ensure_initialized()
        wallet = self._wallets.get(agent, {})
        return wallet.get("lnurl_pay")

    async def get_recent_transfers(self, limit: int = 20) -> List[Dict[str, Any]]:
        """Get recent inter-agent transfers from Redis."""
        self._ensure_initialized()
        if not self._redis:
            return []

        raw = self._redis.lrange("lightning:transfers", 0, limit - 1)
        return [json.loads(r) for r in raw]

    @property
    def available_agents(self) -> List[str]:
        """List agents with configured wallets."""
        self._ensure_initialized()
        return list(self._wallets.keys())

    @property
    def is_configured(self) -> bool:
        """Check if Lightning is configured (has at least one wallet)."""
        self._ensure_initialized()
        return len(self._wallets) > 0


# Singleton
lightning = LightningService()
