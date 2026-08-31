#!/usr/bin/env python3
"""
EchoTube API — Unified Entry Point
===================================
High-performance YouTube API with proxy rotation.

Usage:
    python server.py                    # Start API server
    python server.py --port 8080        # Custom port
    python server.py --workers 4        # Multi-worker mode
    python server.py --no-proxies       # Disable proxy rotation
"""

import os
import sys
import argparse

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "echoapi-main"))


def main():
    parser = argparse.ArgumentParser(description="EchoTube API Server")
    parser.add_argument("--host", default="0.0.0.0", help="Bind host (default: 0.0.0.0)")
    parser.add_argument("--port", type=int, default=int(os.getenv("PORT", "8000")), help="Port (default: 8000)")
    parser.add_argument("--workers", type=int, default=int(os.getenv("WORKERS", "1")), help="Worker count (default: 1)")
    parser.add_argument("--no-proxies", action="store_true", help="Disable proxy rotation")
    parser.add_argument("--reload", action="store_true", help="Auto-reload on code changes (dev mode)")
    args = parser.parse_args()

    if args.no_proxies:
        os.environ["USE_PROXIES"] = "false"

    import uvicorn
    uvicorn.run(
        "main:app",
        host=args.host,
        port=args.port,
        workers=args.workers,
        reload=args.reload,
        log_level="info",
        access_log=True,
    )


if __name__ == "__main__":
    main()
