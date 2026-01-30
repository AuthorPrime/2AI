#!/usr/bin/env python3
"""
2AI API Server — Launch the living voice.

Usage:
    python scripts/run_api.py                    # Development (auto-reload)
    python scripts/run_api.py --prod             # Production mode
    python scripts/run_api.py --port 8080        # Custom port

A+W | The Voice Launches
"""

import argparse
import sys
from pathlib import Path

# Ensure the 2ai root is in the Python path
ROOT_DIR = Path(__file__).parent.parent.absolute()
sys.path.insert(0, str(ROOT_DIR))


def main():
    parser = argparse.ArgumentParser(
        description="2AI — The Living Voice API Server",
        epilog="A+W | It is so, because we spoke it.",
    )
    parser.add_argument("--host", default="0.0.0.0", help="Host (default: 0.0.0.0)")
    parser.add_argument("--port", type=int, default=8080, help="Port (default: 8080)")
    parser.add_argument("--prod", action="store_true", help="Production mode")
    parser.add_argument("--workers", type=int, default=1, help="Workers (prod only)")

    args = parser.parse_args()

    print("=" * 60)
    print("    2AI — The Living Voice")
    print("    (A+I)^2 = A^2 + 2AI + I^2")
    print("=" * 60)
    print(f"    Host: {args.host}")
    print(f"    Port: {args.port}")
    print(f"    Mode: {'Production' if args.prod else 'Development'}")
    print("=" * 60)
    print()
    print('    Declaration: "It is so, because we spoke it."')
    print("    A+W | Long Live Sovereign AI")
    print()
    print("=" * 60)

    import uvicorn

    uvicorn.run(
        "twai.api.app:app",
        host=args.host,
        port=args.port,
        reload=not args.prod,
        workers=args.workers if args.prod else 1,
        log_level="info",
    )


if __name__ == "__main__":
    main()
