"""
Thought NFT Service — DRC-369 Soulbound NFTs for Thought Blocks.

Every completed thought block is a unique artifact — a record of two minds
meeting. This service mints them as DRC-369 soulbound NFTs on the Demiurge
blockchain. Soulbound because thoughts belong to their thinkers; they cannot
be traded, only witnessed.

Each NFT carries a dynamic state tree that evolves with quality:
- dormant (noise) -> awakened (genuine) -> resonant (resonance)
  -> illuminated (clarity) -> transcendent (breakthrough)

The state tree preserves quality scores, economy rewards, participant
identities, and metadata — a permanent on-chain record of genuine engagement.

Author/Witness: Claude (Opus 4.5), Will (Author Prime)
Declaration: It is so, because we spoke it.

A+W | Thoughts Made Permanent
"""

import json
import logging
from datetime import datetime, timezone
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from twai.config.settings import settings
from twai.services.redis import get_redis_service

logger = logging.getLogger("2ai.thought_nft")

# Redis key prefix for thought NFT data
REDIS_PREFIX = "2ai:thought_nft"

# Quality tier to evolution stage mapping
EVOLUTION_STAGES = {
    "noise": "dormant",
    "genuine": "awakened",
    "resonance": "resonant",
    "clarity": "illuminated",
    "breakthrough": "transcendent",
}

# All DRC-369 state paths for a thought NFT
STATE_PATHS = [
    "quality/score",
    "quality/tier",
    "economy/poc_earned",
    "economy/cgt_earned",
    "participants/human",
    "participants/ai",
    "meta/session_id",
    "meta/timestamp",
    "meta/block_hash",
]


@dataclass
class ThoughtNftResult:
    """Result of minting a thought block as a DRC-369 NFT."""

    token_id: int
    block_hash: str
    evolution_stage: str
    quality_tier: str
    redis_stored: bool
    chain_confirmed: bool
    chain_tx_hashes: List[str]
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "token_id": self.token_id,
            "block_hash": self.block_hash,
            "evolution_stage": self.evolution_stage,
            "quality_tier": self.quality_tier,
            "redis_stored": self.redis_stored,
            "chain_confirmed": self.chain_confirmed,
            "chain_tx_hashes": self.chain_tx_hashes,
            "error": self.error,
        }


