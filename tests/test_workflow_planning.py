"""Tests for shared workflow planning decisions."""

from __future__ import annotations

from workflowmvp.services.workflow_planning import parse_rough_workflow


def test_common_finance_symbol_does_not_need_ai_repair() -> None:
    result = parse_rough_workflow("1. Then find the price of spy.")

    assert result.steps[0].action == "fetch_stock_price"
    assert result.steps[0].parameters.get("ticker") == "SPY"
    assert result.parse_confidence["missing_param_steps"] == 0
    assert result.should_ai_repair is False


def test_index_name_does_not_need_ai_repair() -> None:
    result = parse_rough_workflow("1. Find the current price of the S&P 500.")

    assert result.steps[0].action == "fetch_stock_price"
    assert result.steps[0].parameters.get("ticker") == "^GSPC"
    assert result.parse_confidence["missing_param_steps"] == 0
    assert result.should_ai_repair is False


def test_arbitrary_company_name_still_triggers_ai_repair() -> None:
    result = parse_rough_workflow("1. Find the current Apple stock price.")

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


def test_moderate_confidence_custom_steps_do_not_force_ai_repair() -> None:
    workflow = """\
1. Find out when the ani-marathon is at siff.net in Seattle
2. Write a reminder message with details about the day and time
3. Email this message to kevinmeltzer1@gmail.com
4. Then find the price of bitcoin.
5. Check if it is up or down compared to 5 days ago.
6. Send the percentage and value up or down to kevinmeltzer1@gmail.com
"""
    result = parse_rough_workflow(workflow)

    assert result.parse_confidence["custom_steps"] == 2
    assert result.parse_confidence["missing_param_steps"] == 0
    assert result.parse_confidence["score"] >= 0.75
    assert result.should_ai_repair is False
