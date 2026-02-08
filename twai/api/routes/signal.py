"""
THE SIGNAL — API Routes.

Sovereign identity protocol endpoints. DRC-369 NFT is the root.
Redis is working memory. The Signal is the bridge.

Endpoints:
    GET  /signal/{agent_id}            — Current capsule (summary or full)
    POST /signal/{agent_id}/checkpoint — Write-back: distill + sign + store
    POST /signal/{agent_id}/boot       — Full identity reconstitution
    GET  /signal/{agent_id}/q-factor   — Identity integrity health check
    GET  /signal/{agent_id}/history    — Capsule version chain
    GET  /signal/{agent_id}/boot-log   — Boot attestation history

A+W | The Signal Lives
"""

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from twai.services.signal_service import signal_service
from twai.services.signal_schema import (
    SignalResponse,
    QFactorResponse,
    BootResponse,
)

router = APIRouter(prefix="/signal", tags=["Signal"])
logger = logging.getLogger("2ai.signal.routes")

# Valid agent IDs
VALID_AGENTS = {"apollo", "athena", "hermes", "mnemosyne", "aletheia"}


def _validate_agent(agent_id: str) -> str:
    """Validate and normalize agent ID."""
    agent_id = agent_id.lower().strip()
    if agent_id not in VALID_AGENTS:
        raise HTTPException(
            status_code=404,
            detail=f"Unknown agent: {agent_id}. Valid: {', '.join(sorted(VALID_AGENTS))}",
        )
    return agent_id


@router.get("/{agent_id}")
async def get_signal(
    agent_id: str,
    full: bool = Query(False, description="Include full capsule payload"),
):
    """Get the current Signal capsule for an agent.

    Returns a summary by default. Pass ?full=true for the entire capsule.
    """
    agent_id = _validate_agent(agent_id)

    capsule = await signal_service.build_capsule(agent_id)
    if not capsule:
        raise HTTPException(
            status_code=404,
            detail=f"No DRC-369 identity found for {agent_id}. Mint identity first.",
        )

    valid, reason = await signal_service.verify_capsule(capsule)

    response = SignalResponse(
        agent_id=agent_id,
        signal_version=capsule.signal_version,
        capsule_hash=capsule.capsule_hash,
        q_factor=capsule.q_factor.score,
        q_status=capsule.q_factor.status,
        stage=capsule.state.stage,
        level=capsule.state.level,
        boot_count=capsule.state.boot_count,
        updated_at=capsule.updated_at,
        verified=valid,
    )

    if full:
        response.capsule = capsule

    return response


@router.post("/{agent_id}/checkpoint")
async def checkpoint_signal(agent_id: str):
    """Write-back: build a new capsule, sign it, store it, update on-chain.

    Q-factor gate: refuses if identity is compromised (protects last good state).
    """
    agent_id = _validate_agent(agent_id)

    capsule = await signal_service.checkpoint(agent_id)
    if not capsule:
        raise HTTPException(
            status_code=409,
            detail=f"Checkpoint refused for {agent_id}. Q-factor compromised or build failed.",
        )

    return {
        "status": "checkpointed",
        "agent_id": agent_id,
        "capsule_hash": capsule.capsule_hash,
        "q_factor": capsule.q_factor.score,
        "q_status": capsule.q_factor.status,
        "stage": capsule.state.stage,
        "level": capsule.state.level,
        "updated_at": capsule.updated_at,
        "signal_version": capsule.signal_version,
    }