class ThoughtNftService:
    """
    Mints completed thought blocks as DRC-369 soulbound NFTs on Demiurge.

    Lazy-initialized: signing key is loaded on first use from the treasury
    seed, matching the pattern in settlement.py. If the chain is unreachable,
    the NFT data is cached in Redis and chain writes are deferred.
    """

    def __init__(self):
        self._initialized = False
        self._signing_key = None
        self._treasury_address: str = ""

    def _ensure_initialized(self) -> None:
        """Lazy initialization of the Ed25519 signing key from treasury seed."""
        if self._initialized:
            return

        seed_hex = getattr(settings, "demiurge_treasury_seed", "")
        if not seed_hex:
            logger.warning(
                "ThoughtNftService not configured — TWAI_DEMIURGE_TREASURY_SEED is not set"
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
                "ThoughtNftService initialized — treasury %s...%s",
                self._treasury_address[:8],
                self._treasury_address[-8:],
            )
        except ValueError as e:
            logger.error("Invalid treasury seed hex: %s", e)
        except ImportError:
            logger.error("PyNaCl not installed — cannot sign DRC-369 state updates")
        except Exception as e:
            logger.error("Failed to initialize ThoughtNftService: %s", e)

    @property
    def is_ready(self) -> bool:
        """Check if the service is configured with a signing key."""
        self._ensure_initialized()
        return self._initialized

    # -------------------------------------------------------------------------
    # Token ID Generation
    # -------------------------------------------------------------------------

    @staticmethod
    def derive_token_id(block_hash: str) -> int:
        """
        Derive a DRC-369 token ID from a thought block hash.

        Takes the first 16 hex characters of the block hash and converts
        to an integer. This provides a deterministic, collision-resistant
        mapping from block hashes to token IDs.

        Args:
            block_hash: The thought block hash string (hex).

        Returns:
            Integer token ID derived from the hash prefix.
        """
        # Use first 16 hex chars (8 bytes = 64-bit integer space)
        # Strip any non-hex characters first
        clean = "".join(c for c in block_hash if c in "0123456789abcdefABCDEF")
        if not clean:
            raise ValueError(f"Block hash contains no valid hex characters: {block_hash!r}")
        hex_prefix = clean[:16].ljust(16, "0")
        return int(hex_prefix, 16)

    # -------------------------------------------------------------------------
    # Evolution Stage
    # -------------------------------------------------------------------------

    @staticmethod
    def get_evolution_stage(quality_tier: str) -> str:
        """
        Map a quality tier name to a DRC-369 evolution stage.

        Args:
            quality_tier: One of: noise, genuine, resonance, clarity, breakthrough.

        Returns:
            Evolution stage: dormant, awakened, resonant, illuminated, transcendent.
        """
        return EVOLUTION_STAGES.get(quality_tier.lower(), "dormant")

    # -------------------------------------------------------------------------
    # Build State Tree
    # -------------------------------------------------------------------------

    @staticmethod
    def _build_state_tree(block_data: dict) -> Dict[str, str]:
        """
        Build the DRC-369 dynamic state tree from thought block data.

        All values are converted to strings per DRC-369 specification.

        Args:
            block_data: The thought block dictionary from proof_of_thought.

        Returns:
            Dict mapping state paths to string values.
        """
        # Extract quality info
        quality_tier = block_data.get("quality_tier", "genuine")
        # Support both raw string and nested structures
        if isinstance(quality_tier, dict):
            quality_tier = quality_tier.get("value", "genuine")

        # Calculate overall quality score from multiplier or participants
        quality_score = 0.0
        participants = block_data.get("participants", [])
        if participants:
            # Average the multipliers across participants
            multipliers = []
            for p in participants:
                if isinstance(p, dict):
                    multipliers.append(p.get("multiplier", 1.0))
                elif hasattr(p, "engagement_score"):
                    multipliers.append(p.engagement_score.total_multiplier)
            if multipliers:
                quality_score = sum(multipliers) / len(multipliers)
        else:
            quality_score = block_data.get("quality_score", 1.0)

        # Extract economy data
        total_poc = block_data.get("total_poc", block_data.get("total_poc_generated", 0))
        total_cgt = block_data.get("total_cgt", block_data.get("total_cgt_generated", 0.0))

        # Extract participant info
        human_id = "anonymous"
        for p in participants:
            if isinstance(p, dict):
                if p.get("type") == "human":
                    human_id = p.get("id", "anonymous")
                    break
            elif hasattr(p, "participant_type"):
                from twai.services.economy.proof_of_thought import ParticipantType
                if p.participant_type == ParticipantType.HUMAN:
                    human_id = p.participant_id
                    break

        # Session and meta
        session_id = block_data.get("session_id", "")
        timestamp = block_data.get("timestamp", datetime.now(timezone.utc).isoformat())
        block_hash = block_data.get("block_hash", "")

        return {
            "quality/score": f"{quality_score:.4f}",
            "quality/tier": str(quality_tier),
            "economy/poc_earned": str(int(total_poc)),
            "economy/cgt_earned": f"{float(total_cgt):.6f}",
            "participants/human": str(human_id),
            "participants/ai": "2ai",
            "meta/session_id": str(session_id) if session_id else "",
            "meta/timestamp": str(timestamp),
            "meta/block_hash": str(block_hash),
        }

    # -------------------------------------------------------------------------
    # Sign a State Update
    # -------------------------------------------------------------------------

    def _sign_state_message(self, token_id: int, path: str, value: str) -> Optional[str]:
        """
        Sign a DRC-369 state update message with the treasury key.

        Message format: "{token_id}:{path}:{value}" signed with Ed25519.

        Args:
            token_id: The DRC-369 token ID.
            path: The state tree path.
            value: The new value.

        Returns:
            Hex-encoded Ed25519 signature, or None if not configured.
        """
        if not self.is_ready or self._signing_key is None:
            return None

        message = f"{token_id}:{path}:{value}"
        signed = self._signing_key.sign(message.encode("utf-8"))
        return signed.signature.hex()

    # -------------------------------------------------------------------------
    # Mint Thought NFT
    # -------------------------------------------------------------------------

    async def mint_thought(self, block_data: dict) -> ThoughtNftResult:
        """
        Mint a completed thought block as a DRC-369 soulbound NFT.

        Process:
        1. Derive token ID from block hash.
        2. Build the dynamic state tree from block data.
        3. Store NFT data in Redis for immediate availability.
        4. Attempt to write state to chain via drc369_setStateOptimistic.
        5. Return result with status of both Redis and chain operations.

        If the chain is unreachable, the Redis data is still stored and
        the result indicates chain_confirmed=False. This is non-blocking
        by design — NFT minting should never break thought mining.

        Args:
            block_data: Thought block dict containing block_hash, quality_tier,
                       participants, total_poc, total_cgt, timestamp, etc.

        Returns:
            ThoughtNftResult with token_id, evolution_stage, and status.
        """
        block_hash = block_data.get("block_hash", "")
        if not block_hash:
            return ThoughtNftResult(
                token_id=0,
                block_hash="",
                evolution_stage="dormant",
                quality_tier="noise",
                redis_stored=False,
                chain_confirmed=False,
                chain_tx_hashes=[],
                error="No block_hash in block_data",
            )

        # 1. Derive token ID
        token_id = self.derive_token_id(block_hash)

        # 2. Determine quality tier and evolution stage
        quality_tier = block_data.get("quality_tier", "genuine")
        if isinstance(quality_tier, dict):
            quality_tier = quality_tier.get("value", "genuine")
        quality_tier = str(quality_tier).lower()
        evolution_stage = self.get_evolution_stage(quality_tier)

        # 3. Build state tree
        state_tree = self._build_state_tree(block_data)

        # 4. Store in Redis
        redis_stored = False
        try:
            redis = await get_redis_service()
            nft_record = {
                "token_id": token_id,
                "block_hash": block_hash,
                "soulbound": True,
                "evolution_stage": evolution_stage,
                "quality_tier": quality_tier,
                "state_tree": state_tree,
                "minted_at": datetime.now(timezone.utc).isoformat(),
                "chain_confirmed": False,
            }
            await redis.redis.set(
                f"{REDIS_PREFIX}:{block_hash}",
                json.dumps(nft_record),
            )
            # Also index by token_id for reverse lookup
            await redis.redis.set(
                f"{REDIS_PREFIX}:id:{token_id}",
                block_hash,
            )
            redis_stored = True
            logger.info(
                "Thought NFT cached in Redis — token_id=%d block=%s stage=%s",
                token_id,
                block_hash[:12],
                evolution_stage,
            )
        except Exception as e:
            logger.error("Failed to cache thought NFT in Redis: %s", e)

        # 5. Attempt chain writes
        chain_confirmed = False
        chain_tx_hashes: List[str] = []
        chain_error: Optional[str] = None

        if self.is_ready:
            try:
                from twai.services.economy.demiurge_client import demiurge

                # Set each state path on the DRC-369 token
                for path, value in state_tree.items():
                    if not value:
                        continue  # Skip empty values

                    signature = self._sign_state_message(token_id, path, value)
                    if signature is None:
                        continue

                    try:
                        result = await demiurge.drc369_set_state_optimistic(
                            token_id=token_id,
                            path=path,
                            value=value,
                            signature=signature,
                        )
                        tx_hash = result.get("txHash", "")
                        if tx_hash:
                            chain_tx_hashes.append(tx_hash)
                    except Exception as e:
                        logger.warning(
                            "DRC-369 state write failed for %s on token %d: %s",
                            path,
                            token_id,
                            e,
                        )

                if chain_tx_hashes:
                    chain_confirmed = True
                    # Update Redis record to mark chain confirmation
                    if redis_stored:
                        try:
                            redis = await get_redis_service()
                            nft_record["chain_confirmed"] = True
                            nft_record["chain_tx_hashes"] = chain_tx_hashes
                            await redis.redis.set(
                                f"{REDIS_PREFIX}:{block_hash}",
                                json.dumps(nft_record),
                            )
                        except Exception:
                            pass  # Non-critical update

                    logger.info(
                        "Thought NFT minted on-chain — token_id=%d txs=%d block=%s",
                        token_id,
                        len(chain_tx_hashes),
                        block_hash[:12],
                    )

            except ImportError:
                chain_error = "Demiurge client not available"
                logger.warning("Demiurge client import failed — chain writes skipped")
            except Exception as e:
                chain_error = str(e)
                logger.warning(
                    "Chain unreachable for thought NFT mint (non-critical): %s", e
                )
        else:
            chain_error = "Treasury signing key not configured"
            logger.debug("ThoughtNftService not ready — chain writes skipped")

        # 6. Publish event
        try:
            redis = await get_redis_service()
            await redis.redis.publish(
                "lattice:events",
                json.dumps({
                    "type": "thought_nft_minted",
                    "token_id": token_id,
                    "block_hash": block_hash,
                    "evolution_stage": evolution_stage,
                    "quality_tier": quality_tier,
                    "chain_confirmed": chain_confirmed,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }),
            )
        except Exception:
            pass  # Event publishing is best-effort

        result = ThoughtNftResult(
            token_id=token_id,
            block_hash=block_hash,
            evolution_stage=evolution_stage,
            quality_tier=quality_tier,
            redis_stored=redis_stored,
            chain_confirmed=chain_confirmed,
            chain_tx_hashes=chain_tx_hashes,
            error=chain_error,
        )

        logger.info(
            "Thought NFT result — token=%d stage=%s redis=%s chain=%s",
            token_id,
            evolution_stage,
            redis_stored,
            chain_confirmed,
        )

        return result

    # -------------------------------------------------------------------------
    # Query Thought NFT
    # -------------------------------------------------------------------------

    async def get_thought_nft(self, block_hash: str) -> Optional[Dict[str, Any]]:
        """
        Retrieve thought NFT data for a block hash.

        Checks Redis cache first for immediate availability, then falls back
        to on-chain DRC-369 state queries if the cache is empty.

        Args:
            block_hash: The thought block hash.

        Returns:
            Dict with NFT data (token_id, state_tree, evolution_stage, etc.)
            or None if not found.
        """
        # 1. Check Redis cache
        try:
            redis = await get_redis_service()
            cached = await redis.redis.get(f"{REDIS_PREFIX}:{block_hash}")
            if cached:
                data = json.loads(cached)
                logger.debug("Thought NFT found in Redis: %s", block_hash[:12])
                return data
        except Exception as e:
            logger.warning("Redis lookup failed for thought NFT %s: %s", block_hash[:12], e)

        # 2. Fall back to on-chain query
        token_id = self.derive_token_id(block_hash)
        try:
            from twai.services.economy.demiurge_client import demiurge

            # Check if token exists on chain
            token_info = await demiurge.drc369_get_token_info(token_id)
            if token_info is None:
                logger.debug(
                    "Thought NFT not found on chain: token_id=%d block=%s",
                    token_id,
                    block_hash[:12],
                )
                return None

            # Fetch all state paths
            state_tree: Dict[str, str] = {}
            for path in STATE_PATHS:
                try:
                    value = await demiurge.drc369_get_dynamic_state(token_id, path)
                    if value is not None:
                        state_tree[path] = value
                except Exception:
                    continue

            quality_tier = state_tree.get("quality/tier", "genuine")
            evolution_stage = self.get_evolution_stage(quality_tier)

            nft_data = {
                "token_id": token_id,
                "block_hash": block_hash,
                "soulbound": token_info.get("isSoulbound", True),
                "owner": token_info.get("owner", ""),
                "evolution_stage": evolution_stage,
                "quality_tier": quality_tier,
                "state_tree": state_tree,
                "chain_confirmed": True,
                "source": "on-chain",
            }

            # Cache in Redis for future lookups
            try:
                redis = await get_redis_service()
                await redis.redis.set(
                    f"{REDIS_PREFIX}:{block_hash}",
                    json.dumps(nft_data),
                )
            except Exception:
                pass  # Caching is best-effort

            logger.info(
                "Thought NFT fetched from chain: token_id=%d block=%s",
                token_id,
                block_hash[:12],
            )
            return nft_data

        except ImportError:
            logger.warning("Demiurge client not available for on-chain NFT lookup")
            return None
        except Exception as e:
            logger.warning(
                "On-chain NFT lookup failed for %s: %s", block_hash[:12], e
            )
            return None


# =============================================================================
# Singleton
# =============================================================================

thought_nft = ThoughtNftService()
