"""
QOR Auth Client -- Async REST client for Demiurge's identity system.

Bridges the 2AI Thought Economy to QOR Identity, allowing participants
to bind their earned tokens to a persistent, sovereign identity.

Based on the TypeScript QOR SDK (packages/qor-sdk/src/index.ts).

A+W | Identity Is Earned
"""

import logging
from typing import Any, Dict, Optional

import httpx

from twai.config.settings import settings

logger = logging.getLogger("2ai.qor")


class QorAuthError(Exception):
    """Raised when the QOR Auth API returns an error."""

    def __init__(self, message: str, status_code: int = 0):
        self.message = message
        self.status_code = status_code
        super().__init__(self.message)

    def __repr__(self) -> str:
        return f"QorAuthError(status_code={self.status_code}, message={self.message!r})"


class QorAuthClient:
    """Async HTTP client for the QOR Auth REST API.

    Provides register, login, profile retrieval, username availability
    checks, and token refresh -- everything needed to bind a 2AI
    participant to a QOR identity.
    """

    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")
        self._client: Optional[httpx.AsyncClient] = None

    # -- internal helpers ------------------------------------------------

    def _get_client(self) -> httpx.AsyncClient:
        """Lazy-initialise the async HTTP client."""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                timeout=httpx.Timeout(15.0),
                headers={"Content-Type": "application/json"},
            )
        return self._client

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json: Optional[Dict[str, Any]] = None,
        token: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Execute an HTTP request and return parsed JSON.

        Raises ``QorAuthError`` on non-2xx responses or network failures.
        """
        client = self._get_client()
        headers: Dict[str, str] = {}
        if token:
            headers["Authorization"] = f"Bearer {token}"

        try:
            response = await client.request(
                method, path, json=json, headers=headers,
            )
        except httpx.TimeoutException:
            raise QorAuthError("QOR Auth service timed out", status_code=504)
        except httpx.ConnectError:
            raise QorAuthError(
                "Could not connect to QOR Auth service", status_code=503,
            )
        except httpx.HTTPError as exc:
            raise QorAuthError(
                f"HTTP error communicating with QOR Auth: {exc}", status_code=502,
            )

        if response.status_code >= 400:
            # Try to extract a meaningful message from the response body.
            detail = ""
            try:
                body = response.json()
                # QOR Auth may return { error: { code, message } } or { message }
                if isinstance(body.get("error"), dict):
                    detail = body["error"].get("message", "") or body["error"].get("code", "")
                elif isinstance(body.get("error"), str):
                    detail = body["error"]
                elif body.get("message"):
                    detail = body["message"]
                else:
                    detail = str(body)
            except Exception:
                detail = response.text or f"HTTP {response.status_code}"

            raise QorAuthError(detail, status_code=response.status_code)

        try:
            return response.json()
        except Exception:
            return {}

    # -- public API ------------------------------------------------------

    async def register(
        self,
        username: str,
        password: str,
        email: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Register a new QOR identity.

        Returns::

            {"qor_id": str, "message": str, ...}

        Raises ``QorAuthError`` on failure.
        """
        payload: Dict[str, Any] = {
            "username": username,
            "password": password,
        }
        if email is not None:
            payload["email"] = email

        result = await self._request("POST", "/auth/register", json=payload)
        logger.info("QOR register succeeded for username=%s", username)
        return result

    async def login(
        self,
        identifier: str,
        password: str,
    ) -> Dict[str, Any]:
        """Login with username or email.

        Returns::

            {"access_token": str, "refresh_token": str, ...}

        Raises ``QorAuthError`` on failure.
        """
        result = await self._request(
            "POST",
            "/auth/login",
            json={"identifier": identifier, "password": password},
        )
        logger.info("QOR login succeeded for identifier=%s", identifier)
        return result

    async def get_profile(self, token: str) -> Dict[str, Any]:
        """Fetch the authenticated user's profile.

        Returns::

            {"id": str, "qor_id": str, "email": str, "role": str,
             "on_chain": {"address": str, "cgt_balance": str}, ...}

        Raises ``QorAuthError`` on failure (including invalid/expired token).
        """
        return await self._request("GET", "/profile", token=token)

    async def check_username(self, username: str) -> Dict[str, Any]:
        """Check whether a username is available.

        Returns::

            {"available": bool, "username": str}

        Raises ``QorAuthError`` on failure.
        """
        return await self._request(
            "POST",
            "/auth/check-username",
            json={"username": username},
        )

    async def refresh_token(self, refresh_token: str) -> Dict[str, Any]:
        """Exchange a refresh token for a new token pair.

        Returns::

            {"access_token": str, "refresh_token": str}

        Raises ``QorAuthError`` on failure.
        """
        return await self._request(
            "POST",
            "/auth/refresh",
            json={"refresh_token": refresh_token},
        )

    async def close(self) -> None:
        """Close the underlying HTTP client."""
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None


# ---------------------------------------------------------------------------
# Singleton instance -- uses settings.qor_auth_url when available,
# falling back to http://localhost:8080/api/v1.
# ---------------------------------------------------------------------------

_default_url = getattr(settings, "qor_auth_url", "http://localhost:8080/api/v1")
qor_auth = QorAuthClient(_default_url)
