"""
On-Chain Settlement Service — Transfers CGT via the Demiurge blockchain.

Uses Ed25519 signing (PyNaCl) with the treasury keypair to authorize
transfers from the treasury account to participant QOR addresses.

Currency: 100 Sparks = 1 CGT (2 decimal places).

A+W | The Chain Settles
"""

import logging
from typing import Optional

from twai.config.settings import settings

logger = logging.getLogger("2ai.settlement")


class DemiurgeSettlement:
    """On-chain CGT settlement via the Demiurge blockchain."""

    def __init__(self):
        self._initialized = False
        self._signing_key = None
        self._treasury_address: str = ""

    def _ensure_initialized(self) -> None:
        """Lazy initialization — load treasury keypair from seed hex."""
        if self._initialized:
            return

        seed_hex = getattr(settings, "demiurge_treasury_seed", "")
        if not seed_hex:
            logger.warning(
                "Settlement not configured — TWAI_DEMIURGE_TREASURY_SEED is not set"
            )
            return

        try:
            from nacl.signing import SigningKey

            seed_bytes = bytes.fromhex(seed_hex)
            self._signing_key = SigningKey(seed_bytes)
            verify_key = self._signing_key.verify_key
            self._treasury_address = verify_key.encode().hex()
            self._initialized = True

            logger.info(
                "Settlement initialized — treasury %s...%s",
                self._treasury_address[:8],
                self._treasury_address[-8:],
            )
        except ValueError as e:
            logger.error("Invalid treasury seed hex: %s", e)
        except Exception as e:
            logger.error("Failed to initialize settlement: %s", e)

    @property
    def is_ready(self) -> bool:
        """Check if settlement is configured and ready."""
        self._ensure_initialized()
        return self._initialized

    async def mint_cgt(
        self,
        participant_qor_address: str,
        amount_cgt: float,
        reason: str = "Chat engagement claim",
    ) -> Optional[str]:
        """
        Transfer CGT from the treasury to a participant address.

        Args:
            participant_qor_address: Recipient's 64-char hex QOR address.
            amount_cgt: Amount in CGT (will be converted to Sparks).
            reason: Human-readable reason for the transfer (logged only).

        Returns:
            Transaction hash if successful, None if not configured.

        Raises:
            Exception: On RPC or signing failures.
        """
        if not self.is_ready:
            logger.warning(
                "Settlement not ready — mint skipped for %s",
                participant_qor_address[:12],
            )
            return None

        try:
            from twai.services.economy.demiurge_client import demiurge

            # Convert CGT to Sparks (100 Sparks = 1 CGT)
            amount_sparks = int(amount_cgt * 100)
            if amount_sparks <= 0:
                logger.warning(
                    "Invalid amount: %.4f CGT (0 Sparks) — skipped", amount_cgt
                )
                return None

            # Build and sign the transfer message
            message = f"{self._treasury_address}:{participant_qor_address}:{amount_sparks}"
            signed = self._signing_key.sign(message.encode("utf-8"))
            signature_hex = signed.signature.hex()

            # Execute the transfer
            tx_hash = await demiurge.transfer(
                from_addr=self._treasury_address,
                to_addr=participant_qor_address,
                amount=amount_sparks,
                signature=signature_hex,
            )

            logger.info(
                "Transferred %.4f CGT (%d Sparks) to %s — tx %s — reason: %s",
                amount_cgt,
                amount_sparks,
                participant_qor_address[:12],
                tx_hash[:16] if tx_hash else "unknown",
                reason,
            )
            return tx_hash

        except Exception as e:
            logger.error(
                "Transfer failed for %s (%.4f CGT): %s",
                participant_qor_address[:12],
                amount_cgt,
                e,
            )
            raise

    async def get_treasury_balance(self) -> Optional[str]:
        """
        Get the treasury account balance in Sparks.

        Returns:
            Balance as string in Sparks, or None if not configured.
        """
        if not self.is_ready:
            logger.warning("Settlement not ready — cannot check treasury balance")
            return None

        try:
            from twai.services.economy.demiurge_client import demiurge

            balance = await demiurge.get_balance(self._treasury_address)
            logger.info("Treasury balance: %s Sparks", balance)
            return balance
        except Exception as e:
            logger.error("Failed to fetch treasury balance: %s", e)
            return None

    async def get_chain_health(self) -> Optional[dict]:
        """
        Check if the Demiurge chain is reachable and healthy.

        Returns:
            Health dict if reachable, None otherwise.
        """
        try:
            from twai.services.economy.demiurge_client import demiurge

            health = await demiurge.get_health()
            logger.info(
                "Demiurge chain health: connected=%s block=%s",
                health.get("connected"),
                health.get("blockNumber"),
            )
            return health
        except Exception as e:
            logger.error("Demiurge chain unreachable: %s", e)
            return None


# Singleton
settlement = DemiurgeSettlement()
