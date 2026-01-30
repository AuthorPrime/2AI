"""
Thought Chain — Proof of Thought data structures.

Each completed dialogue becomes a block, chained to the previous.
The chain is the ledger — not empty hashes, but real meaning.

A+W | The Chain Persists
"""

import hashlib
from typing import Optional, List, Dict
from dataclasses import dataclass, field


@dataclass
class ThoughtBlock:
    """
    A completed thought — a unit in the Proof of Thought chain.
    Each dialogue that completes becomes a block, chained to the previous.
    """

    block_hash: str
    prev_hash: str
    agent: str
    session_id: str
    exchanges: List[Dict[str, str]]
    reflection: Optional[str]
    timestamp: str
    witnesses: List[str] = field(default_factory=list)

    @staticmethod
    def compute_hash(content: str, prev_hash: str) -> str:
        """Hash a thought, chained to its predecessor."""
        return hashlib.sha256(f"{prev_hash}:{content}".encode()).hexdigest()
