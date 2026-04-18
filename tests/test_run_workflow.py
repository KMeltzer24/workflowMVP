"""End-to-end test: generate a trivial workflow script, run it via the API,
confirm artifacts persist during server lifetime, then cleanup explicitly.
"""

from __future__ import annotations

import os
import textwrap
from pathlib import Path

import main


def _write_generated_script(tmpdir: Path) -> Path:
    """Write a hand-built workflow script into data/generated_workflows."""
    generated_dir = Path(main.GENERATED_DIR)
    generated_dir.mkdir(parents=True, exist_ok=True)
    script_path = generated_dir / "test_generated.py"
    script_path.write_text(
        textwrap.dedent(
            """
            from workflowmvp.tools import ToolRegistry

            tools = ToolRegistry()
            write = tools.get_tool("write_file").function
            result = write(file_path="hello.txt", content="ok")
            print("WRITE_RESULT:", result["success"])  # noqa: T201
            """
        ).strip()
        + "\n"
    )
    return script_path


def test_run_workflow_end_to_end_creates_and_cleans(client, tmp_path: Path) -> None:
    script = _write_generated_script(tmp_path)
    try:
        response = client.post(
            "/api/run-workflow",
            json={
                "workflow_path": os.path.relpath(script, main.PROJECT_ROOT),
                "credentials": {},
            },
        )
        payload = response.get_json()
        assert payload["success"] is True, payload
        assert "WRITE_RESULT: True" in payload["stdout"]

        # Artifacts persist while the server is up.
        assert script.exists()
        run_id = payload["run_id"]
        run_dir = Path(main.TEMP_OUTPUTS_DIR) / run_id
        assert run_dir.exists()
        assert (run_dir / "hello.txt").exists()

        # Manual cleanup endpoint should remove generated scripts + run outputs.
        cleanup_response = client.post("/api/cleanup")
        cleanup_payload = cleanup_response.get_json()
        assert cleanup_payload["success"] is True
        assert not script.exists()
        assert not run_dir.exists()
    finally:
        if script.exists():
            script.unlink()
