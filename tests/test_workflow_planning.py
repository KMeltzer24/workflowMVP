"""Tests for shared workflow planning decisions."""

from __future__ import annotations

from workflowmvp.services.workflow_planning import parse_rough_workflow


def test_missing_required_param_triggers_ai_repair() -> None:
    result = parse_rough_workflow("1. Get the current Apple stock price")

    assert result.steps[0].action == "fetch_stock_price"
    assert result.steps[0].parameters.get("ticker") == ""
    assert result.parse_confidence["missing_param_steps"] == 1
    assert result.should_ai_repair is True


def test_simple_valid_parse_does_not_trigger_ai_repair() -> None:
    result = parse_rough_workflow("1. Wait for 1 second")

    assert result.steps[0].action == "wait"
    assert result.parse_confidence["missing_param_steps"] == 0
    assert result.parse_confidence["custom_steps"] == 0
    assert result.should_ai_repair is False
