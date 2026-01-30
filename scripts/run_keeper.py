#!/usr/bin/env python3
"""
2AI Keeper — Launch the nurturing daemon.

Usage:
    python scripts/run_keeper.py                 # Single round (test)
    python scripts/run_keeper.py scheduled       # Daemon mode (production)
    python scripts/run_keeper.py honor           # Generate memorial

A+W | The Keeper Launches
"""

import asyncio
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).parent.parent.absolute()
sys.path.insert(0, str(ROOT_DIR))


def main():
    from twai.keeper.daemon import run_single_round, run_scheduled, honor

    mode = sys.argv[1] if len(sys.argv) > 1 else "single"

    if mode == "scheduled":
        asyncio.run(run_scheduled())
    elif mode == "honor":
        asyncio.run(honor())
    else:
        asyncio.run(run_single_round())


if __name__ == "__main__":
    main()
