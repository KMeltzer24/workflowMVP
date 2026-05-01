"""Typed validation boundary for workflow step payloads.

This module is intentionally independent of Flask so API routes can validate
client-supplied workflow JSON before passing it to code generation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, List, Optional

from workflowmvp.parser import WorkflowParser, WorkflowStep
from workflowmvp.tools import Tool, ToolRegistry

SIDE_EFFECTING_ACTIONS = {
    "write_file",
    "write_json",
    "write_csv",
    "append_file",
    "copy_file",
    "move_file",
    "delete_file",
    "compress_files",
    "extract_archive",
    "download",
    "http_request",
    "send_email",
    "send_notification",
    "sqlite_query",
    "sqlite_insert",
    "run_command",
}


@dataclass(frozen=True)
class WorkflowValidationIssue:
    """A structured validation error or warning for one workflow step."""

    message: str
    step_id: Optional[str] = None
    field: Optional[str] = None
    action: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "message": self.message,
            "step_id": self.step_id,
            "field": self.field,
            "action": self.action,
        }


@dataclass(frozen=True)
class WorkflowValidationResult:
    """Result returned by workflow step validation."""

    valid: bool
    steps: List[WorkflowStep] = field(default_factory=list)
    errors: List[WorkflowValidationIssue] = field(default_factory=list)
    warnings: List[WorkflowValidationIssue] = field(default_factory=list)


def _registry_tools(registry: ToolRegistry) -> dict[str, Tool]:
    """Return registered tools keyed by action name."""
    return {tool.name: tool for tool in registry.list_tools()}


def allowed_actions(registry: ToolRegistry | None = None) -> set[str]:
    """Return all actions accepted by workflow generation."""
    registry = registry or ToolRegistry()
    return set(_registry_tools(registry)) | {"custom"}


def _metadata_required_params(tool: Tool | None) -> list[str]:
    """Return required params from structured tool metadata when available."""
    if tool is None:
        return []
    required: list[str] = []
    for name, metadata in tool.parameters.items():
        if isinstance(metadata, dict) and metadata.get("required") is True:
            required.append(name)
        elif getattr(metadata, "required", False) is True:
            required.append(name)
    return required


def missing_required_params(
    step: WorkflowStep, tools_by_action: dict[str, Tool] | None = None
) -> list[str]:
    """Return required parameters missing from a workflow step."""
    tool = (tools_by_action or {}).get(step.action)
    required = (
        _metadata_required_params(tool)
        or WorkflowParser.REQUIRED_ACTION_PARAMS.get(step.action, [])
    )
    return [
        key
        for key in required
        if not str(step.parameters.get(key, "")).strip()
    ]


def validate_workflow_steps(raw_steps: object) -> WorkflowValidationResult:
    """Validate and coerce a raw workflow step payload.

    This is the last structured boundary before code generation. Routes pass
    browser JSON through here so generated code only sees known actions,
    required parameters, and valid dependency shapes.
    """
    errors: List[WorkflowValidationIssue] = []
    warnings: List[WorkflowValidationIssue] = []
    steps: List[WorkflowStep] = []
    registry = ToolRegistry()
    tools_by_action = _registry_tools(registry)
    valid_actions = allowed_actions(registry)

    if not isinstance(raw_steps, list):
        return WorkflowValidationResult(
            valid=False,
            errors=[
                WorkflowValidationIssue(
                    message="Workflow steps payload must be a list.",
                    field="steps",
                )
            ],
        )

    for index, raw_step in enumerate(raw_steps, start=1):
        fallback_step_id = f"step_{index}"
        if not isinstance(raw_step, dict):
            errors.append(
                WorkflowValidationIssue(
                    message="Each workflow step must be an object.",
                    step_id=fallback_step_id,
                    field="steps",
                )
            )
            continue

        step_id = raw_step.get("step_id")
        description = raw_step.get("description")
        action = raw_step.get("action")
        parameters = raw_step.get("parameters")
        dependencies = raw_step.get("dependencies")

        issue_step_id = str(step_id).strip() if step_id is not None else fallback_step_id

        if not isinstance(step_id, str) or not step_id.strip():
            errors.append(
                WorkflowValidationIssue(
                    message="Step is missing required field: step_id.",
                    step_id=issue_step_id,
                    field="step_id",
                )
            )
        if not isinstance(description, str) or not description.strip():
            errors.append(
                WorkflowValidationIssue(
                    message="Step is missing required field: description.",
                    step_id=issue_step_id,
                    field="description",
                )
            )
        if not isinstance(action, str) or not action.strip():
            errors.append(
                WorkflowValidationIssue(
                    message="Step is missing required field: action.",
                    step_id=issue_step_id,
                    field="action",
                )
            )
        elif action.strip() not in valid_actions:
            errors.append(
                WorkflowValidationIssue(
                    message=f"Unknown workflow action: {action.strip()}.",
                    step_id=issue_step_id,
                    field="action",
                    action=action.strip(),
                )
            )
        if not isinstance(parameters, dict):
            errors.append(
                WorkflowValidationIssue(
                    message="Step field must be an object: parameters.",
                    step_id=issue_step_id,
                    field="parameters",
                )
            )
        if not isinstance(dependencies, list):
            errors.append(
                WorkflowValidationIssue(
                    message="Step field must be a list: dependencies.",
                    step_id=issue_step_id,
                    field="dependencies",
                )
            )

        shape_valid = (
            isinstance(step_id, str)
            and step_id.strip()
            and isinstance(description, str)
            and description.strip()
            and isinstance(action, str)
            and action.strip()
            and isinstance(parameters, dict)
            and isinstance(dependencies, list)
        )
        action_valid = isinstance(action, str) and action.strip() in valid_actions

        if shape_valid and action_valid:
            step = WorkflowStep(
                step_id=step_id.strip(),
                description=description.strip(),
                action=action.strip(),
                parameters=parameters,
                dependencies=dependencies,
            )
            for key in missing_required_params(step, tools_by_action):
                errors.append(
                    WorkflowValidationIssue(
                        message=f"Step is missing required parameter: {key}.",
                        step_id=step.step_id,
                        field=f"parameters.{key}",
                        action=step.action,
                    )
                )
            if step.action in SIDE_EFFECTING_ACTIONS:
                warnings.append(
                    WorkflowValidationIssue(
                        message=f"Step uses side-effecting tool: {step.action}.",
                        step_id=step.step_id,
                        field="action",
                        action=step.action,
                    )
                )
            steps.append(step)

    valid = not errors
    return WorkflowValidationResult(
        valid=valid,
        steps=steps if valid else [],
        errors=errors,
        warnings=warnings,
    )
