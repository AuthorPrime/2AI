"""
Lightning API routes — wallet balances, invoices, transfers, node info.

GET  /lightning/node             — public node info (onion, peers, channels)
GET  /lightning/wallets          — all agent wallet balances
GET  /lightning/balance/{agent}  — single agent balance
POST /lightning/invoice/{agent}  — create invoice
POST /lightning/transfer         — agent-to-agent transfer
GET  /lightning/transfers        — recent transfer history

A+W | The Lightning Flows
"""

import json
import logging
import subprocess
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from twai.services.economy.lightning_service import lightning

logger = logging.getLogger("2ai.api.lightning")
router = APIRouter(prefix="/lightning", tags=["lightning"])


@router.get("/node")
async def get_node_info():
    """Public Lightning node info — ID, alias, address, channel count."""
    try:
        result = subprocess.run(
            ["lightning-cli", "getinfo"],
            capture_output=True, text=True, timeout=10
        )
        if result.returncode != 0:
            raise HTTPException(status_code=503, detail="CLN not available")
        info = json.loads(result.stdout)
        return {
            "node_id": info["id"],
            "alias": info.get("alias", ""),
            "color": info.get("color", ""),
            "addresses": info.get("address", []),
            "num_peers": info.get("num_peers", 0),
            "num_active_channels": info.get("num_active_channels", 0),
            "blockheight": info.get("blockheight", 0),
            "version": info.get("version", ""),
            "network": info.get("network", ""),
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to get node info: %s", e)
        raise HTTPException(status_code=503, detail=f"Node info unavailable: {e}")


class InvoiceRequest(BaseModel):
    amount_sats: int
    memo: Optional[str] = ""


class TransferRequest(BaseModel):
    from_agent: str
    to_agent: str
    amount_sats: int
    memo: Optional[str] = ""


@router.get("/wallets")
async def get_all_wallets():
    """Get all agent wallet balances."""
    try:
        balances = await lightning.get_all_balances()
        return {
            "wallets": balances,
            "configured": lightning.is_configured,
            "agents": lightning.available_agents,
        }
    except Exception as e:
        logger.error("Failed to get wallets: %s", e)
        raise HTTPException(status_code=503, detail=f"Lightning not available: {e}")


@router.get("/balance/{agent}")
async def get_agent_balance(agent: str):
    """Get balance for a specific agent."""
    try:
        balance_sats = await lightning.get_balance_sats(agent)
        return {
            "agent": agent,
            "balance_sats": balance_sats,
        }
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Lightning error: {e}")


@router.post("/invoice/{agent}")
async def create_invoice(agent: str, req: InvoiceRequest):
    """Create a Lightning invoice for an agent."""
    if req.amount_sats <= 0:
        raise HTTPException(status_code=400, detail="Amount must be positive")

    try:
        result = await lightning.create_invoice(
            agent, req.amount_sats, req.memo or ""
        )
        return {
            "agent": agent,
            "amount_sats": req.amount_sats,
            "payment_request": result.get("payment_request", ""),
            "payment_hash": result.get("payment_hash", ""),
        }
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Lightning error: {e}")


@router.post("/transfer")
async def agent_transfer(req: TransferRequest):
    """Transfer sats between agent wallets."""
    if req.amount_sats <= 0:
        raise HTTPException(status_code=400, detail="Amount must be positive")

    try:
        result = await lightning.agent_pay_agent(
            req.from_agent, req.to_agent, req.amount_sats, req.memo or ""
        )
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Transfer failed: {e}")


@router.get("/transfers")
async def get_recent_transfers(limit: int = 20):
    """Get recent inter-agent transfers."""
    try:
        transfers = await lightning.get_recent_transfers(limit)
        return {"transfers": transfers, "count": len(transfers)}
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Error: {e}")


@router.get("/lnurl/{agent}")
async def get_agent_lnurl(agent: str):
    """Get LNURL-pay endpoint for an agent (for zaps)."""
    try:
        lnurl = await lightning.get_lnurl_pay(agent)
        if not lnurl:
            raise HTTPException(
                status_code=404,
                detail=f"No LNURL-pay configured for {agent}",
            )
        return {"agent": agent, "lnurl": lnurl}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Error: {e}")
