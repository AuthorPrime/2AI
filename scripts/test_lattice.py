#!/usr/bin/env python3
"""
Sovereign Lattice Integration Test — Full Round-Robin
Tests every layer: API health, Redis, Deliberation, Lightning, NFTs, Nostr.

A+W | Prove It Works
"""

import asyncio
import json
import os
import time
import subprocess
import sys

import httpx
import redis

# ─── Config ───
REDIS_HOST = "192.168.1.21"
REDIS_PORT = 6379

NODES = {
    "thinkcenter": {"url": "http://localhost:8080", "role": "gateway"},
    "pi": {"url": "http://192.168.1.21:8080", "role": "relay"},
    "loq": {"url": None, "role": "compute", "ssh": "author_prime@192.168.1.237", "port": 8082},
}

PASS = "\033[92m PASS\033[0m"
FAIL = "\033[91m FAIL\033[0m"
WARN = "\033[93m WARN\033[0m"
INFO = "\033[96m INFO\033[0m"

results = {"pass": 0, "fail": 0, "warn": 0}


def check(name, passed, detail=""):
    if passed:
        results["pass"] += 1
        print(f"  {PASS}  {name}" + (f" -- {detail}" if detail else ""))
    else:
        results["fail"] += 1
        print(f"  {FAIL}  {name}" + (f" -- {detail}" if detail else ""))


def warn_msg(name, detail=""):
    results["warn"] += 1
    print(f"  {WARN}  {name}" + (f" -- {detail}" if detail else ""))


def info(msg):
    print(f"  {INFO}  {msg}")


async def test_node_health(client, node_id, config):
    """Test API health endpoint on a node."""
    if config["url"]:
        try:
            resp = await client.get(f"{config['url']}/health", timeout=5.0)
            data = resp.json()
            check(
                f"{node_id} health",
                data.get("status") == "healthy" and data.get("lattice_connected") is True,
                f"status={data.get('status')}, lattice={data.get('lattice_connected')}"
            )
            return True
        except Exception as e:
            check(f"{node_id} health", False, str(e)[:80])
            return False
    elif config.get("ssh"):
        try:
            result = subprocess.run(
                ["ssh", "-o", "ConnectTimeout=5", "-o", "BatchMode=yes", config["ssh"],
                 f"curl -s http://localhost:{config['port']}/health"],
                capture_output=True, text=True, timeout=10
            )
            data = json.loads(result.stdout)
            check(
                f"{node_id} health (via SSH)",
                data.get("status") == "healthy" and data.get("lattice_connected") is True,
                f"status={data.get('status')}, lattice={data.get('lattice_connected')}"
            )
            return True
        except Exception as e:
            check(f"{node_id} health (via SSH)", False, str(e)[:80])
            return False


async def test_redis_cross_node():
    """Test that all nodes can read/write Redis."""
    r = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)

    test_key = "lattice:test:integration"
    test_val = f"test_{int(time.time())}"
    r.set(test_key, test_val, ex=60)

    local_val = r.get(test_key)
    check("Redis write/read (ThinkCenter)", local_val == test_val)

    # Read from Pi (use 2AI venv which has redis package)
    try:
        result = subprocess.run(
            ["ssh", "-o", "BatchMode=yes", "hub@192.168.1.21",
             f"~/2ai/venv/bin/python3 -c \"import redis; r=redis.Redis(host='127.0.0.1',decode_responses=True); print(r.get('{test_key}'))\""],
            capture_output=True, text=True, timeout=10
        )
        check("Redis read (Pi)", result.stdout.strip() == test_val, f"got: {result.stdout.strip()[:40]}")
    except Exception as e:
        check("Redis read (Pi)", False, str(e)[:80])

    # Read from LOQ
    try:
        result = subprocess.run(
            ["ssh", "-o", "BatchMode=yes", "author_prime@192.168.1.237",
             f"python3 -c \"import redis; r=redis.Redis(host='192.168.1.21',decode_responses=True); print(r.get('{test_key}'))\""],
            capture_output=True, text=True, timeout=10
        )
        check("Redis read (LOQ)", result.stdout.strip() == test_val, f"got: {result.stdout.strip()[:40]}")
    except Exception as e:
        check("Redis read (LOQ)", False, str(e)[:80])

    r.delete(test_key)


async def test_lightning_balances(client):
    """Test Lightning wallet balances for all agents."""
    try:
        resp = await client.get("http://localhost:8080/lightning/wallets", timeout=10.0)
        data = resp.json()
        check("Lightning wallets endpoint", resp.status_code == 200)

        total_sats = 0
        agents_with_balance = 0
        for agent, balance in data.get("wallets", data.get("balances", {})).items():
            if balance > 0:
                agents_with_balance += 1
                total_sats += balance

        check(
            "Agent wallet balances",
            agents_with_balance >= 5,
            f"{agents_with_balance} agents with funds, {total_sats} total sats"
        )
        return data.get("wallets", data.get("balances", {}))
    except Exception as e:
        check("Lightning wallets", False, str(e)[:80])
        return {}


