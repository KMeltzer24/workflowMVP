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


def test_read_write_json_roundtrip(registry: ToolRegistry, tmp_path: Path) -> None:
    path = tmp_path / "data.json"
    w = registry.get_tool("write_json").function(
        file_path=str(path), data={"a": 1, "b": [2, 3]}
    )
    assert w["success"] is True
    r = registry.get_tool("read_json").function(file_path=str(path))
    assert r["success"] is True
    assert r["data"] == {"a": 1, "b": [2, 3]}


def test_append_file(registry: ToolRegistry, tmp_path: Path) -> None:
    p = tmp_path / "log.txt"
    a1 = registry.get_tool("append_file").function(file_path=str(p), content="one\n")
    assert a1["success"] is True
    a2 = registry.get_tool("append_file").function(file_path=str(p), content="two")
    assert a2["success"] is True
    raw = p.read_text()
    assert raw == "one\ntwo"


def test_hash_file(registry: ToolRegistry, tmp_path: Path) -> None:
    p = tmp_path / "blob.bin"
    p.write_bytes(b"hello")
    h = registry.get_tool("hash_file").function(file_path=str(p), algorithm="sha256")
    assert h["success"] is True
    assert h["hex_digest"] == "2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824"


def test_get_current_time_utc(registry: ToolRegistry) -> None:
    t = registry.get_tool("get_current_time").function(timezone="UTC")
    assert t["success"] is True
    assert "T" in t["iso"]
    assert t["unix"] > 0


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


def test_send_email_fails_when_attachment_missing(
    registry: ToolRegistry, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("EMAIL_USER", "a@b.com")
    monkeypatch.setenv("EMAIL_PASSWORD", "secret")
    monkeypatch.setenv("EMAIL_FROM", "a@b.com")
    monkeypatch.chdir(tmp_path)
    result = registry.get_tool("send_email").function(
        recipient="x@y.com",
        subject="t",
        body="hi",
        attachments=["does-not-exist.txt"],
    )
    assert result["success"] is False
    assert "Attachment not found" in (result.get("error") or "")


def test_download_uses_requests(registry: ToolRegistry, monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeResponse:
        text = '{"ok": true}'
        content = b'{"ok": true}'

        def raise_for_status(self) -> None:
            return None

    def fake_get(url: str, timeout: int = 30, **_: object) -> FakeResponse:
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

    def flaky_get(url: str, timeout: int = 30, **_: object):  # type: ignore[no-untyped-def]
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


def test_run_command_not_registered_in_safe_mode() -> None:
    registry = ToolRegistry(safety_profile="safe")
    assert registry.get_tool("run_command") is None
    assert "run_command" not in {tool.name for tool in registry.list_tools()}


def test_run_command_registered_in_full_mode() -> None:
    registry = ToolRegistry(safety_profile="full")
    tool = registry.get_tool("run_command")
    assert tool is not None
    # Deny list still rejects obvious footguns even when opted in to full mode.
    result = tool.function(command="sudo rm -rf /")
    assert result["success"] is False
    assert result.get("blocked") is True


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
