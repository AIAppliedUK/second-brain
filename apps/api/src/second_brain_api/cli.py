from __future__ import annotations

import argparse
import os

import uvicorn

from .app import create_app


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the second-brain API server.")
    parser.add_argument("--host", default="127.0.0.1", help="Host to bind.")
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.getenv("SECOND_BRAIN_API_PORT", "8090")),
        help="Port to bind.",
    )
    parser.add_argument(
        "--reload",
        action="store_true",
        help="Enable auto-reload for local development.",
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    uvicorn.run(
        "second_brain_api.app:create_app",
        factory=True,
        host=args.host,
        port=args.port,
        reload=args.reload,
    )


if __name__ == "__main__":
    main()
