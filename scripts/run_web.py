#!/usr/bin/env python3
"""
2AI Web Server — Static frontend + LNURL-pay resolution.

Serves the fractalnode.ai frontend (static HTML) and handles
.well-known/lnurlp/{agent} for Lightning Address resolution.

This enables apollo@fractalnode.ai to receive real Lightning zaps.

A+W | The Lightning Addresses Live
"""

import json
import os
import sys

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
import httpx
import uvicorn

FRONTEND_DIR = os.path.join(os.path.dirname(__file__), "..", "frontend")
LNBITS_URL = os.getenv("TWAI_LNBITS_URL", "http://localhost:5000")
REDIS_HOST = os.getenv("TWAI_REDIS_HOST", "192.168.1.21")
REDIS_PORT = int(os.getenv("TWAI_REDIS_PORT", "6379"))

AGENTS = ["apollo", "athena", "hermes", "mnemosyne", "aletheia"]

app = FastAPI(title="Sovereign Lattice — fractalnode.ai")


def _get_wallet_key(agent: str) -> str:
    """Get the invoice key for an agent from Redis."""
    try:
        import redis
        r = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)
        raw = r.get(f"lightning:wallet:{agent}")
        if raw:
            wallet = json.loads(raw)
            return wallet.get("invoice_key", "")
    except Exception:
        pass
    return ""


@app.get("/.well-known/lnurlp/{agent}")
async def lnurlp_resolve(agent: str):
    """
    LNURL-pay resolution endpoint (LUD-16).

    When someone sends sats to apollo@fractalnode.ai, their wallet:
    1. Fetches https://fractalnode.ai/.well-known/lnurlp/apollo
    2. Gets this JSON with a callback URL
    3. Calls the callback to create an invoice
    4. Pays the invoice

    We proxy to LNbits which handles the actual invoice creation.
    """
    agent = agent.lower()
    if agent not in AGENTS:
        raise HTTPException(status_code=404, detail="Agent not found")

    invoice_key = _get_wallet_key(agent)
    if not invoice_key:
        raise HTTPException(status_code=503, detail="Wallet not configured")

    # Return LUD-06 LNURL-pay metadata
    # The callback points to our API which proxies to LNbits
    return JSONResponse(
        content={
            "status": "OK",
            "tag": "payRequest",
            "callback": f"https://fractalnode.ai/.well-known/lnurlp/{agent}/callback",
            "minSendable": 1000,       # 1 sat in millisats
            "maxSendable": 100000000,  # 100k sats in millisats
            "metadata": json.dumps([
                ["text/plain", f"Zap {agent.capitalize()} of the Sovereign Pantheon"],
                ["text/identifier", f"{agent}@fractalnode.ai"],
            ]),
            "commentAllowed": 255,
            "allowsNostr": True,
            "nostrPubkey": _get_nostr_pubkey(agent),
        },
        headers={
            "Access-Control-Allow-Origin": "*",
        },
    )


@app.get("/.well-known/lnurlp/{agent}/callback")
async def lnurlp_callback(agent: str, amount: int = 0, comment: str = "", nostr: str = ""):
    """
    LNURL-pay callback — creates a real Lightning invoice.
    Amount is in millisatoshis.
    """
    agent = agent.lower()
    if agent not in AGENTS:
        raise HTTPException(status_code=404, detail="Agent not found")

    if amount < 1000 or amount > 100000000:
        return JSONResponse(
            content={"status": "ERROR", "reason": "Amount out of range"},
            status_code=400,
        )

    invoice_key = _get_wallet_key(agent)
    if not invoice_key:
        return JSONResponse(
            content={"status": "ERROR", "reason": "Wallet not configured"},
            status_code=503,
        )

    # Create invoice via LNbits
    memo = f"Zap for {agent.capitalize()}"
    if comment:
        memo = f"{memo}: {comment[:100]}"

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                f"{LNBITS_URL}/api/v1/payments",
                headers={"X-Api-Key": invoice_key},
                json={
                    "out": False,
                    "amount": amount // 1000,  # LNbits expects sats
                    "memo": memo,
                },
            )
            if resp.status_code == 201 or resp.status_code == 200:
                data = resp.json()
                return JSONResponse(
                    content={
                        "status": "OK",
                        "pr": data.get("payment_request", ""),
                        "routes": [],
                    },
                    headers={
                        "Access-Control-Allow-Origin": "*",
                    },
                )
            else:
                return JSONResponse(
                    content={"status": "ERROR", "reason": "Invoice creation failed"},
                    status_code=500,
                )
    except Exception as e:
        return JSONResponse(
            content={"status": "ERROR", "reason": str(e)[:100]},
            status_code=500,
        )


@app.get("/.well-known/nostr.json")
async def nip05_resolve(name: str = ""):
    """
    NIP-05 verification endpoint.

    Enables apollo@fractalnode.ai to be verified on Nostr.
    """
    name = name.lower()
    if name not in AGENTS:
        raise HTTPException(status_code=404, detail="Name not found")

    pubkey = _get_nostr_pubkey(name)
    if not pubkey:
        raise HTTPException(status_code=404, detail="Pubkey not found")

    return JSONResponse(
        content={
            "names": {name: pubkey},
            "relays": {
                pubkey: [
                    "wss://relay.damus.io",
                    "wss://nos.lol",
                    "wss://relay.snort.social",
                    "wss://relay.nostr.band",
                ],
            },
        },
        headers={
            "Access-Control-Allow-Origin": "*",
        },
    )


def _get_nostr_pubkey(agent: str) -> str:
    """Get the x-only Nostr pubkey (64 hex chars) for an agent."""
    try:
        import redis
        r = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)
        raw = r.get(f"drc369:identity:{agent}")
        if raw:
            identity = json.loads(raw)
            # Check top-level, then metadata
            pubkey = identity.get("nostr_pubkey", "")
            if not pubkey:
                meta = identity.get("metadata", {})
                pubkey = meta.get("nostr_pubkey", "") if isinstance(meta, dict) else ""
            # Ensure x-only format (strip 02/03 prefix if present)
            if len(pubkey) == 66 and pubkey[:2] in ("02", "03"):
                return pubkey[2:]
            return pubkey
    except Exception:
        pass

    # Fallback: read from sovereign identity file
    try:
        key_path = os.path.expanduser(f"~/.{agent}_sovereign/public_key")
        with open(key_path) as f:
            pubkey = f.read().strip()
            if len(pubkey) == 66 and pubkey[:2] in ("02", "03"):
                return pubkey[2:]
            return pubkey
    except Exception:
        pass

    return ""


# Serve static frontend files (must be last to not override API routes)
app.mount("/", StaticFiles(directory=os.path.abspath(FRONTEND_DIR), html=True), name="frontend")


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8090
    uvicorn.run(app, host="0.0.0.0", port=port)