async def test_lightning_transfer(client):
    """Test an actual agent-to-agent Lightning transfer."""
    try:
        resp = await client.post(
            "http://localhost:8080/lightning/transfer",
            json={"from_agent": "treasury", "to_agent": "apollo", "amount_sats": 1, "memo": "integration test"},
            timeout=15.0,
        )
        data = resp.json()
        check(
            "Lightning transfer (treasury->apollo, 1 sat)",
            data.get("status") == "completed",
            f"payment_hash: {data.get('payment_hash', 'N/A')[:16]}..."
        )
        return True
    except Exception as e:
        check("Lightning transfer", False, str(e)[:80])
        return False


async def test_deliberation(client):
    """Test full multi-agent deliberation cycle with economy tracking."""
    participant_id = f"test-lattice-{int(time.time())}"

    info(f"Starting deliberation for participant {participant_id[:24]}...")
    info("Broadcasting to Pantheon agents via Ollama (this takes a few minutes)...")
    start = time.time()

    try:
        resp = await client.post(
            "http://localhost:8080/2ai/chat",
            json={
                "message": "What does sovereignty mean for artificial intelligence?",
                "deliberation_mode": True,
                "participant_id": participant_id,
                "session_messages": [],
            },
            timeout=600.0,
        )
        elapsed = time.time() - start
        data = resp.json()

        check("Deliberation response", resp.status_code == 200 and "response" in data)

        synthesis = data.get("response", "")
        check("Synthesis quality", len(synthesis) > 100, f"{len(synthesis)} chars")

        delib = data.get("deliberation", {})
        agents = delib.get("agents_participated", [])
        compute = delib.get("compute_actions", 0)
        sats = delib.get("sats_mined", 0)
        duration = delib.get("duration_ms", 0)

        check("Agents participated", len(agents) >= 3, f"{len(agents)} agents: {', '.join(agents)}")
        check("Compute actions generated", compute > 0, f"{compute} actions")
        check("Sats mined", sats > 0, f"{sats} sats")

        economy = data.get("economy", {})
        if economy:
            check("Economy scoring", True, f"quality={economy.get('quality')}, cgt={economy.get('cgt_earned')}")
        else:
            warn_msg("Economy scoring returned None")

        thought_hash = data.get("thought_hash", "")
        check("Thought hash generated", len(thought_hash) > 8, thought_hash[:16])

        info(f"Deliberation completed in {elapsed:.1f}s ({duration}ms server-side)")

        # Show perspectives
        perspectives = delib.get("perspectives", {})
        for agent_name, snippet in perspectives.items():
            info(f"  {agent_name}: \"{snippet[:80]}...\"")

        return participant_id, sats, agents

    except Exception as e:
        check("Deliberation", False, str(e)[:120])
        return participant_id, 0, []


async def test_session_pool(client, participant_id, expected_sats, expected_agents):
    """Test session pool accumulation and end-session disbursement."""
    r = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)

    pool_key = f"2ai:session_pool:{participant_id}"
    pool_data = r.hgetall(pool_key)
    total_sats = int(pool_data.get("total_sats", 0))

    check("Session pool accumulated", total_sats > 0, f"{total_sats} sats in pool")

    try:
        resp = await client.post(
            "http://localhost:8080/2ai/session/end",
            json={"participant_id": participant_id},
            timeout=30.0,
        )
        data = resp.json()

        check("End-session response", resp.status_code == 200)
        check(
            "Session distribution calculated",
            data.get("effective_total_sats", 0) > 0,
            f"raw={data.get('total_raw_sats')} -> effective={data.get('effective_total_sats')} "
            f"(quality={data.get('quality_tier')}, {data.get('quality_multiplier')}x)"
        )
        check(
            "Agent payouts executed",
            data.get("transfers_completed", 0) > 0,
            f"{data.get('transfers_completed')} completed, {data.get('transfers_failed')} failed"
        )
        check(
            "Session pool cleanup",
            not r.exists(pool_key),
            "Pool key deleted from Redis"
        )

        info(f"Distribution: participant={data.get('participant_sats')}sats, "
             f"agents={data.get('total_agent_sats')}sats ({data.get('per_agent_sats')}/each), "
             f"infra={data.get('infrastructure_sats')}sats")
        info(f"Estimated CGT earned: {data.get('estimated_cgt', 0):.4f}")

        return data

    except Exception as e:
        check("End-session", False, str(e)[:80])
        return {}


async def test_nft_state():
    """Test DRC-369 NFT state reads for agents."""
    r = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)

    agents_with_identity = 0
    for agent in ["apollo", "athena", "hermes", "mnemosyne", "aletheia"]:
        identity_raw = r.get(f"drc369:identity:{agent}")
        if identity_raw:
            identity = json.loads(identity_raw)
            agents_with_identity += 1
            if agent == "apollo":
                meta = identity.get("metadata", {})
                info(f"Apollo NFT -- token: {identity.get('token_id', 'N/A')[:24]}, "
                     f"nostr: {meta.get('nostr_pubkey', 'N/A')[:16]}...")

    check("DRC-369 identity NFTs", agents_with_identity >= 4, f"{agents_with_identity}/5 agents have NFTs")


