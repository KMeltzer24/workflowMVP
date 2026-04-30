"""Unit tests for workflow step payload validation."""

from __future__ import annotations

from workflowmvp.parser import WorkflowStep
from workflowmvp.services.workflow_validation import validate_workflow_steps


def _valid_step(**overrides: object) -> dict[str, object]:
    step: dict[str, object] = {
        "step_id": "step_1",
        "description": "Wait for 1 second",
        "action": "wait",
        "parameters": {"seconds": 1},
        "dependencies": [],
    }
    step.update(overrides)
    return step


def test_non_list_payload_is_invalid() -> None:
    result = validate_workflow_steps({"steps": []})

    assert result.valid is False
    assert result.steps == []
    assert result.errors
    assert result.errors[0].field == "steps"


def test_non_dict_step_is_invalid() -> None:
    result = validate_workflow_steps(["not-a-step"])

    assert result.valid is False
    assert result.steps == []
    assert result.errors[0].field == "steps"


def test_missing_required_shape_field_is_invalid() -> None:
    result = validate_workflow_steps([
        {
            "step_id": "step_1",
            "action": "wait",
            "parameters": {"seconds": 1},
            "dependencies": [],
        }
    ])

    assert result.valid is False
    assert result.steps == []
    assert any(issue.field == "description" for issue in result.errors)


def test_unknown_action_is_invalid() -> None:
    result = validate_workflow_steps([_valid_step(action="invented_tool")])

    assert result.valid is False
    assert result.steps == []
    assert any(issue.field == "action" for issue in result.errors)


def test_registry_tool_action_is_allowed() -> None:
    result = validate_workflow_steps([
        _valid_step(
            description="Extract order numbers from text",
            action="extract_regex",
            parameters={"text": "Order 123", "pattern": r"\d+"},
        )
    ])

    assert result.valid is True
    assert result.errors == []
    assert result.steps[0].action == "extract_regex"


def test_missing_required_param_is_invalid() -> None:
    result = validate_workflow_steps([
        _valid_step(
            description="Send email to admin@example.com",
            action="send_email",
            parameters={},
        )
    ])

    assert result.valid is False
    assert result.steps == []
    assert any(issue.field == "parameters.recipient" for issue in result.errors)


def test_side_effecting_action_produces_warning() -> None:
    result = validate_workflow_steps([
        _valid_step(
            description='Write "hello" to file "note.txt"',
            action="write_file",
            parameters={"file_path": "note.txt"},
        )
    ])

    assert result.valid is True
    assert result.errors == []
    assert result.warnings
    assert result.warnings[0].action == "write_file"


def test_valid_step_returns_workflow_step() -> None:
    result = validate_workflow_steps([_valid_step()])

    assert result.valid is True
    assert result.errors == []
    assert len(result.steps) == 1
    assert isinstance(result.steps[0], WorkflowStep)
    assert result.steps[0].step_id == "step_1"
    assert result.steps[0].action == "wait"
