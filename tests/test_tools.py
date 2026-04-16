"""Unit tests for the tool registry.

Covers the tools that the example workflows rely on, plus the safety contract
that `send_email` never calls `input()` and returns a structured missing-cred
error when credentials aren't available.
"""

from __future__ import annotations

import zipfile
from pathlib import Path
from unittest.mock import patch

import pytest
import requests

from workflowmvp.tools import ToolRegistry


@pytest.fixture()
def registry() -> ToolRegistry:
    return ToolRegistry()


def test_write_and_read_file_roundtrip(registry: ToolRegistry, tmp_path: Path) -> None:
    write = registry.get_tool("write_file").function
    read = registry.get_tool("read_file").function

    target = tmp_path / "hello.txt"
    w = write(file_path=str(target), content="hello world")
    assert w["success"] is True

    r = read(file_path=str(target))
    assert r["success"] is True
    assert r["content"] == "hello world"


def test_write_file_handles_bare_filename(
    registry: ToolRegistry, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """os.makedirs("") used to crash write_file for bare filenames."""
    monkeypatch.chdir(tmp_path)
    result = registry.get_tool("write_file").function(file_path="bare.txt", content="ok")
    assert result["success"] is True
    assert (tmp_path / "bare.txt").read_text() == "ok"


def test_analyze_data_average(registry: ToolRegistry) -> None:
    result = registry.get_tool("analyze_data").function(data=[1, 2, 3, 4], operation="average")
    assert result["success"] is True
    assert result["operation"] == "average"
    assert result["result"] == 2.5
    assert result["error"] is None
    assert result["meta"]["tool"] == "analyze_data"


def test_compress_and_extract_roundtrip(registry: ToolRegistry, tmp_path: Path) -> None:
    first = tmp_path / "a.txt"
    second = tmp_path / "b.txt"
    first.write_text("one")
    second.write_text("two")

    archive = tmp_path / "pack.zip"
    c = registry.get_tool("compress_files").function(
        files=[str(first), str(second)],
        archive_path=str(archive),
        include_dirs=False,
    )
    assert c["success"] is True
    with zipfile.ZipFile(archive) as zf:
        assert set(zf.namelist()) == {"a.txt", "b.txt"}

    extract_dir = tmp_path / "out"
    e = registry.get_tool("extract_archive").function(
        archive_path=str(archive), extract_to=str(extract_dir)
    )
    assert e["success"] is True
    assert (extract_dir / "a.txt").read_text() == "one"


def test_send_email_returns_structured_error_without_creds(
    registry: ToolRegistry, monkeypatch: pytest.MonkeyPatch
) -> None:
    for key in ("EMAIL_USER", "EMAIL_PASSWORD", "EMAIL_FROM"):
        monkeypatch.delenv(key, raising=False)

    # If send_email ever touched input() we'd hang under pytest. Patch it so
    # any accidental prompt surfaces as a clear test failure instead.
    with patch("builtins.input", side_effect=AssertionError("input() must not be called")):
        result = registry.get_tool("send_email").function(
            recipient="a@b.com", subject="hi", body="yo"
        )

    assert result["success"] is False
    assert "required" in result
    assert set(result["required"]) >= {"EMAIL_USER", "EMAIL_PASSWORD"}


def test_download_uses_requests(registry: ToolRegistry, monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeResponse:
        text = '{"ok": true}'
        content = b'{"ok": true}'

        def raise_for_status(self) -> None:
            return None

    def fake_get(url: str, timeout: int = 30) -> FakeResponse:
        assert url.startswith("http")
        assert timeout >= 1
        return FakeResponse()

    monkeypatch.setattr("workflowmvp.tools.requests.get", fake_get)
    result = registry.get_tool("download").function(url="https://example.com")
    assert result["success"] is True
    assert result["content"] == '{"ok": true}'
    assert result["result"] == '{"ok": true}'
    assert result["size"] == 12
    assert result["error"] is None


def test_download_retries_transient_failures(
    registry: ToolRegistry, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = {"count": 0}

    class FakeResponse:
        text = "ok"
        content = b"ok"

        def raise_for_status(self) -> None:
            return None

    def flaky_get(url: str, timeout: int = 30):  # type: ignore[no-untyped-def]
        calls["count"] += 1
        if calls["count"] < 3:
            raise requests.RequestException("transient")
        return FakeResponse()

    monkeypatch.setattr("workflowmvp.tools.requests.get", flaky_get)
    result = registry.get_tool("download").function(url="https://example.com")
    assert result["success"] is True
    assert calls["count"] == 3


def test_standardized_response_envelope(registry: ToolRegistry, tmp_path: Path) -> None:
    result = registry.get_tool("write_file").function(
        file_path=str(tmp_path / "x.txt"),
        content="ok",
    )
    assert result["success"] is True
    assert "result" in result
    assert "error" in result
    assert "meta" in result
    assert result["meta"]["tool"] == "write_file"


def test_list_files_filters_by_pattern(registry: ToolRegistry, tmp_path: Path) -> None:
    (tmp_path / "a.csv").write_text("x")
    (tmp_path / "b.txt").write_text("x")
    result = registry.get_tool("list_files").function(directory=str(tmp_path), pattern=".csv")
    assert result["success"] is True
    assert result["files"] == ["a.csv"]


def test_run_command_blocked_in_safe_mode() -> None:
    registry = ToolRegistry(safety_profile="safe")
    result = registry.get_tool("run_command").function(command="echo hi")
    assert result["success"] is False
    assert result.get("blocked") is True
    assert "safe mode" in result["error"]


def test_sandbox_blocks_paths_outside_run_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("WORKFLOW_OUTPUT_DIR", str(tmp_path))
    registry = ToolRegistry()
    result = registry.get_tool("write_file").function(
        file_path="../outside.txt",
        content="nope",
    )
    assert result["success"] is False
    assert "outside sandbox" in result["error"].lower()
