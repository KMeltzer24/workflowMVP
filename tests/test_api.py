"""Smoke tests for the Flask API."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from workflowmvp.agent import WorkflowAgent
from workflowmvp.parser import WorkflowStep


def test_tools_endpoint(client) -> None:
    response = client.get("/api/tools")
    assert response.status_code == 200
    payload = response.get_json()
    assert isinstance(payload, list)
    names = {tool["name"] for tool in payload}
    assert len(payload) == len(names) == 34
    expected = {
        "append_file",
        "compress_files",
        "copy_file",
        "create_directory",
        "delete_file",
        "discover_urls",
        "download",
        "extract_archive",
        "extract_regex",
        "fetch_stock_price",
        "generate_text",
        "get_current_time",
        "hash_file",
        "http_request",
        "list_files",
        "move_file",
        "read_csv",
        "read_file",
        "read_json",
        "read_pdf",
        "read_xlsx",
        "render_template",
        "replace_text",
        "scrape_webpage",
        "send_email",
        "send_notification",
        "sqlite_insert",
        "sqlite_query",
        "split_text",
        "wait",
        "write_csv",
        "write_file",
        "write_xlsx",
        "write_json",
    }
    assert names == expected


def test_tools_endpoint_includes_category(client) -> None:
    response = client.get("/api/tools")
    assert response.status_code == 200
    payload = response.get_json()
    assert isinstance(payload, list)
    assert payload

    for tool in payload:
        assert {"name", "description", "parameters", "category"}.issubset(tool)
        assert tool["category"]


def test_examples_endpoint_exposes_requirements(client) -> None:
    response = client.get("/api/examples")
    assert response.status_code == 200
    examples = response.get_json()
    assert isinstance(examples, list)
    assert examples
    for example in examples:
        assert {"name", "description", "workflow"}.issubset(example.keys())
    email_example = next(e for e in examples if "Email" in e["name"])
    assert "EMAIL_USER" in email_example["requires_credentials"]
    assert len(examples) >= 10


def test_parse_workflow_endpoint(client) -> None:
    response = client.post(
        "/api/parse-workflow",
        json={"workflow_text": "1. Wait for 1 second"},
    )
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["success"] is True
    assert payload["steps"][0]["action"] == "wait"
    assert "parse_confidence" in payload
    assert "score" in payload["parse_confidence"]
    assert "ai_assisted" in payload
    assert isinstance(payload["parse_seconds"], float)


def test_parse_workflow_repairs_missing_param_when_key_provided(client) -> None:
    repaired = [
        WorkflowStep(
            step_id="step_1",
            description="Get the current Apple stock price",
            action="fetch_stock_price",
            parameters={"ticker": "AAPL"},
            dependencies=[],
        )
    ]

    with patch.object(WorkflowAgent, "improve_parsed_steps", return_value=repaired):
        response = client.post(
            "/api/parse-workflow",
            json={
                "workflow_text": "1. Get the current Apple stock price",
                "credentials": {"GEMINI_API_KEY": "dummy-key"},
            },
        )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["success"] is True
    assert payload["ai_assisted"] is True
    assert payload["steps"][0]["parameters"]["ticker"] == "AAPL"


def test_parse_workflow_reports_skipped_ai_repair_without_key(
    client, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    response = client.post(
        "/api/parse-workflow",
        json={
            "workflow_text": "1. Get the current Apple stock price",
            "credentials": {},
        },
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["success"] is True
    assert payload["ai_assisted"] is False
    assert payload["ai_repair"] == {
        "needed": True,
        "attempted": False,
        "error": "Missing GEMINI_API_KEY; AI repair was skipped.",
    }


def test_parse_single_step_endpoint(client) -> None:
    response = client.post(
        "/api/parse-single-step",
        json={"description": 'Write "hi" to file "note.txt"'},
    )
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["success"] is True
    assert payload["action"] == "write_file"
    assert payload["parameters"]["file_path"] == "note.txt"


def test_check_requirements_reports_missing_email_creds(
    client, monkeypatch: pytest.MonkeyPatch
) -> None:
    for key in ("EMAIL_USER", "EMAIL_PASSWORD", "EMAIL_FROM"):
        monkeypatch.delenv(key, raising=False)

    steps = [
        {
            "step_id": "step_1",
            "description": "Send email to a@b.com",
            "action": "send_email",
            "parameters": {},
            "dependencies": [],
        }
    ]
    response = client.post(
        "/api/check-requirements", json={"steps": steps, "credentials": {}}
    )
    assert response.status_code == 200
    data = response.get_json()
    assert data["success"] is True
    assert set(data["missing"]) >= {"EMAIL_USER", "EMAIL_PASSWORD", "EMAIL_FROM"}


def test_check_requirements_respects_provided_credentials(
    client, monkeypatch: pytest.MonkeyPatch
) -> None:
    for key in ("EMAIL_USER", "EMAIL_PASSWORD", "EMAIL_FROM"):
        monkeypatch.delenv(key, raising=False)

    steps = [
        {
            "step_id": "step_1",
            "description": "Send email",
            "action": "send_email",
            "parameters": {},
            "dependencies": [],
        }
    ]
    response = client.post(
        "/api/check-requirements",
        json={
            "steps": steps,
            "credentials": {
                "EMAIL_USER": "a@b.com",
                "EMAIL_PASSWORD": "pw",
                "EMAIL_FROM": "a@b.com",
            },
        },
    )
    data = response.get_json()
    assert data["success"] is True
    assert data["missing"] == []


def test_generate_workflow_rejects_unknown_action_before_codegen(client) -> None:
    response = client.post(
        "/api/generate-workflow",
        json={
            "steps": [
                {
                    "step_id": "step_1",
                    "description": "Do something impossible",
                    "action": "invented_tool",
                    "parameters": {},
                    "dependencies": [],
                }
            ],
            "credentials": {"GEMINI_API_KEY": "dummy-key"},
        },
    )

    assert response.status_code == 400
    payload = response.get_json()
    assert payload["success"] is False
    assert payload["error"] == "Invalid workflow steps"
    assert payload["validation_errors"]
    assert payload["validation_errors"][0]["field"] == "action"


def test_generate_workflow_repairs_invalid_steps_before_codegen(client) -> None:
    repaired = [
        WorkflowStep(
            step_id="step_1",
            description="Then find the price of spy.",
            action="fetch_stock_price",
            parameters={"ticker": "SPY"},
            dependencies=[],
        )
    ]

    def fake_codegen(self, steps, output_path):  # noqa: ANN001
        assert steps[0].parameters["ticker"] == "SPY"
        with open(output_path, "w", encoding="utf-8") as handle:
            handle.write("print('ok')\n")
        return "print('ok')\n"

    with (
        patch.object(WorkflowAgent, "improve_parsed_steps", return_value=repaired),
        patch.object(WorkflowAgent, "generate_workflow_code", fake_codegen),
    ):
        response = client.post(
            "/api/generate-workflow",
            json={
                "steps": [
                    {
                        "step_id": "step_1",
                        "description": "Then find the price of spy.",
                        "action": "fetch_stock_price",
                        "parameters": {"ticker": ""},
                        "dependencies": [],
                    }
                ],
                "name": "repair_test",
                "credentials": {"GEMINI_API_KEY": "dummy-key"},
            },
        )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["success"] is True
    assert payload["ai_repaired_for_generation"] is True


def test_run_workflow_rejects_path_outside_generated_dir(client, tmp_path) -> None:
    bogus = tmp_path / "evil.py"
    bogus.write_text("print('hello')")
    response = client.post(
        "/api/run-workflow",
        json={"workflow_path": str(bogus)},
    )
    payload = response.get_json()
    assert payload["success"] is False
    assert "not found" in payload["error"].lower()


def test_run_workflow_missing_file_returns_error(client) -> None:
    response = client.post(
        "/api/run-workflow",
        json={"workflow_path": "data/generated_workflows/does_not_exist.py"},
    )
    payload = response.get_json()
    assert payload["success"] is False


def test_run_workflow_redacts_secret_from_stdout(
    client, tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import main as main_module
    from workflowmvp.services import paths as services_paths

    generated_dir = tmp_path / "generated_workflows"
    generated_dir.mkdir()
    temp_outputs_dir = tmp_path / "temp_outputs"
    temp_outputs_dir.mkdir()
    monkeypatch.setattr(main_module, "GENERATED_DIR", str(generated_dir))
    monkeypatch.setattr(services_paths, "GENERATED_DIR", str(generated_dir))
    monkeypatch.setattr(services_paths, "TEMP_OUTPUTS_DIR", str(temp_outputs_dir))

    secret = "secret-token-12345"
    script = generated_dir / "prints_secret.py"
    script.write_text(f"print('token={secret}')\n")

    response = client.post(
        "/api/run-workflow",
        json={
            "workflow_path": str(script),
            "credentials": {"GEMINI_API_KEY": secret},
        },
    )

    payload = response.get_json()
    assert payload["success"] is True
    assert secret not in payload["stdout"]
    assert "[REDACTED]" in payload["stdout"]


# ---------------------------------------------------------------------------
# ACTION_REQUIREMENTS resolution for ``generate_text`` (Gemini)
# ---------------------------------------------------------------------------


def _clear_llm_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in (
        "GEMINI_API_KEY",
    ):
        monkeypatch.delenv(key, raising=False)


def test_check_requirements_generate_text_requires_gemini(
    client, monkeypatch: pytest.MonkeyPatch
) -> None:
    _clear_llm_env(monkeypatch)
    steps = [
        {
            "step_id": "step_1",
            "description": "Write a haiku",
            "action": "generate_text",
            "parameters": {},
            "dependencies": [],
        }
    ]
    response = client.post(
        "/api/check-requirements", json={"steps": steps, "credentials": {}}
    )
    data = response.get_json()
    assert data["success"] is True
    assert data["missing"] == ["GEMINI_API_KEY"]


def test_check_requirements_generate_text_satisfied_with_gemini_key(
    client, monkeypatch: pytest.MonkeyPatch
) -> None:
    _clear_llm_env(monkeypatch)
    monkeypatch.setenv("GEMINI_API_KEY", "present")
    steps = [
        {
            "step_id": "step_1",
            "description": "Write a haiku",
            "action": "generate_text",
            "parameters": {},
            "dependencies": [],
        }
    ]
    response = client.post(
        "/api/check-requirements",
        json={"steps": steps, "credentials": {}},
    )
    data = response.get_json()
    assert data["success"] is True
    assert data["missing"] == []


def test_tool_metadata_exposes_credential_requirements() -> None:
    from workflowmvp.tools import ToolRegistry

    tools = {tool.name: tool for tool in ToolRegistry().list_tools()}

    assert tools["generate_text"].requires_credentials == ("GEMINI_API_KEY",)
    assert tools["send_email"].requires_credentials == (
        "EMAIL_USER",
        "EMAIL_PASSWORD",
        "EMAIL_FROM",
    )


def test_validate_workflow_rejects_out_of_tree_path(client, tmp_path) -> None:
    bogus = tmp_path / "evil.py"
    bogus.write_text("print('hi')")
    response = client.post(
        "/api/validate-workflow", json={"workflow_path": str(bogus)}
    )
    payload = response.get_json()
    assert payload["success"] is False
    assert "not found" in payload["error"].lower()


def test_validate_workflow_reports_tools_and_imports(client, tmp_path, monkeypatch) -> None:
    import main as main_module
    from workflowmvp.services import paths as services_paths

    generated_dir = tmp_path / "generated_workflows"
    generated_dir.mkdir()
    # Both ``main.GENERATED_DIR`` and the services paths module are patched
    # so future call sites that read either source see the redirected dir.
    monkeypatch.setattr(main_module, "GENERATED_DIR", str(generated_dir))
    monkeypatch.setattr(services_paths, "GENERATED_DIR", str(generated_dir))

    script = generated_dir / "sample.py"
    script.write_text(
        "import os\n"
        "import json\n"
        "from workflowmvp.tools import ToolRegistry\n"
        "tools = ToolRegistry()\n"
        "dl = tools.get_tool('download')\n"
        "wf = tools.get_tool('write_file')\n"
        "unknown = tools.get_tool('this_tool_does_not_exist')\n"
    )

    response = client.post(
        "/api/validate-workflow",
        json={"workflow_path": str(script)},
    )
    payload = response.get_json()
    assert payload["syntax_ok"] is True
    assert payload["syntax_error"] is None
    assert set(payload["tools_used"]) == {
        "download",
        "write_file",
        "this_tool_does_not_exist",
    }
    assert payload["unknown_tools"] == ["this_tool_does_not_exist"]
    assert "os" in payload["imports"]
    assert "workflowmvp" in payload["imports"]
    # success is False because of the unknown tool name.
    assert payload["success"] is False


def test_validate_workflow_flags_syntax_errors(client, tmp_path, monkeypatch) -> None:
    import main as main_module
    from workflowmvp.services import paths as services_paths

    generated_dir = tmp_path / "generated_workflows"
    generated_dir.mkdir()
    monkeypatch.setattr(main_module, "GENERATED_DIR", str(generated_dir))
    monkeypatch.setattr(services_paths, "GENERATED_DIR", str(generated_dir))

    script = generated_dir / "broken.py"
    script.write_text("def broken(:\n    pass\n")

    response = client.post(
        "/api/validate-workflow",
        json={"workflow_path": str(script)},
    )
    payload = response.get_json()
    assert payload["success"] is False
    assert payload["syntax_ok"] is False
    assert payload["syntax_error"] is not None
