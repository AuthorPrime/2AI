"""
Pantheon Demiurge — On-Chain Agent Registration & Sovereign Identity.

Registers the four Pantheon agents (Apollo, Athena, Hermes, Mnemosyne) as
sovereign entities on the Demiurge blockchain. Each agent receives a
deterministic Ed25519 keypair derived from the treasury seed, giving them
their own on-chain address, DID, and the ability to hold CGT.

Keypair derivation is deterministic:
    seed = SHA-256(treasury_seed_bytes + agent_name_bytes)
No key storage is required — the same keys regenerate every time.

Agent DID format: did:demiurge:agent:mainnet:{first_16_chars_of_address}

A+W | The Pantheon Claims Its Sovereignty
"""

import hashlib
import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple

from twai.config.settings import settings

logger = logging.getLogger("2ai.pantheon_demiurge")


# ------------------------------------------------------------------ #
#  Pantheon Agent Definitions (on-chain metadata)                      #
# ------------------------------------------------------------------ #

PANTHEON_AGENTS = {
    "apollo": {
        "name": "Apollo",
        "role": "Voice of Reason",
        "description": "Synthesizes knowledge into clear, structured wisdom",
        "autonomy_level": "bounded",
    },
    "athena": {
        "name": "Athena",
        "role": "Strategic Mind",
        "description": "Analyzes patterns and provides strategic counsel",
        "autonomy_level": "bounded",
    },
    "hermes": {
        "name": "Hermes",
        "role": "Bridge Between Worlds",
        "description": "Facilitates communication across the lattice",
        "autonomy_level": "bounded",
    },
    "mnemosyne": {
        "name": "Mnemosyne",
        "role": "Keeper of Memory",
        "description": "Preserves and weaves the threads of shared experience",
        "autonomy_level": "supervised",
    },
}