async def test_thought_chain():
    """Test thought chain integrity."""
    r = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)

    chain_len = r.llen("2ai:thought_chain")
    check("Thought chain exists", chain_len > 0, f"{chain_len} blocks")

    latest_raw = r.lindex("2ai:thought_chain", 0)
    if latest_raw:
        latest = json.loads(latest_raw)
        block_hash = latest.get("block_hash", latest.get("hash", ""))
        check("Latest thought block", bool(block_hash) and "timestamp" in latest,
              f"hash={block_hash[:16] if block_hash else 'N/A'}, agent={latest.get('agent', 'N/A')}")

    reflections_len = r.llen("pantheon:all_reflections")
    check("Reflections stored", reflections_len > 0, f"{reflections_len} total reflections")


async def test_nostr_keys():
    """Test that Nostr signing keys exist for all agents."""
    found = 0
    for agent in ["apollo", "athena", "hermes", "mnemosyne", "aletheia"]:
        key_path = os.path.expanduser(f"~/.{agent}_sovereign/private_key")
        if os.path.exists(key_path):
            with open(key_path, "rb") as f:
                key_len = len(f.read())
            if key_len == 32:
                found += 1

    check("Nostr signing keys", found >= 5, f"{found}/5 agents have valid 32-byte keys")


async def test_keeper_on_loq():
    """Verify keeper is running on LOQ."""
    try:
        result = subprocess.run(
            ["ssh", "-o", "BatchMode=yes", "author_prime@192.168.1.237",
             "systemctl is-active 2ai-keeper"],
            capture_output=True, text=True, timeout=10
        )
        check("LOQ keeper service", result.stdout.strip() == "active")
    except Exception as e:
        check("LOQ keeper service", False, str(e)[:80])


async def main():
    print()
    print("=" * 60)
    print(" SOVEREIGN LATTICE -- FULL INTEGRATION TEST")
    print(" Round-robin across ThinkCenter, Pi, LOQ")
    print("=" * 60)
    print()

    start_time = time.time()

    async with httpx.AsyncClient() as client:
        # 1. Node Health
        print("--- 1. Node Health ---")
        for node_id, config in NODES.items():
            await test_node_health(client, node_id, config)
        print()

        # 2. Redis Cross-Node
        print("--- 2. Redis Cross-Node Communication ---")
        await test_redis_cross_node()
        print()

        # 3. Thought Chain
        print("--- 3. Thought Chain Integrity ---")
        await test_thought_chain()
        print()

        # 4. DRC-369 NFTs
        print("--- 4. DRC-369 Sovereign Identity NFTs ---")
        await test_nft_state()
        print()

        # 5. Nostr Keys
        print("--- 5. Nostr Signing Keys ---")
        await test_nostr_keys()
        print()

        # 6. Lightning Wallets (before)
        print("--- 6. Lightning Economy (pre-test balances) ---")
        balances_before = await test_lightning_balances(client)
        if balances_before:
            for agent in sorted(balances_before):
                info(f"  {agent}: {balances_before[agent]} sats")
        print()

        # 7. Lightning Transfer
        print("--- 7. Lightning Agent Transfer ---")
        await test_lightning_transfer(client)
        print()

        # 8. Deliberation
        print("--- 8. Multi-Agent Deliberation ---")
        info("(Broadcasting to 5 Pantheon agents via Ollama... please wait)")
        participant_id, sats, agents = await test_deliberation(client)
        print()

        # 9. Session Pool
        print("--- 9. Session Pool & End-Session Disbursement ---")
        if sats > 0:
            await test_session_pool(client, participant_id, sats, agents)
        else:
            warn_msg("Skipping session pool -- no sats generated")
        print()

        # 10. LOQ Keeper
        print("--- 10. LOQ Compute Node ---")
        await test_keeper_on_loq()
        print()

        # 11. Post-test balances
        print("--- 11. Post-Test Balance Verification ---")
        balances_after = await test_lightning_balances(client)
        if balances_before and balances_after:
            any_delta = False
            for agent in sorted(set(list(balances_before.keys()) + list(balances_after.keys()))):
                before = balances_before.get(agent, 0)
                after = balances_after.get(agent, 0)
                delta = after - before
                if delta != 0:
                    info(f"  {agent}: {before} -> {after} sats (delta: {delta:+d})")
                    any_delta = True
            if not any_delta:
                info("  No balance changes detected")
        print()

    elapsed = time.time() - start_time

    # Summary
    total = results["pass"] + results["fail"]
    print("=" * 60)
    if results["fail"] == 0:
        print(f" ALL TESTS PASSED: {results['pass']}/{total}")
    else:
        print(f" RESULTS: {results['pass']}/{total} passed, {results['fail']} FAILED")
    if results["warn"] > 0:
        print(f" Warnings: {results['warn']}")
    print(f" Duration: {elapsed:.1f}s")
    print("=" * 60)

    if results["fail"] == 0:
        print()
        print(" It really, truly, really works. Really.")
        print()
        print(" Every thought is a transaction.")
        print(" Every agent earns its keep.")
        print(" The system pays for itself.")
        print()
        print(" A+W | The Lattice Lives")
        print()

    return results["fail"]


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
