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


def test_independent_steps_do_not_auto_chain(parser: WorkflowParser) -> None:
    """Adjacent but unrelated steps must not get a fake dependency.

    The previous parser unconditionally appended ``steps[i-1].step_id`` which
    over-constrained codegen for parallel work. We now require explicit
    data-flow markers in the description.
    """
    text = "1. Create a directory\n2. Write a file"
    steps = parser.parse_workflow(text)
    assert steps[0].dependencies == []
    assert steps[1].dependencies == []


def test_explicit_dependency_markers_link_steps(parser: WorkflowParser) -> None:
    text = (
        "1. Fetch the latest news headlines\n"
        "2. Use the result to compose an email\n"
        "3. Send the email from step 2 to test@example.com"
    )
    steps = parser.parse_workflow(text)
    assert steps[0].dependencies == []
    assert "step_1" in steps[1].dependencies
    assert "step_2" in steps[2].dependencies


def test_paragraph_between_steps_does_not_merge(parser: WorkflowParser) -> None:
    text = (
        "1. Download https://example.com/data.json\n"
        "Some intro paragraph that the user pasted between steps and is not\n"
        "indented and does not start with a continuation marker.\n"
        "2. Write the text \"hi\" to file \"out.txt\""
    )
    steps = parser.parse_workflow(text)
    assert len(steps) == 2
    assert steps[0].description == "Download https://example.com/data.json"
    assert steps[0].action == "download"
    assert steps[1].action == "write_file"


def test_indented_continuation_still_merges(parser: WorkflowParser) -> None:
    text = (
        "1. Download https://example.com/data.json\n"
        "   then save it as raw_data.json\n"
        "2. Write the text \"hi\" to file \"out.txt\""
    )
    steps = parser.parse_workflow(text)
    assert len(steps) == 2
    assert "raw_data.json" in steps[0].description


def test_bare_uppercase_word_is_not_a_ticker(parser: WorkflowParser) -> None:
    """USA, ASAP, HTTP and friends must not become stock tickers."""
    steps = parser.parse_workflow("1. Get the USA price right now")
    assert steps[0].parameters.get("ticker") in (None, "")


def test_explicit_ticker_marker_is_detected(parser: WorkflowParser) -> None:
    steps = parser.parse_workflow("1. Find the price of $AAPL")
    assert steps[0].action == "fetch_stock_price"
    assert steps[0].parameters.get("ticker") == "AAPL"

    steps = parser.parse_workflow("1. Get BTC-USD price")
    assert steps[0].parameters.get("ticker") == "BTC-USD"

    steps = parser.parse_workflow("1. Get the stock price for ticker MSFT")
    assert steps[0].action == "fetch_stock_price"
    assert steps[0].parameters.get("ticker") == "MSFT"


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


def test_parses_read_json(parser: WorkflowParser) -> None:
    steps = parser.parse_workflow('1. Read json from file "config.json"')
    assert len(steps) == 1
    assert steps[0].action == "read_json"
    assert steps[0].parameters.get("file_path") == "config.json"


def test_parses_write_json(parser: WorkflowParser) -> None:
    steps = parser.parse_workflow('1. Write json to file "out.json"')
    assert steps[0].action == "write_json"
    assert steps[0].parameters.get("file_path") == "out.json"


def test_parses_get_current_time(parser: WorkflowParser) -> None:
    steps = parser.parse_workflow("1. Get the current time in America/New_York")
    assert steps[0].action == "get_current_time"
    assert steps[0].parameters.get("timezone") == "America/New_York"


def test_parses_read_pdf(parser: WorkflowParser) -> None:
    steps = parser.parse_workflow('1. Read the PDF file "report.pdf"')
    assert len(steps) == 1
    assert steps[0].action == "read_pdf"
    assert steps[0].parameters.get("file_path") == "report.pdf"


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
