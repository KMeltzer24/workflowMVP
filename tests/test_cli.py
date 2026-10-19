"""CLI helpers (no live server bind)."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from workflowmvp.cli import default_host, default_port, run_server


def test_default_host_and_port(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("HOST", raising=False)
    monkeypatch.delenv("PORT", raising=False)
    assert default_host() == "127.0.0.1"
    assert default_port() == 5050


def test_default_host_and_port_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOST", "0.0.0.0")
    monkeypatch.setenv("PORT", "6000")
    assert default_host() == "0.0.0.0"
    assert default_port() == 6000


def test_default_port_invalid(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PORT", "nope")
    assert default_port() == 5050


def test_run_server_debug_calls_app_run(capsys: pytest.CaptureFixture[str]) -> None:
    app = MagicMock()
    run_server(app, host="127.0.0.1", port=5050, debug=True)
    app.run.assert_called_once_with(debug=True, host="127.0.0.1", port=5050)
    assert "Debug mode" in capsys.readouterr().out


def test_run_server_non_localhost_warns(capsys: pytest.CaptureFixture[str]) -> None:
    app = MagicMock()
    run_server(app, host="0.0.0.0", port=5050, debug=False)
    app.run.assert_called_once()
    assert "anyone on this network" in capsys.readouterr().out


def test_run_server_bind_failure_exits() -> None:
    app = MagicMock()
    app.run.side_effect = OSError("address already in use")
    with pytest.raises(SystemExit) as exc:
        run_server(app, host="127.0.0.1", port=5050, debug=False)
    assert exc.value.code == 1
