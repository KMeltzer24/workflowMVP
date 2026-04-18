"""Smoke tests for the Flask API."""

from __future__ import annotations

import pytest


def test_tools_endpoint(client) -> None:
    response = client.get("/api/tools")
    assert response.status_code == 200
    payload = response.get_json()
    assert isinstance(payload, list)
    names = {tool["name"] for tool in payload}
    assert {
        "download",
        "read_file",
        "write_file",
        "send_email",
        "read_json",
        "write_json",
        "append_file",
        "hash_file",
        "get_current_time",
        "read_pdf",
        "render_template",
        "fetch_stock_price",
    }.issubset(names)


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


# ---------------------------------------------------------------------------
# ACTION_REQUIREMENTS provider-aware resolution for generate_text
# ---------------------------------------------------------------------------


def _clear_llm_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in (
        "LLM_PROVIDER",
        "GEMINI_API_KEY",
        "GROQ_API_KEY",
        "OPENROUTER_API_KEY",
    ):
        monkeypatch.delenv(key, raising=False)


def test_check_requirements_generate_text_gemini_default(
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


def test_check_requirements_generate_text_groq_provider(
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
        "/api/check-requirements",
        json={"steps": steps, "credentials": {"LLM_PROVIDER": "groq"}},
    )
    data = response.get_json()
    assert data["success"] is True
    assert data["missing"] == ["GROQ_API_KEY"]


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

    generated_dir = tmp_path / "generated_workflows"
    generated_dir.mkdir()
    monkeypatch.setattr(main_module, "GENERATED_DIR", str(generated_dir))

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

    generated_dir = tmp_path / "generated_workflows"
    generated_dir.mkdir()
    monkeypatch.setattr(main_module, "GENERATED_DIR", str(generated_dir))

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


def test_check_requirements_generate_text_openrouter_provider(
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
        "/api/check-requirements",
        json={
            "steps": steps,
            "credentials": {
                "LLM_PROVIDER": "openrouter",
                "OPENROUTER_API_KEY": "sk-or-test",
            },
        },
    )
    data = response.get_json()
    assert data["success"] is True
    assert data["missing"] == []
