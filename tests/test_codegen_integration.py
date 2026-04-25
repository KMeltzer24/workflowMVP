"""Integration test: WorkflowAgent.generate_workflow_code → real subprocess.

Stubs the LLM call so the test is hermetic, but still exercises the
end-to-end pipeline:

1. WorkflowAgent assembles a system prompt from real WorkflowSteps.
2. Mocked LLM returns a plausible script that uses ToolRegistry.write_file.
3. The generated file is compiled (so syntax errors fail loudly) and then
   executed via ``subprocess.run`` against the project's interpreter.
4. We assert the file the script was supposed to produce actually appeared
   on disk in the temp dir.
"""

from __future__ import annotations

import os
import subprocess
import sys
import textwrap
from pathlib import Path
from unittest.mock import patch

from workflowmvp.agent import WorkflowAgent
from workflowmvp.parser import WorkflowStep

_GENERATED_SCRIPT_TEMPLATE = textwrap.dedent(
    """
    import logging, json, os
    from workflowmvp.tools import ToolRegistry

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    logger = logging.getLogger(__name__)


    def main() -> None:
        tools = ToolRegistry()
        write = tools.get_tool("write_file").function
        result = write(file_path="codegen_integration.txt", content="ok")
        logger.info("WRITE_OK=%s", result.get("success"))


    if __name__ == "__main__":
        main()
    """
).strip()


def test_generate_workflow_code_runs_end_to_end(tmp_path: Path) -> None:
    project_root = Path(__file__).resolve().parents[1]

    agent = WorkflowAgent.__new__(WorkflowAgent)
    from workflowmvp.tools import ToolRegistry

    agent._llm = None  # type: ignore[attr-defined]
    agent.provider = "gemini"
    agent.model = "fake-model"
    agent.api_key = "fake-key"
    agent.tool_registry = ToolRegistry()

    steps = [
        WorkflowStep(
            step_id="step_1",
            description='Write "ok" to file "codegen_integration.txt"',
            action="write_file",
            parameters={"file_path": "codegen_integration.txt", "content": "ok"},
            dependencies=[],
        )
    ]

    output_path = tmp_path / "generated.py"

    with patch.object(WorkflowAgent, "_generate_text", return_value=_GENERATED_SCRIPT_TEMPLATE):
        code = agent.generate_workflow_code(steps, output_file=str(output_path))

    assert output_path.exists()
    compile(code, str(output_path), "exec")
    assert "ToolRegistry" in code

    env = os.environ.copy()
    existing_pp = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = f"{project_root}{os.pathsep}{existing_pp}" if existing_pp else str(project_root)

    completed = subprocess.run(
        [sys.executable, str(output_path)],
        cwd=str(tmp_path),
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert completed.returncode == 0, (
        f"subprocess failed: stdout={completed.stdout!r} stderr={completed.stderr!r}"
    )
    assert "WRITE_OK=True" in (completed.stdout + completed.stderr)
    assert (tmp_path / "codegen_integration.txt").exists()
    assert (tmp_path / "codegen_integration.txt").read_text() == "ok"
