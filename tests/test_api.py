"""Smoke tests for the Flask API."""

from __future__ import annotations

import pytest

import main


@pytest.fixture()
def client():
    main.app.config["TESTING"] = True
    with main.app.test_client() as test_client:
        yield test_client


def test_tools_endpoint(client) -> None:
    response = client.get("/api/tools")
    assert response.status_code == 200
    payload = response.get_json()
    assert isinstance(payload, list)
    names = {tool["name"] for tool in payload}
    assert {"download", "read_file", "write_file", "send_email"}.issubset(names)


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
