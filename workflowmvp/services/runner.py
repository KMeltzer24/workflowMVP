"""Subprocess + sandbox helpers for running generated workflow scripts.

This module owns:
  - POSIX rlimits applied to workflow subprocesses (CPU / RSS / file size).
  - Building the subprocess environment from request credentials.
  - Resolving the per-run working directory under ``data/temp_outputs``.
  - Validating workflow paths stay inside ``data/generated_workflows``.
  - Server-Sent Event encoding helpers used by the streaming endpoint.

The Flask routes in ``main.py`` should be thin wrappers around these
functions so the runtime concerns are isolated and unit-testable.
"""

from __future__ import annotations

import json
import os
import sys
from collections.abc import Iterable
from typing import Any, Callable, Dict, Optional

from flask import Response, stream_with_context

from . import paths as _paths

# POSIX resource caps applied to generated workflow subprocesses. Prevents
# a runaway script from exhausting host CPU / memory / disk. Bypass by
# setting ``WORKFLOW_DISABLE_RLIMIT=1`` in the env (useful for long-running
# LLM calls).
_RLIMIT_CPU_SECONDS = int(os.getenv("WORKFLOW_RLIMIT_CPU", "120"))
_RLIMIT_AS_BYTES = int(os.getenv("WORKFLOW_RLIMIT_AS_MB", "1024")) * 1024 * 1024
_RLIMIT_FSIZE_BYTES = int(os.getenv("WORKFLOW_RLIMIT_FSIZE_MB", "100")) * 1024 * 1024

SECRET_ENV_KEYS = {
    "GEMINI_API_KEY",
    "EMAIL_PASSWORD",
    "EMAIL_USER",
    "EMAIL_FROM",
    "SMTP_SERVER",
}
_MIN_SECRET_LENGTH = 8


def apply_workflow_rlimits() -> None:
    """preexec_fn for workflow subprocesses: cap CPU, address space, file size.

    POSIX only. On Windows (or when ``WORKFLOW_DISABLE_RLIMIT=1``) this is a
    no-op. Errors from individual ``setrlimit`` calls are swallowed
    intentionally — partial limits are better than the subprocess never
    starting because of an unsupported limit on a given OS.
    """
    if os.getenv("WORKFLOW_DISABLE_RLIMIT") == "1":
        return
    try:
        import resource  # POSIX-only
    except ImportError:
        return
    try:
        resource.setrlimit(resource.RLIMIT_CPU, (_RLIMIT_CPU_SECONDS, _RLIMIT_CPU_SECONDS))
    except (ValueError, OSError):
        pass
    try:
        resource.setrlimit(resource.RLIMIT_AS, (_RLIMIT_AS_BYTES, _RLIMIT_AS_BYTES))
    except (ValueError, OSError):
        pass
    try:
        resource.setrlimit(resource.RLIMIT_FSIZE, (_RLIMIT_FSIZE_BYTES, _RLIMIT_FSIZE_BYTES))
    except (ValueError, OSError):
        pass
    try:
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    except (ValueError, OSError):
        pass


def workflow_popen_kwargs() -> Dict[str, Any]:
    """Extra kwargs for Popen/run that apply POSIX resource caps where available."""
    if sys.platform == "win32":
        return {}
    return {"preexec_fn": apply_workflow_rlimits}


def build_run_env(creds: Dict[str, str]) -> Dict[str, str]:
    """Build a subprocess env: parent env + PYTHONPATH + request creds."""
    env = os.environ.copy()
    existing_path = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = (
        _paths.PROJECT_ROOT
        + (os.pathsep + existing_path if existing_path else "")
    )
    env.update(creds)
    return env


def secret_values_from_env(env: Dict[str, str]) -> list[str]:
    """Return non-empty, long-enough secret values from an environment dict."""
    values: set[str] = set()
    for key in SECRET_ENV_KEYS:
        raw = env.get(key)
        if raw is None:
            continue
        value = str(raw)
        if len(value) >= _MIN_SECRET_LENGTH:
            values.add(value)
    return sorted(values, key=len, reverse=True)


def build_redactor(env: Dict[str, str]) -> Callable[[object], str]:
    """Build a function that redacts known secret values from text."""
    secret_values = secret_values_from_env(env)

    def redact(text: object) -> str:
        redacted = str(text)
        for value in secret_values:
            redacted = redacted.replace(value, "[REDACTED]")
        return redacted

    return redact


def ensure_run_dir(run_id: str) -> str:
    run_dir = os.path.join(_paths.TEMP_OUTPUTS_DIR, run_id)
    os.makedirs(run_dir, exist_ok=True)
    return run_dir


def resolve_workflow_path(raw: str) -> Optional[str]:
    """Resolve a workflow path and ensure it stays under ``GENERATED_DIR``.

    Returns ``None`` for invalid input or path-traversal attempts. The
    caller is expected to surface a "not found" error to the API client.

    The ``GENERATED_DIR`` and ``PROJECT_ROOT`` values are looked up on the
    ``paths`` module at call time so tests can monkeypatch them via
    ``workflowmvp.services.paths`` without re-importing this module.
    """
    if not raw:
        return None
    project_root = _paths.PROJECT_ROOT
    generated_dir = _paths.GENERATED_DIR
    candidate = raw if os.path.isabs(raw) else os.path.join(project_root, raw)
    candidate = os.path.abspath(candidate)
    if not candidate.startswith(generated_dir + os.sep) and candidate != generated_dir:
        return None
    if not os.path.exists(candidate):
        return None
    return candidate


def encode_sse(event: str, data: Dict[str, Any]) -> bytes:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n".encode()


def sse_error_response(message: str) -> Response:
    """Wrap a single SSE ``error`` event in a streaming Flask Response."""
    def gen() -> Iterable[bytes]:
        yield encode_sse("error", {"message": message})

    return Response(stream_with_context(gen()), mimetype="text/event-stream")
