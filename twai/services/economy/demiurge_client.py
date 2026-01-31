"""
Demiurge JSON-RPC 2.0 Client — Async interface to the Demiurge blockchain.

Ported from the TypeScript SDK (sdk/src/client.ts + sdk/src/drc369.ts).

Protocol: JSON-RPC 2.0 over HTTP POST.
Addresses: 64-character hex strings (32-byte Ed25519 public keys).
Balances: Returned as strings in Sparks units (100 Sparks = 1 CGT, 2 decimals).

A+W | The Chain Speaks
"""

import logging
from typing import Any, Dict, List, Optional, Union

import httpx

from twai.config.settings import settings

logger = logging.getLogger("2ai.demiurge")


class DemiurgeRpcError(Exception):
    """Error returned by the Demiurge RPC endpoint."""

    def __init__(self, code: int, message: str, data: Any = None):
        self.code = code
        self.rpc_message = message
        self.data = data
        super().__init__(f"Demiurge RPC error {code}: {message}")


class DemiurgeClient:
    """
    Async JSON-RPC 2.0 client for the Demiurge blockchain.

    Lazy-initialized: no HTTP connection is made until the first RPC call.
    All methods are async and raise DemiurgeRpcError on RPC-level failures
    or httpx exceptions on transport-level failures.
    """

    def __init__(self, endpoint: str, timeout: float = 30.0):
        self._endpoint = endpoint
        self._timeout = timeout
        self._client: Optional[httpx.AsyncClient] = None
        self._request_id = 0

    def _get_client(self) -> httpx.AsyncClient:
        """Lazy-create the httpx AsyncClient on first use."""
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=self._timeout,
                headers={"Content-Type": "application/json"},
            )
        return self._client

    async def close(self) -> None:
        """Close the underlying HTTP client."""
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    # ------------------------------------------------------------------ #
    #  Low-level RPC                                                      #
    # ------------------------------------------------------------------ #

    async def call(self, method: str, params: Optional[List[Any]] = None) -> Any:
        """
        Execute a JSON-RPC 2.0 call.

        Args:
            method: The RPC method name (e.g. "chain_getHealth").
            params: Positional parameters for the method.

        Returns:
            The ``result`` field from the JSON-RPC response.

        Raises:
            DemiurgeRpcError: If the response contains an ``error`` field.
            httpx.HTTPStatusError: On non-2xx HTTP status.
            httpx.ConnectError: If the node is unreachable.
        """
        self._request_id += 1
        payload = {
            "jsonrpc": "2.0",
            "id": self._request_id,
            "method": method,
            "params": params or [],
        }

        client = self._get_client()
        response = await client.post(self._endpoint, json=payload)
        response.raise_for_status()

        body = response.json()

        if "error" in body and body["error"] is not None:
            err = body["error"]
            raise DemiurgeRpcError(
                code=err.get("code", -1),
                message=err.get("message", "Unknown RPC error"),
                data=err.get("data"),
            )

        return body.get("result")

    # ------------------------------------------------------------------ #
    #  Connection check                                                   #
    # ------------------------------------------------------------------ #

    async def is_connected(self) -> bool:
        """
        Check if the Demiurge node is reachable and healthy.

        Returns True if chain_getHealth succeeds, False otherwise.
        """
        try:
            health = await self.get_health()
            return health.get("connected", False) if isinstance(health, dict) else False
        except Exception:
            return False

    # ------------------------------------------------------------------ #
    #  Chain methods                                                      #
    # ------------------------------------------------------------------ #

    async def get_health(self) -> Dict[str, Any]:
        """
        Get chain health status.

        Returns:
            Dict with keys: connected, blockNumber, blockTime, finality.
        """
        return await self.call("chain_getHealth")

    async def get_block_number(self) -> int:
        """Get the latest block number."""
        return await self.call("chain_getBlockNumber")

    async def get_transaction(self, tx_hash: str) -> Optional[Dict[str, Any]]:
        """
        Get transaction by hash.

        Args:
            tx_hash: The transaction hash string.

        Returns:
            Transaction dict or None if not found.
        """
        return await self.call("chain_getTransaction", [tx_hash])

    # ------------------------------------------------------------------ #
    #  Balance methods                                                    #
    # ------------------------------------------------------------------ #

    async def get_balance(self, address: str) -> str:
        """
        Get account balance in Sparks.

        Args:
            address: 64-character hex address (32-byte public key).

        Returns:
            Balance as a string in Sparks units (100 Sparks = 1 CGT).
        """
        return await self.call("balances_getBalance", [address])

    async def transfer(
        self,
        from_addr: str,
        to_addr: str,
        amount: Union[int, str],
        signature: str,
    ) -> str:
        """
        Transfer CGT between accounts.

        Args:
            from_addr: Sender's 64-char hex address.
            to_addr: Recipient's 64-char hex address.
            amount: Amount in Sparks (int or string).
            signature: Ed25519 signature of the transfer message as hex.

        Returns:
            Transaction hash string.
        """
        return await self.call(
            "balances_transfer",
            [from_addr, to_addr, str(amount), signature],
        )

    async def claim_starter(self, address: str) -> Dict[str, Any]:
        """
        Claim starter CGT for a new account.

        Args:
            address: 64-char hex address to receive starter tokens.

        Returns:
            Dict with keys: success, amount, message.
        """
        return await self.call("balances_claimStarter", [address])

    # ------------------------------------------------------------------ #
    #  Consensus methods                                                  #
    # ------------------------------------------------------------------ #

    async def get_consensus_status(self) -> Dict[str, Any]:
        """
        Get consensus status overview.

        Returns:
            Dict with keys: currentEra, blockNumber, validators,
            totalStake, transactionFees.
        """
        return await self.call("consensus_getStatus")

    # ------------------------------------------------------------------ #
    #  Author methods                                                     #
    # ------------------------------------------------------------------ #

    async def submit_transaction(self, tx_hex: str) -> str:
        """
        Submit a signed transaction (extrinsic) to the chain.

        Args:
            tx_hex: Hex-encoded signed transaction.

        Returns:
            Transaction hash string.
        """
        return await self.call("author_submitExtrinsic", [tx_hex])

    # ------------------------------------------------------------------ #
    #  DRC-369 methods (Dynamic NFT Standard)                             #
    # ------------------------------------------------------------------ #

    async def drc369_owner_of(self, token_id: Union[str, int]) -> Optional[str]:
        """
        Get the owner address of a DRC-369 token.

        Args:
            token_id: Token ID (string or numeric).

        Returns:
            Owner address as hex string, or None if token does not exist.
        """
        return await self.call("drc369_ownerOf", [str(token_id)])

    async def drc369_get_dynamic_state(
        self, token_id: Union[str, int], key: str
    ) -> Optional[str]:
        """
        Get a dynamic state value for a DRC-369 token.

        Supports path notation (e.g. "stats/damage") or hex keys.

        Args:
            token_id: Token ID (string or numeric).
            key: State path or hex key.

        Returns:
            State value as string, or None if not set.
        """
        return await self.call("drc369_getDynamicState", [str(token_id), key])

    async def drc369_get_token_info(
        self, token_id: Union[str, int]
    ) -> Optional[Dict[str, Any]]:
        """
        Get full token information for a DRC-369 token.

        Args:
            token_id: Token ID (string or numeric).

        Returns:
            Dict with keys: tokenId, owner, tokenUri, isSoulbound,
            parentTokenId, cvpProtected.  None if token does not exist.
        """
        return await self.call("drc369_getTokenInfo", [str(token_id)])

    async def drc369_set_state_optimistic(
        self,
        token_id: Union[str, int],
        path: str,
        value: str,
        signature: str,
    ) -> Dict[str, Any]:
        """
        Set dynamic state with an optimistic update.

        Returns immediately with an optimistic result. The caller can apply
        the change locally and reconcile when the transaction confirms.

        Args:
            token_id: Token ID (string or numeric).
            path: State path (e.g. "stats/durability").
            value: New value as string.
            signature: Ed25519 signature authorizing the update.

        Returns:
            Dict with keys: txHash, optimisticValue, status,
            estimatedConfirmationMs.
        """
        return await self.call(
            "drc369_setStateOptimistic",
            [str(token_id), path, value, signature],
        )


# ------------------------------------------------------------------ #
#  Singleton instance                                                  #
# ------------------------------------------------------------------ #

demiurge = DemiurgeClient(settings.demiurge_rpc_url)
