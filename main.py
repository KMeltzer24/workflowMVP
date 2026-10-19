"""CLI entry for WorkflowMVP (`python main.py`)."""

from __future__ import annotations

import argparse
import os
import signal
import sys

from workflowmvp.app import app
from workflowmvp.cli import default_host, default_port, run_server
from workflowmvp.services.cleanup import cleanup_files as _services_cleanup_files
from workflowmvp.services.paths import GENERATED_DIR, PROJECT_ROOT, TEMP_OUTPUTS_DIR

__all__ = ["app", "cleanup_files", "main", "GENERATED_DIR", "PROJECT_ROOT", "TEMP_OUTPUTS_DIR"]


def cleanup_files(verbose: bool = True) -> int:
    return _services_cleanup_files(verbose=verbose)


def _is_debug() -> bool:
    return "--debug" in sys.argv


def _cleanup_on_exit() -> None:
    debug_mode = _is_debug()
    if debug_mode:
        print("\nCleaning up temporary files...")
    cleanup_files(verbose=debug_mode)


def _signal_handler(signum, frame):  # type: ignore[no-untyped-def]
    if _is_debug():
        print(f"\nReceived signal {signum}, shutting down...")
    else:
        print()
    _cleanup_on_exit()
    sys.exit(0)


def main() -> None:
    parser = argparse.ArgumentParser(description="WorkflowMVP - Web Interface")
    parser.add_argument(
        "--debug", action="store_true", help="Enable Flask debug mode (auto-reload)"
    )
    parser.add_argument(
        "--port",
        type=int,
        default=default_port(),
        help="Port to bind (default: env PORT or 5050)",
    )
    parser.add_argument(
        "--host",
        default=default_host(),
        help=(
            "Host interface to bind (default: env HOST or 127.0.0.1). "
            "Use 0.0.0.0 to expose on the LAN; the app runs LLM-generated "
            "Python so only do this on networks you trust."
        ),
    )
    args = parser.parse_args()

    signal.signal(signal.SIGINT, _signal_handler)
    signal.signal(signal.SIGTERM, _signal_handler)

    os.makedirs(GENERATED_DIR, exist_ok=True)
    os.makedirs(TEMP_OUTPUTS_DIR, exist_ok=True)

    run_server(app, host=args.host, port=args.port, debug=args.debug)


if __name__ == "__main__":
    main()
