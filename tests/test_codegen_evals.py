"""Hermetic codegen evals: prompt assembly + contract-valid golden scripts.

These do not call Gemini. They lock the expected tool set and response-shape
contracts for three resume-demo workflows (Bitcoin, CSV, email).
"""

from __future__ import annotations

import ast
import textwrap
from typing import List

import pytest

from workflowmvp.agent import WorkflowAgent
from workflowmvp.parser import WorkflowStep

BITCOIN_STEPS = [
    WorkflowStep(
        step_id="step_1",
        description="Download https://api.coinbase.com/v2/prices/BTC-USD/spot",
        action="download",
        parameters={"url": "https://api.coinbase.com/v2/prices/BTC-USD/spot"},
        dependencies=[],
    ),
    WorkflowStep(
        step_id="step_2",
        description='Write the Bitcoin USD price to file "bitcoin_price.txt"',
        action="write_file",
        parameters={"file_path": "bitcoin_price.txt"},
        dependencies=["step_1"],
    ),
    WorkflowStep(
        step_id="step_3",
        description='Send notification with title "Bitcoin" and message "Price saved"',
        action="send_notification",
        parameters={"title": "Bitcoin", "message": "Price saved"},
        dependencies=["step_2"],
    ),
]

CSV_STEPS = [
    WorkflowStep(
        step_id="step_1",
        description="Read CSV examples/inputs/tickets.csv",
        action="read_csv",
        parameters={"file_path": "examples/inputs/tickets.csv"},
        dependencies=[],
    ),
    WorkflowStep(
        step_id="step_2",
        description='Write filtered rows to "filtered_tickets.csv"',
        action="write_csv",
        parameters={"file_path": "filtered_tickets.csv"},
        dependencies=["step_1"],
    ),
]

EMAIL_STEPS = [
    WorkflowStep(
        step_id="step_1",
        description="Fetch the current SPY stock price",
        action="fetch_stock_price",
        parameters={"ticker": "SPY"},
        dependencies=[],
    ),
    WorkflowStep(
        step_id="step_2",
        description="Email the price to you@example.com",
        action="send_email",
        parameters={"recipient": "you@example.com"},
        dependencies=["step_1"],
    ),
]

BITCOIN_SCRIPT = textwrap.dedent(
    """
    import json
    import logging
    from workflowmvp.tools import ToolRegistry

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    logger = logging.getLogger(__name__)


    def main() -> None:
        tools = ToolRegistry()
        dl = tools.get_tool("download").function
        fetched = dl(url="https://api.coinbase.com/v2/prices/BTC-USD/spot")
        if not fetched.get("success"):
            logger.error(fetched.get("error"))
            return
        raw = fetched.get("result")
        write = tools.get_tool("write_file").function
        write(file_path="bitcoin_price.txt", content=str(raw))
        note = tools.get_tool("send_notification").function
        note(title="Bitcoin", message="Price saved")


    if __name__ == "__main__":
        main()
    """
).strip()

CSV_SCRIPT = textwrap.dedent(
    """
    import logging
    from workflowmvp.tools import ToolRegistry

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    logger = logging.getLogger(__name__)


    def main() -> None:
        tools = ToolRegistry()
        read = tools.get_tool("read_csv").function
        rows = read(file_path="examples/inputs/tickets.csv")
        if not rows.get("success"):
            logger.error(rows.get("error"))
            return
        write = tools.get_tool("write_csv").function
        write(file_path="filtered_tickets.csv", data=rows.get("rows") or [])


    if __name__ == "__main__":
        main()
    """
).strip()

EMAIL_SCRIPT = textwrap.dedent(
    """
    import logging
    from workflowmvp.tools import ToolRegistry

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    logger = logging.getLogger(__name__)


    def main() -> None:
        tools = ToolRegistry()
        quote = tools.get_tool("fetch_stock_price").function
        priced = quote(ticker="SPY")
        if not priced.get("success"):
            logger.error(priced.get("error"))
            return
        price = priced.get("price")
        email = tools.get_tool("send_email").function
        email(
            recipient="you@example.com",
            subject="SPY",
            body=f"SPY last close: {price}",
        )


    if __name__ == "__main__":
        main()
    """
).strip()


def _tool_names(code: str) -> set[str]:
    tree = ast.parse(code)
    names: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not isinstance(func, ast.Attribute) or func.attr != "get_tool":
            continue
        if node.args and isinstance(node.args[0], ast.Constant):
            names.add(str(node.args[0].value))
    return names


@pytest.fixture()
def agent(monkeypatch: pytest.MonkeyPatch) -> WorkflowAgent:
    monkeypatch.setenv("GEMINI_API_KEY", "fake-key-for-eval")
    return WorkflowAgent(api_key="fake-key-for-eval", provider="gemini")


@pytest.mark.parametrize(
    ("steps", "expected_tools", "script"),
    [
        (BITCOIN_STEPS, {"download", "write_file", "send_notification"}, BITCOIN_SCRIPT),
        (CSV_STEPS, {"read_csv", "write_csv"}, CSV_SCRIPT),
        (EMAIL_STEPS, {"fetch_stock_price", "send_email"}, EMAIL_SCRIPT),
    ],
)
def test_golden_eval_prompt_and_script(
    agent: WorkflowAgent,
    steps: List[WorkflowStep],
    expected_tools: set[str],
    script: str,
) -> None:
    prompt = agent._create_system_prompt(steps)
    for name in expected_tools:
        assert name in prompt
    compile(script, "<eval>", "exec")
    WorkflowAgent._validate_generated_python(script)
    assert expected_tools <= _tool_names(script)


def test_email_eval_includes_email_guidance(agent: WorkflowAgent) -> None:
    prompt = agent._create_system_prompt(EMAIL_STEPS)
    assert "EMAIL — send_email" in prompt
    assert "STOCK —" in prompt


def test_csv_eval_mentions_demo_input_path(agent: WorkflowAgent) -> None:
    prompt = agent._create_system_prompt(CSV_STEPS)
    assert "examples/inputs/tickets.csv" in prompt
