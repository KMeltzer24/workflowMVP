"""Shared HTTP helpers for Flask blueprints."""

from __future__ import annotations

import logging
import os
import re
import sys
from typing import Any, Dict, List
from urllib.parse import urlparse

from flask import Request, jsonify

from workflowmvp.parser import WorkflowStep

logger = logging.getLogger(__name__)

ALLOWED_VIDEO_MIME_PREFIXES = ("video/",)
ALLOWED_VIDEO_MIME_TYPES = {
    "application/octet-stream",
}


def is_debug() -> bool:
    return "--debug" in sys.argv


def json_error(message: str, status: int = 400, **extra: Any):
    payload: Dict[str, Any] = {"success": False, "error": message, **extra}
    return jsonify(payload), status


def json_internal_error(exc: BaseException):
    logger.exception("Unhandled API error")
    if is_debug():
        return json_error(str(exc), 500)
    return json_error("Internal server error", 500)


def step_to_dict(step: WorkflowStep) -> Dict[str, Any]:
    return {
        "step_id": step.step_id,
        "description": step.description,
        "action": step.action,
        "parameters": step.parameters,
        "dependencies": step.dependencies,
    }


def raw_steps_for_cleanup(raw_steps: object) -> List[WorkflowStep]:
    if not isinstance(raw_steps, list):
        return []

    cleanup_steps: List[WorkflowStep] = []
    for index, raw_step in enumerate(raw_steps, start=1):
        if not isinstance(raw_step, dict):
            continue
        parameters = raw_step.get("parameters")
        dependencies = raw_step.get("dependencies")
        cleanup_steps.append(
            WorkflowStep(
                step_id=str(raw_step.get("step_id") or f"step_{index}"),
                description=str(raw_step.get("description") or "").strip(),
                action=str(raw_step.get("action") or "custom").strip() or "custom",
                parameters=parameters if isinstance(parameters, dict) else {},
                dependencies=dependencies if isinstance(dependencies, list) else [],
            )
        )
    return cleanup_steps


def workflow_text_from_steps(steps: List[WorkflowStep]) -> str:
    return "\n".join(
        f"{index}. {step.description}"
        for index, step in enumerate(steps, start=1)
        if step.description
    )


def safe_name(name: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_\-]", "_", name).strip("_")
    return cleaned or "generated_workflow"


def same_origin(url: str, host: str) -> bool:
    parsed = urlparse(url)
    return parsed.scheme in {"http", "https"} and parsed.netloc == host


def enforce_same_origin_post(req: Request):
    if req.method != "POST":
        return None

    origin = (req.headers.get("Origin") or "").strip()
    referer = (req.headers.get("Referer") or "").strip()
    host = req.host
    if origin:
        if not same_origin(origin, host):
            return json_error("Cross-origin POST blocked. Use same-origin requests.", 403)
        return None
    if referer:
        if not same_origin(referer, host):
            return json_error("Cross-origin Referer blocked. Use same-origin requests.", 403)
        return None
    return json_error("Missing Origin or Referer. Same-origin POST required.", 403)


def blocking_run_enabled() -> bool:
    return os.getenv("WORKFLOW_ENABLE_BLOCKING_RUN_ENDPOINT", "0") == "1"


def max_upload_mb() -> int:
    try:
        return max(1, int(os.getenv("WORKFLOW_MAX_UPLOAD_MB", "100")))
    except ValueError:
        return 100