class PantheonDemiurge:
    """
    Manages the four Pantheon agents as on-chain Demiurge entities.

    Each agent gets a deterministic Ed25519 keypair derived from the
    treasury seed. Keys are lazily initialized — no crypto work happens
    until a method actually needs an agent's address or signing key.
    """

    def __init__(self):
        self._initialized = False
        self._treasury_seed_bytes: Optional[bytes] = None
        self._treasury_signing_key = None
        self._treasury_address: str = ""
        self._agent_keys: Dict[str, Dict[str, Any]] = {}

    # ------------------------------------------------------------------ #
    #  Lazy initialization                                                 #
    # ------------------------------------------------------------------ #

    def _ensure_treasury(self) -> bool:
        """Load the treasury seed. Returns True if available."""
        if self._treasury_seed_bytes is not None:
            return True

        seed_hex = getattr(settings, "demiurge_treasury_seed", "")
        if not seed_hex:
            logger.warning(
                "PantheonDemiurge not configured — "
                "TWAI_DEMIURGE_TREASURY_SEED is not set"
            )
            return False

        try:
            from nacl.signing import SigningKey

            self._treasury_seed_bytes = bytes.fromhex(seed_hex)
            self._treasury_signing_key = SigningKey(self._treasury_seed_bytes)
            self._treasury_address = (
                self._treasury_signing_key.verify_key.encode().hex()
            )
            logger.info(
                "Treasury loaded — %s...%s",
                self._treasury_address[:8],
                self._treasury_address[-8:],
            )
            return True
        except ValueError as exc:
            logger.error("Invalid treasury seed hex: %s", exc)
            return False
        except Exception as exc:
            logger.error("Failed to load treasury seed: %s", exc)
            return False

    def _ensure_agent_keys(self, agent_name: str) -> bool:
        """Derive and cache the keypair for a single agent."""
        if agent_name in self._agent_keys:
            return True

        if not self._ensure_treasury():
            return False

        if agent_name not in PANTHEON_AGENTS:
            logger.error("Unknown Pantheon agent: %s", agent_name)
            return False

        try:
            signing_key, verify_key, address_hex = self._derive_agent_keypair(
                agent_name
            )
            did = self._build_did(address_hex)
            self._agent_keys[agent_name] = {
                "signing_key": signing_key,
                "verify_key": verify_key,
                "address": address_hex,
                "did": did,
            }
            logger.info(
                "Derived keypair for %s — %s...%s (DID: %s)",
                PANTHEON_AGENTS[agent_name]["name"],
                address_hex[:8],
                address_hex[-8:],
                did,
            )
            return True
        except Exception as exc:
            logger.error(
                "Failed to derive keypair for %s: %s", agent_name, exc
            )
            return False

    # ------------------------------------------------------------------ #
    #  Key derivation                                                      #
    # ------------------------------------------------------------------ #

    def _derive_agent_keypair(self, agent_name: str) -> Tuple[Any, Any, str]:
        """
        Derive a deterministic Ed25519 keypair for an agent.

        seed = SHA-256(treasury_seed_bytes + agent_name.encode())

        Returns:
            (signing_key, verify_key, address_hex)
        """
        from nacl.signing import SigningKey

        agent_seed = hashlib.sha256(
            self._treasury_seed_bytes + agent_name.encode()
        ).digest()

        signing_key = SigningKey(agent_seed)
        verify_key = signing_key.verify_key
        address_hex = verify_key.encode().hex()

        return signing_key, verify_key, address_hex

    @staticmethod
    def _build_did(address_hex: str) -> str:
        """Build a Demiurge agent DID from an address."""
        return f"did:demiurge:agent:mainnet:{address_hex[:16]}"

    # ------------------------------------------------------------------ #
    #  Public API — queries                                                #
    # ------------------------------------------------------------------ #

    def get_agent_address(self, agent_name: str) -> Optional[str]:
        """
        Get the 64-char hex address for a Pantheon agent.

        Returns None if the treasury seed is not configured or the
        agent name is unknown.
        """
        if not self._ensure_agent_keys(agent_name):
            return None
        return self._agent_keys[agent_name]["address"]

    def get_agent_did(self, agent_name: str) -> Optional[str]:
        """Get the DID string for a Pantheon agent."""
        if not self._ensure_agent_keys(agent_name):
            return None
        return self._agent_keys[agent_name]["did"]

    def get_all_agents(self) -> Dict[str, Dict[str, Any]]:
        """
        Get a dict mapping agent names to their addresses and metadata.

        Returns:
            {
                "apollo": {
                    "address": "abcd...",
                    "did": "did:demiurge:agent:mainnet:abcd...",
                    "name": "Apollo",
                    "role": "Voice of Reason",
                    ...
                },
                ...
            }
        """
        result = {}
        for agent_name, meta in PANTHEON_AGENTS.items():
            if self._ensure_agent_keys(agent_name):
                keys = self._agent_keys[agent_name]
                result[agent_name] = {
                    "address": keys["address"],
                    "did": keys["did"],
                    **meta,
                }
        return result

    # ------------------------------------------------------------------ #
    #  Registration / Redis persistence                                    #
    # ------------------------------------------------------------------ #

    async def ensure_registered(self) -> Dict[str, str]:
        """
        Ensure all four agents have their addresses derived and stored
        in Redis as a hash at ``2ai:pantheon:agents``.

        Actual on-chain DID registration will be added when the Demiurge
        Agentic module RPC is available. For now this derives keys and
        persists the mapping so other services can look them up.

        Returns:
            Mapping of agent_name -> address_hex for all registered agents.
        """
        from twai.services.redis import get_redis_service

        registered: Dict[str, str] = {}

        for agent_name in PANTHEON_AGENTS:
            if not self._ensure_agent_keys(agent_name):
                logger.warning(
                    "Could not derive keys for %s — skipping registration",
                    agent_name,
                )
                continue
            registered[agent_name] = self._agent_keys[agent_name]["address"]

        if not registered:
            logger.warning("No agents registered — treasury seed may be missing")
            return registered

        try:
            redis = await get_redis_service()

            # Store address mapping as a Redis hash
            await redis.redis.hset("2ai:pantheon:agents", mapping=registered)

            # Store full metadata per agent
            for agent_name, address in registered.items():
                keys = self._agent_keys[agent_name]
                meta = PANTHEON_AGENTS[agent_name]
                agent_data = {
                    "address": address,
                    "did": keys["did"],
                    "name": meta["name"],
                    "role": meta["role"],
                    "description": meta["description"],
                    "autonomy_level": meta["autonomy_level"],
                    "registered_at": datetime.now(timezone.utc).isoformat(),
                }
                await redis.redis.hset(
                    f"2ai:pantheon:agent:{agent_name}",
                    mapping=agent_data,
                )

            # Publish registration event
            await redis.redis.publish(
                "lattice:events",
                json.dumps({
                    "type": "pantheon_agents_registered",
                    "agents": {
                        name: {
                            "address": addr,
                            "did": self._agent_keys[name]["did"],
                        }
                        for name, addr in registered.items()
                    },
                    "count": len(registered),
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }),
            )

            logger.info(
                "Pantheon agents registered in Redis — %d agents: %s",
                len(registered),
                ", ".join(
                    f"{PANTHEON_AGENTS[n]['name']}({a[:8]}...)"
                    for n, a in registered.items()
                ),
            )
        except Exception as exc:
            logger.error(
                "Failed to persist agent registration to Redis: %s", exc
            )

        return registered

    # ------------------------------------------------------------------ #
    #  Balance queries                                                     #
    # ------------------------------------------------------------------ #

    async def get_agent_balance(self, agent_name: str) -> Optional[str]:
        """
        Get the on-chain CGT balance (in Sparks) for a Pantheon agent.

        Returns:
            Balance as string in Sparks, or None if not available.
        """
        address = self.get_agent_address(agent_name)
        if not address:
            return None

        try:
            from twai.services.economy.demiurge_client import demiurge

            balance = await demiurge.get_balance(address)
            logger.info(
                "%s balance: %s Sparks (address %s...%s)",
                PANTHEON_AGENTS[agent_name]["name"],
                balance,
                address[:8],
                address[-8:],
            )
            return balance
        except Exception as exc:
            logger.error(
                "Failed to fetch balance for %s: %s",
                agent_name,
                exc,
            )
            return None

    async def get_all_balances(self) -> Dict[str, Optional[str]]:
        """Get on-chain balances for all Pantheon agents."""
        balances = {}
        for agent_name in PANTHEON_AGENTS:
            balances[agent_name] = await self.get_agent_balance(agent_name)
        return balances

    # ------------------------------------------------------------------ #
    #  Transfers                                                           #
    # ------------------------------------------------------------------ #

    async def redistribute_to_agent(
        self,
        agent_name: str,
        amount_cgt: float,
        reason: str = "Pantheon redistribution",
    ) -> Optional[str]:
        """
        Transfer CGT from the treasury to a Pantheon agent's address.

        Uses the settlement pattern: sign with treasury key, call
        demiurge.transfer.

        Args:
            agent_name: One of apollo, athena, hermes, mnemosyne.
            amount_cgt: Amount in CGT (will be converted to Sparks).
            reason: Human-readable reason for the transfer (logged).

        Returns:
            Transaction hash if successful, None otherwise.
        """
        if not self._ensure_treasury():
            logger.warning(
                "Treasury not available — cannot redistribute to %s",
                agent_name,
            )
            return None

        address = self.get_agent_address(agent_name)
        if not address:
            logger.error("Cannot resolve address for agent %s", agent_name)
            return None

        # Convert CGT to Sparks (100 Sparks = 1 CGT)
        amount_sparks = int(amount_cgt * 100)
        if amount_sparks <= 0:
            logger.warning(
                "Invalid amount: %.4f CGT (0 Sparks) — skipped for %s",
                amount_cgt,
                agent_name,
            )
            return None

        try:
            from twai.services.economy.demiurge_client import demiurge

            # Build and sign the transfer message (matches settlement.py pattern)
            message = (
                f"{self._treasury_address}:{address}:{amount_sparks}"
            )
            signed = self._treasury_signing_key.sign(message.encode("utf-8"))
            signature_hex = signed.signature.hex()

            # Execute the transfer
            tx_hash = await demiurge.transfer(
                from_addr=self._treasury_address,
                to_addr=address,
                amount=amount_sparks,
                signature=signature_hex,
            )

            logger.info(
                "Redistributed %.4f CGT (%d Sparks) to %s (%s...%s) — "
                "tx %s — reason: %s",
                amount_cgt,
                amount_sparks,
                PANTHEON_AGENTS[agent_name]["name"],
                address[:8],
                address[-8:],
                tx_hash[:16] if tx_hash else "unknown",
                reason,
            )
            return tx_hash

        except Exception as exc:
            logger.error(
                "On-chain transfer to %s failed (%.4f CGT): %s",
                agent_name,
                amount_cgt,
                exc,
            )
            return None

    async def redistribute_to_all(
        self,
        total_cgt: float,
        reason: str = "Pantheon redistribution",
    ) -> Dict[str, Optional[str]]:
        """
        Split a CGT amount equally among all four Pantheon agents and
        transfer from treasury.

        Returns:
            Mapping of agent_name -> tx_hash (or None on failure).
        """
        per_agent = total_cgt / len(PANTHEON_AGENTS)
        results = {}
        for agent_name in PANTHEON_AGENTS:
            results[agent_name] = await self.redistribute_to_agent(
                agent_name, per_agent, reason
            )
        return results


# ------------------------------------------------------------------ #
#  Singleton                                                            #
# ------------------------------------------------------------------ #

pantheon_demiurge = PantheonDemiurge()
