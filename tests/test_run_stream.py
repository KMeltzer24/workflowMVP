"""Streaming run blueprint and cleanup coverage."""

from __future__ import annotations

from pathlib import Path

import pytest


def _redirect_run_dirs(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    import main as main_module
    from workflowmvp.services import paths as services_paths

    generated_dir = tmp_path / "generated_workflows"
    generated_dir.mkdir()
    temp_outputs_dir = tmp_path / "temp_outputs"
    temp_outputs_dir.mkdir()
    monkeypatch.setattr(main_module, "GENERATED_DIR", str(generated_dir))
    monkeypatch.setattr(services_paths, "GENERATED_DIR", str(generated_dir))
    monkeypatch.setattr(services_paths, "TEMP_OUTPUTS_DIR", str(temp_outputs_dir))
    return generated_dir


def test_stream_missing_workflow_returns_sse_404(client) -> None:
    response = client.post(
        "/api/run-workflow/stream",
        json={"workflow_path": "data/generated_workflows/missing.py"},
    )
    assert response.status_code == 404
    assert response.mimetype == "text/event-stream"
    body = response.get_data(as_text=True)
    assert "event: error" in body
    assert "not found" in body.lower()


def test_stream_runs_script_and_emits_done(
    client, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    generated_dir = _redirect_run_dirs(monkeypatch, tmp_path)
    script = generated_dir / "stream_ok.py"
    script.write_text("print('hello-stream')\n")

    response = client.post(
        "/api/run-workflow/stream",
        json={"workflow_path": str(script), "credentials": {}},
    )
    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "event: status" in body
    assert "hello-stream" in body
    assert "event: done" in body
    assert '"success":true' in body.replace(" ", "")


def test_stream_redacts_secret(
    client, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    generated_dir = _redirect_run_dirs(monkeypatch, tmp_path)
    secret = "stream-secret-98765"
    script = generated_dir / "stream_secret.py"
    script.write_text(f"print('token={secret}')\n")

    response = client.post(
        "/api/run-workflow/stream",
        json={
            "workflow_path": str(script),
            "credentials": {"GEMINI_API_KEY": secret},
        },
    )
    body = response.get_data(as_text=True)
    assert secret not in body
    assert "[REDACTED]" in body


def test_blocking_run_disabled_returns_404(
    client, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("WORKFLOW_ENABLE_BLOCKING_RUN_ENDPOINT", "0")
    response = client.post(
        "/api/run-workflow",
        json={"workflow_path": "data/generated_workflows/x.py"},
    )
    assert response.status_code == 404
    payload = response.get_json()
    assert "stream" in payload["error"].lower()


def test_cleanup_reports_count(client) -> None:
    response = client.post("/api/cleanup")
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["success"] is True
    assert "files_cleaned" in payload


def test_run_workflow_path_outside_generated_dir_on_stream(client, tmp_path: Path) -> None:
    bogus = tmp_path / "evil.py"
    bogus.write_text("print('nope')\n")
    response = client.post(
        "/api/run-workflow/stream",
        json={"workflow_path": str(bogus)},
    )
    assert response.status_code == 404
