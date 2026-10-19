from __future__ import annotations

import os
import time
from typing import Optional

from flask import Blueprint, jsonify, request

from workflowmvp.agent import WorkflowAgent
from workflowmvp.http import (
    json_error,
    json_internal_error,
    raw_steps_for_cleanup,
    safe_name,
    step_to_dict,
    workflow_text_from_steps,
)
from workflowmvp.services.credentials import (
    missing_gemini_api_key_hint,
    resolve_gemini_api_key,
    resolve_gemini_model,
    sanitize_credentials,
)
from workflowmvp.services.examples import missing_requirements
from workflowmvp.services.paths import GENERATED_DIR, PROJECT_ROOT
from workflowmvp.services.runner import resolve_workflow_path
from workflowmvp.services.static_analysis import (
    extract_tools_from_source,
    extract_top_level_imports,
)
from workflowmvp.services.workflow_validation import validate_workflow_steps
from workflowmvp.tools import ToolRegistry

bp = Blueprint("codegen", __name__)


@bp.route("/api/generate-workflow", methods=["POST"])
def generate_workflow():
    try:
        payload = request.get_json(silent=True) or {}
        steps_data = payload.get("steps", [])
        workflow_name = safe_name(payload.get("name", "generated_workflow"))
        creds = sanitize_credentials(payload.get("credentials"))
        api_key = resolve_gemini_api_key(creds)
        if not api_key:
            missing_key = missing_gemini_api_key_hint()
            return json_error(
                f"Missing {missing_key}. Add it in Settings or .env.",
                400,
                missing_requirements=[missing_key],
            )

        model = resolve_gemini_model(creds)

        validation = validate_workflow_steps(steps_data)
        ai_cleaned_for_generation = False
        ai_cleanup_error: Optional[str] = None
        cleanup_steps = []
        cleanup_text = ""
        if not validation.valid:
            cleanup_steps = raw_steps_for_cleanup(steps_data)
            cleanup_text = workflow_text_from_steps(cleanup_steps)
            if cleanup_steps and cleanup_text:
                try:
                    ai_agent = WorkflowAgent(api_key=api_key, model=model)
                    improved = ai_agent.improve_parsed_steps(cleanup_text, cleanup_steps)
                    if improved:
                        repaired_validation = validate_workflow_steps(
                            [step_to_dict(step) for step in improved]
                        )
                        if repaired_validation.valid:
                            validation = repaired_validation
                            ai_cleaned_for_generation = True
                except Exception as exc:
                    ai_cleanup_error = str(exc)
        validation_warnings = [issue.to_dict() for issue in validation.warnings]
        if not validation.valid:
            return (
                jsonify(
                    {
                        "success": False,
                        "error": "Invalid workflow steps",
                        "validation_errors": [
                            issue.to_dict() for issue in validation.errors
                        ],
                        "validation_warnings": validation_warnings,
                        "ai_repair": {
                            "attempted": bool(cleanup_steps and cleanup_text),
                            "error": ai_cleanup_error,
                        },
                    }
                ),
                400,
            )

        steps = validation.steps

        os.makedirs(GENERATED_DIR, exist_ok=True)
        timestamp = int(time.time())
        output_path = os.path.join(GENERATED_DIR, f"{workflow_name}_{timestamp}.py")
        t_gen0 = time.monotonic()
        agent = WorkflowAgent(api_key=api_key, model=model)
        agent.generate_workflow_code(steps, output_path)
        generation_seconds = round(time.monotonic() - t_gen0, 3)

        return jsonify(
            {
                "success": True,
                "output_path": os.path.relpath(output_path, PROJECT_ROOT),
                "message": "Workflow generated successfully",
                "generation_seconds": generation_seconds,
                "validation_warnings": validation_warnings,
                "ai_repaired_for_generation": ai_cleaned_for_generation,
            }
        )
    except Exception as exc:
        return json_internal_error(exc)


@bp.route("/api/check-requirements", methods=["POST"])
def check_requirements():
    try:
        payload = request.get_json(silent=True) or {}
        steps = payload.get("steps", [])
        creds = sanitize_credentials(payload.get("credentials"))
        missing = missing_requirements(steps, creds)
        return jsonify({"success": True, "missing": missing})
    except Exception as exc:
        return json_internal_error(exc)


@bp.route("/api/validate-workflow", methods=["POST"])
def validate_workflow():
    payload = request.get_json(silent=True) or {}
    workflow_path = payload.get("workflow_path", "")
    abs_path = resolve_workflow_path(workflow_path)
    if not abs_path:
        return json_error("Workflow file not found", 404)
    try:
        with open(abs_path, encoding="utf-8") as f:
            source = f.read()
    except OSError as exc:
        return json_error(f"Could not read file: {exc}", 400)

    syntax_ok = True
    syntax_error: Optional[str] = None
    try:
        compile(source, abs_path, "exec")
    except SyntaxError as exc:
        syntax_ok = False
        syntax_error = f"{exc.msg} (line {exc.lineno})"

    tools_used = extract_tools_from_source(source)
    registry_tools = {tool.name for tool in ToolRegistry().list_tools()}
    unknown_tools = [name for name in tools_used if name not in registry_tools]

    return jsonify(
        {
            "success": syntax_ok and not unknown_tools,
            "syntax_ok": syntax_ok,
            "syntax_error": syntax_error,
            "tools_used": tools_used,
            "unknown_tools": unknown_tools,
            "imports": extract_top_level_imports(source),
            "line_count": source.count("\n") + 1,
            "workflow_path": workflow_path,
        }
    )
