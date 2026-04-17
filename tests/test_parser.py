"""Unit tests for the workflow parser."""

from __future__ import annotations

import pytest

from workflowmvp.parser import WorkflowParser


@pytest.fixture()
def parser() -> WorkflowParser:
    return WorkflowParser()


def test_parses_simple_numbered_steps(parser: WorkflowParser) -> None:
    text = """
    1. Download https://example.com/data.json
    2. Write the text "hi" to file "out.txt"
    3. Wait for 2 seconds
    """.strip()
    steps = parser.parse_workflow(text)

    assert len(steps) == 3
    assert steps[0].action == "download"
    assert steps[0].parameters.get("url") == "https://example.com/data.json"
    assert steps[1].action == "write_file"
    assert steps[1].parameters.get("file_path") == "out.txt"
    assert steps[2].action == "wait"
    assert steps[2].parameters.get("seconds") == 2


def test_dependencies_link_sequentially(parser: WorkflowParser) -> None:
    text = "1. Create a directory\n2. Write a file"
    steps = parser.parse_workflow(text)
    assert steps[0].dependencies == []
    assert steps[1].dependencies == ["step_1"]


def test_detects_email_action(parser: WorkflowParser) -> None:
    steps = parser.parse_workflow(
        '1. Send email to admin@example.com with subject "Hello"'
    )
    assert steps[0].action == "send_email"
    assert steps[0].parameters.get("recipient") == "admin@example.com"


def test_empty_text_yields_no_steps(parser: WorkflowParser) -> None:
    assert parser.parse_workflow("") == []


def test_confidence_flags_custom_heavy_parse(parser: WorkflowParser) -> None:
    steps = parser.parse_workflow(
        """
        1. Do that thing from yesterday
        2. Maybe sync with whatever was created before
        """.strip()
    )
    confidence = parser.assess_parse_confidence(steps)
    assert confidence["needs_ai_assist"] is True
    assert confidence["score"] < 0.55


def test_parses_step_number_and_description_on_next_line(
    parser: WorkflowParser,
) -> None:
    text = """
    1.
    Download https://example.com/data.json
    2.
    Write the text "ok" to file "out.txt"
    """.strip()
    steps = parser.parse_workflow(text)
    assert len(steps) == 2
    assert steps[0].action == "download"
    assert steps[0].parameters.get("url") == "https://example.com/data.json"
    assert steps[1].action == "write_file"
    assert steps[1].parameters.get("file_path") == "out.txt"
