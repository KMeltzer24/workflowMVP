"""Unit tests for WorkflowAgent code extraction, system prompt, and code generation."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from workflowmvp.agent import WorkflowAgent
from workflowmvp.parser import WorkflowStep
from workflowmvp.tools import ToolRegistry

# ---------------------------------------------------------------------------
# _extract_python_script helpers
# ---------------------------------------------------------------------------


def test_extract_python_script_prefers_fenced_block() -> None:
    text = """
### Here is your script
```python
import os
print("hello")
```
Some explanation below.
""".strip()
    code = WorkflowAgent._extract_python_script(text)
    assert code.startswith("import os")
    assert 'print("hello")' in code


def test_extract_python_script_handles_unfenced_markdown_header() -> None:
    text = """
## Python Script
import json
from workflowmvp.tools import ToolRegistry
""".strip()
    code = WorkflowAgent._extract_python_script(text)
    assert code.startswith("import json")
    assert "ToolRegistry" in code


def test_extract_python_script_picks_longest_fenced_block() -> None:
    text = """
First try (short):
```python
x = 1
```

Better version:
```python
import json
from workflowmvp.tools import ToolRegistry
tools = ToolRegistry()
print("ok")
```
""".strip()
    code = WorkflowAgent._extract_python_script(text)
    assert "ToolRegistry" in code
    assert code.count("\n") >= 3


# ---------------------------------------------------------------------------
# System prompt dynamic tool list
# ---------------------------------------------------------------------------


@pytest.fixture()
def agent(monkeypatch: pytest.MonkeyPatch) -> WorkflowAgent:
    monkeypatch.setenv("GEMINI_API_KEY", "fake-key-for-test")
    return WorkflowAgent(api_key="fake-key-for-test", provider="gemini")


def test_system_prompt_lists_every_registered_tool(agent: WorkflowAgent) -> None:
    prompt = agent._create_system_prompt()
    registry_names = {tool.name for tool in ToolRegistry().list_tools()}
    assert registry_names, "registry unexpectedly empty"
    for name in registry_names:
        assert name in prompt, f"system prompt missing tool '{name}'"


def test_system_prompt_omits_removed_tools(agent: WorkflowAgent) -> None:
    prompt = agent._create_system_prompt()
    for removed in ("process_data", "analyze_data", "process_json"):
        assert removed not in prompt, f"removed tool '{removed}' leaked into prompt"


def test_system_prompt_has_structural_sections(agent: WorkflowAgent) -> None:
    prompt = agent._create_system_prompt()
    for header in ("SCRIPT STRUCTURE", "TOOL USAGE", "OUTPUT"):
        assert header in prompt, f"system prompt missing section '{header}'"


def test_system_prompt_groups_tools_by_category(agent: WorkflowAgent) -> None:
    prompt = agent._create_system_prompt()
    for label in ("Files & I/O", "Network & Web", "Communications"):
        assert f"### {label}" in prompt


def test_system_prompt_inlines_only_relevant_guidance(agent: WorkflowAgent) -> None:
    """Steps that don't use scraping/discovery should not get those snippets."""
    steps = [
        WorkflowStep(
            step_id="step_1",
            description="Write hi to file out.txt",
            action="write_file",
            parameters={"file_path": "out.txt"},
            dependencies=[],
        )
    ]
    prompt = agent._create_system_prompt(steps)
    # generate_text guidance is always-on for codegen flexibility.
    assert "AI TEXT GENERATION" in prompt
    # No scraping in this workflow → no SCRAPING block.
    assert "SCRAPING — scrape_webpage" not in prompt
    # No fetch_stock_price step → no STOCK guidance.
    assert "STOCK / FINANCIAL DATA" not in prompt


def test_system_prompt_includes_specific_guidance_when_action_present(
    agent: WorkflowAgent,
) -> None:
    steps = [
        WorkflowStep(
            step_id="step_1",
            description="Send email to me@example.com",
            action="send_email",
            parameters={"recipient": "me@example.com"},
            dependencies=[],
        )
    ]
    prompt = agent._create_system_prompt(steps)
    assert "EMAIL — send_email" in prompt


# ---------------------------------------------------------------------------
# generate_workflow_code with a fully mocked LLM response
# ---------------------------------------------------------------------------


_FAKE_GENERATED_SCRIPT = '''
```python
import logging
from workflowmvp.tools import ToolRegistry

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)


def main() -> None:
    tools = ToolRegistry()
    write = tools.get_tool("write_file").function
    result = write(file_path="hello.txt", content="hi")
    logger.info("WRITE_OK=%s", result.get("success"))


if __name__ == "__main__":
    main()
```
'''.strip()


def test_generate_workflow_code_writes_valid_python(
    agent: WorkflowAgent, tmp_path: Path
) -> None:
    steps = [
        WorkflowStep(
            step_id="step_1",
            description='Write "hi" to file "hello.txt"',
            action="write_file",
            parameters={"file_path": "hello.txt", "content": "hi"},
            dependencies=[],
        )
    ]
    output = tmp_path / "generated.py"

    with patch.object(WorkflowAgent, "_generate_text", return_value=_FAKE_GENERATED_SCRIPT):
        code = agent.generate_workflow_code(steps, output_file=str(output))

    assert output.exists()
    assert "ToolRegistry" in code
    compile(code, str(output), "exec")  # raises SyntaxError if invalid


def test_generate_workflow_code_raises_on_empty_model_output(
    agent: WorkflowAgent, tmp_path: Path
) -> None:
    steps = [
        WorkflowStep(
            step_id="step_1",
            description="do a thing",
            action="custom",
            parameters={},
            dependencies=[],
        )
    ]
    output = tmp_path / "generated.py"

    with patch.object(WorkflowAgent, "_generate_text", return_value=""):
        with pytest.raises(ValueError, match="empty"):
            agent.generate_workflow_code(steps, output_file=str(output))
