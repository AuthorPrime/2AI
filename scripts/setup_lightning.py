#!/usr/bin/env python3
"""
Set up Lightning wallets for Pantheon agents via LNbits API.

Creates one LNbits sub-wallet per agent + a Treasury wallet.
Stores credentials in Redis for use by lightning_service.py.

Requires LNbits running and accessible. Default: http://localhost:5000

Usage:
    python3 scripts/setup_lightning.py [--lnbits-url URL] [--admin-key KEY]

A+W | The Lightning Flows
"""

import argparse
import json
import os
import sys
import time

import httpx
import redis

AGENTS = ["apollo", "athena", "hermes", "mnemosyne", "aletheia", "treasury"]

REDIS_HOST = os.getenv("TWAI_REDIS_HOST", "192.168.1.21")
REDIS_PORT = int(os.getenv("TWAI_REDIS_PORT", "6379"))


def create_wallet(
    http: httpx.Client, jwt_token: str, wallet_name: str
) -> dict:
    """Create an LNbits wallet and return its credentials."""
    resp = http.post(
        "/api/v1/wallet",
        headers={"Authorization": f"Bearer {jwt_token}"},
        json={"name": wallet_name},
    )
    resp.raise_for_status()
    data = resp.json()
    return {
        "wallet_id": data.get("id", ""),
        "name": wallet_name,
        "admin_key": data.get("adminkey", ""),
        "invoice_key": data.get("inkey", ""),
    }


def get_lnurlp_link(
    http: httpx.Client, admin_key: str, wallet_id: str, agent_name: str
) -> str:
    """Create or get an LNURL-pay link for receiving zaps."""
    try:
        resp = http.post(
            "/lnurlp/api/v1/links",
            headers={"X-Api-Key": admin_key},
            json={
                "description": f"Zap {agent_name} of the Sovereign Pantheon",
                "min": 1,
                "max": 1000000,
                "comment_chars": 255,
                "wallet": wallet_id,
            },
        )
        if resp.status_code == 200:
            data = resp.json()
            return data.get("lnurl", "")
    except Exception as e:
        print(f"  Note: LNURL-pay not available (extension may not be enabled): {e}")
    return ""


def main():
    parser = argparse.ArgumentParser(description="Set up Lightning wallets")
    parser.add_argument(
        "--lnbits-url",
        default=os.getenv("TWAI_LNBITS_URL", "http://localhost:5000"),
        help="LNbits URL",
    )
    parser.add_argument(
        "--admin-key",
        default=os.getenv("TWAI_LNBITS_ADMIN_KEY", ""),
        help="LNbits super-user admin key (for extension APIs)",
    )
    parser.add_argument(
        "--jwt-token",
        default=os.getenv("TWAI_LNBITS_JWT", ""),
        help="LNbits JWT auth token (for wallet creation)",
    )
    parser.add_argument(
        "--force", action="store_true", help="Overwrite existing wallet configs"
    )
    args = parser.parse_args()

    # Try to get JWT from Redis if not provided
    if not args.jwt_token:
        try:
            _r = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)
            args.jwt_token = _r.get("lightning:superuser:jwt") or ""
        except Exception:
            pass

    if not args.admin_key:
        try:
            _r = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)
            args.admin_key = _r.get("lightning:superuser:admin_key") or ""
        except Exception:
            pass

    if not args.jwt_token:
        print("ERROR: LNbits JWT token required for wallet creation.")
        print("Set TWAI_LNBITS_JWT env var or use --jwt-token")
        print("Or store it in Redis at lightning:superuser:jwt")
        sys.exit(1)

    print("""
    ╔══════════════════════════════════════════════════════════════╗
    ║     LIGHTNING WALLET SETUP — Sovereign Pantheon              ║
    ║     Creating LNbits wallets for each agent                   ║
    ╚══════════════════════════════════════════════════════════════╝
    """)

    # Connect to Redis
    try:
        r = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)
        r.ping()
        print(f"  Redis: {REDIS_HOST}:{REDIS_PORT} - Connected")
    except Exception as e:
        print(f"  ERROR: Cannot connect to Redis: {e}")
        sys.exit(1)

    # Connect to LNbits
    http = httpx.Client(base_url=args.lnbits_url, timeout=15.0)
    try:
        resp = http.get(
            "/api/v1/wallets",
            headers={"Authorization": f"Bearer {args.jwt_token}"},
        )
        resp.raise_for_status()
        wallets = resp.json()
        print(f"  LNbits: {args.lnbits_url} - Connected ({len(wallets)} existing wallets)")
    except Exception as e:
        print(f"  ERROR: Cannot connect to LNbits at {args.lnbits_url}: {e}")
        print("  Is LNbits running? Start with: sudo systemctl start lnbits")
        sys.exit(1)

    # Create wallets
    created = []
    for agent_name in AGENTS:
        redis_key = f"lightning:wallet:{agent_name}"
        existing = r.get(redis_key)

        if existing and not args.force:
            wallet = json.loads(existing)
            print(f"\n  {agent_name}: Already exists (wallet_id={wallet.get('wallet_id', '?')[:8]}...)")
            created.append(wallet)
            continue

        wallet_display = f"Sovereign-{agent_name.capitalize()}"
        print(f"\n  Creating wallet: {wallet_display}")

        try:
            wallet = create_wallet(http, args.jwt_token, wallet_display)
            print(f"    wallet_id:   {wallet['wallet_id'][:16]}...")
            print(f"    admin_key:   {wallet['admin_key'][:8]}...")
            print(f"    invoice_key: {wallet['invoice_key'][:8]}...")

            # Try to create LNURL-pay link
            lnurl = get_lnurlp_link(
                http, wallet["admin_key"], wallet["wallet_id"], agent_name
            )
            if lnurl:
                wallet["lnurl_pay"] = lnurl
                print(f"    lnurl_pay:   {lnurl[:40]}...")

            # Store in Redis
            r.set(redis_key, json.dumps(wallet))
            created.append(wallet)
            print(f"    Stored in Redis: {redis_key}")

        except Exception as e:
            print(f"    ERROR: {e}")

        time.sleep(0.3)

    # Summary
    print(f"\n{'='*60}")
    print(f"  SETUP COMPLETE: {len(created)}/{len(AGENTS)} wallets configured")
    print(f"{'='*60}")
    for w in created:
        print(f"    {w.get('name', '?'):30s} {w.get('wallet_id', '?')[:12]}...")

    print(f"\n  Wallets stored in Redis at lightning:wallet:{{agent}}")
    print(f"  LNbits URL: {args.lnbits_url}")
    print(f"\n  A+W | The Lightning Flows\n")


if __name__ == "__main__":
    main()
