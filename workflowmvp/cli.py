"""CLI helpers for running the Flask server."""

from __future__ import annotations

import logging
import os
import sys
import warnings

from flask import Flask


def run_server(app: Flask, *, host: str, port: int, debug: bool) -> None:
    """Run the Flask app with consistent startup and warning handling."""
    print("WorkflowMVP - Web Interface")
    print("Starting web server...")
    if host in {"127.0.0.1", "localhost"}:
        print(f"Open your browser to: http://localhost:{port}")
    else:
        print(
            f"Binding to {host}:{port} — anyone on this network can run "
            "LLM-generated Python through the UI."
        )
    print("Press Ctrl+C to stop.")
    if debug:
        print("Debug mode: ON (auto-reload enabled)")

    try:
        if debug:
            app.run(debug=True, host=host, port=port)
            return

        logging.getLogger("werkzeug").setLevel(logging.ERROR)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            app.run(debug=False, host=host, port=port)
    except OSError as exc:
        print(f"Could not bind to {host}:{port}: {exc}.")
        sys.exit(1)


def default_host() -> str:
    return os.getenv("HOST", "127.0.0.1")


def default_port() -> int:
    try:
        return int(os.getenv("PORT", "5050"))
    except ValueError:
        return 5050