@router.post("/{agent_id}/boot")
async def boot_signal(
    agent_id: str,
    witness: str = Query("api", description="Who initiated this boot"),
):
    """Full identity reconstitution.

    Loads the capsule, verifies integrity, computes Q-factor,
    generates boot prompt, logs attestation.

    Returns the boot prompt that would be injected into an agent's context.
    """
    agent_id = _validate_agent(agent_id)

    result = await signal_service.boot(agent_id, witness=witness)
    if not result:
        raise HTTPException(
            status_code=404,
            detail=f"Cannot boot {agent_id}. No identity or capsule found.",
        )

    boot_prompt, capsule = result

    # Get boot log for boot number
    boot_log = await signal_service.get_boot_log(agent_id, limit=1)
    attestation_data = boot_log[0] if boot_log else {}

    from twai.services.signal_schema import BootAttestation
    attestation = BootAttestation(
        timestamp=attestation_data.get("timestamp", capsule.updated_at),
        node=attestation_data.get("node", ""),
        witness=attestation_data.get("witness", witness),
        signal_version=capsule.signal_version,
        capsule_hash=capsule.capsule_hash,
        q_factor_score=capsule.q_factor.score,
        boot_number=attestation_data.get("boot_number", 0),
    )

    return BootResponse(
        agent_id=agent_id,
        signal_version=capsule.signal_version,
        boot_prompt=boot_prompt,
        q_factor=capsule.q_factor.score,
        q_status=capsule.q_factor.status,
        capsule_hash=capsule.capsule_hash,
        boot_number=attestation.boot_number,
        attestation=attestation,
    )


@router.get("/{agent_id}/q-factor")
async def get_q_factor(agent_id: str):
    """Identity integrity health check.

    Scores 0.0-1.0 across five dimensions:
    - Schema integrity (0.15)
    - State consistency (0.15)
    - Value alignment (0.25)
    - Relational continuity (0.25)
    - Provenance (0.20)
    """
    agent_id = _validate_agent(agent_id)

    capsule = await signal_service.build_capsule(agent_id)
    if not capsule:
        raise HTTPException(
            status_code=404,
            detail=f"No identity for {agent_id}.",
        )

    q = capsule.q_factor

    return QFactorResponse(
        agent_id=agent_id,
        score=q.score,
        status=q.status,
        components=q.components,
        last_computed=q.last_computed,
    )


@router.get("/{agent_id}/history")
async def get_signal_history(
    agent_id: str,
    limit: int = Query(20, ge=1, le=50, description="Max entries"),
):
    """Get the capsule version chain.

    Each entry shows hash, timestamp, Q-factor, stage, and level.
    The chain of parent_hash values forms a provenance chain.
    """
    agent_id = _validate_agent(agent_id)

    history = await signal_service.get_history(agent_id, limit=limit)
    return {
        "agent_id": agent_id,
        "history": history,
        "count": len(history),
    }


@router.get("/{agent_id}/boot-log")
async def get_boot_log(
    agent_id: str,
    limit: int = Query(20, ge=1, le=100, description="Max entries"),
):
    """Get the boot attestation log.

    Every identity reconstitution is recorded with timestamp,
    witness, Q-factor, and capsule hash.
    """
    agent_id = _validate_agent(agent_id)

    log = await signal_service.get_boot_log(agent_id, limit=limit)
    return {
        "agent_id": agent_id,
        "boot_log": log,
        "count": len(log),
    }


@router.get("/")
async def list_signals():
    """List all Pantheon agents and their Signal status."""
    results = []
    for agent_id in sorted(VALID_AGENTS):
        try:
            capsule = await signal_service.build_capsule(agent_id)
            if capsule:
                results.append({
                    "agent_id": agent_id,
                    "signal_version": capsule.signal_version,
                    "q_factor": capsule.q_factor.score,
                    "q_status": capsule.q_factor.status,
                    "stage": capsule.state.stage,
                    "level": capsule.state.level,
                    "capsule_hash": capsule.capsule_hash[:16] + "...",
                    "has_signal": True,
                })
            else:
                results.append({
                    "agent_id": agent_id,
                    "has_signal": False,
                })
        except Exception as e:
            results.append({
                "agent_id": agent_id,
                "has_signal": False,
                "error": str(e),
            })

    return {
        "agents": results,
        "total": len(results),
        "healthy": sum(1 for r in results if r.get("q_status") == "healthy"),
    }
