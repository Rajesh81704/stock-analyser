"""
FastDesk MarketX Web Server Launcher
Launches the FastAPI backend & interactive web workstation on http://localhost:8000
"""

import argparse
import sys
import uvicorn


def main():
    parser = argparse.ArgumentParser(description="FastDesk MarketX Server Launcher")
    parser.add_argument("--host", type=str, default="0.0.0.0", help="Host IP address to bind to (default: 0.0.0.0)")
    parser.add_argument("--port", type=int, default=8000, help="Port to run FastAPI server on (default: 8000)")
    parser.add_argument("--no-reload", action="store_true", help="Disable auto-reload mode")

    args = parser.parse_args()
    uvicorn.run(
        "web.app:app",
        host=args.host,
        port=args.port,
        reload=not args.no_reload
    )


if __name__ == "__main__":
    main()
