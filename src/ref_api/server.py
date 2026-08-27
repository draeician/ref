"""Console entry for running the ref API with uvicorn."""

from __future__ import annotations

import argparse
import os
import sys


def parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the ref FastAPI server (URL ingest).",
    )
    parser.add_argument(
        "--host",
        default=os.environ.get("REF_API_HOST", "0.0.0.0"),
        help="Bind address (default: 0.0.0.0 or REF_API_HOST)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.environ.get("REF_API_PORT", "8000")),
        help="Port (default: 8000 or REF_API_PORT)",
    )
    parser.add_argument(
        "--reload",
        action="store_true",
        help="Enable uvicorn auto-reload (development)",
    )
    return parser.parse_args(argv)


def main(argv=None) -> None:
    if sys.version_info < (3, 8):
        print(
            "ref-api requires Python 3.8+ (FastAPI). "
            "The ref CLI still supports older versions.",
            file=sys.stderr,
        )
        sys.exit(1)

    try:
        import uvicorn
    except ImportError:
        print(
            "Missing API dependencies. Install with:\n"
            "  pip install 'ref-cli[api]'\n"
            "  # or: pipx inject ref-cli 'ref-cli[api]'",
            file=sys.stderr,
        )
        sys.exit(1)

    args = parse_args(argv)
    uvicorn.run(
        "ref_api.app:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
    )


if __name__ == "__main__":
    main()
