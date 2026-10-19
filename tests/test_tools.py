"""Unit tests for the tool registry.

Covers the tools that the example workflows rely on, plus the safety contract
that `send_email` never calls `input()` and returns a structured missing-cred
error when credentials aren't available.
"""

from __future__ import annotations

import socket
import zipfile
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
import requests

from workflowmvp.tool_contracts import build_contract_prompt_guidance, validate_tool_contracts
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
    assert r["result"] == {"a": 1, "b": [2, 3]}
    assert r["data"] == {"a": 1, "b": [2, 3]}


def test_read_xlsx_reads_rows_as_dicts(registry: ToolRegistry, tmp_path: Path) -> None:
    from openpyxl import Workbook

    path = tmp_path / "users.xlsx"
    workbook = Workbook()
    worksheet = workbook.active
    worksheet.title = "Users"
    worksheet.append(["name", "age"])
    worksheet.append(["Alice", 30])
    worksheet.append(["Bob", 25])
    workbook.save(path)

    result = registry.get_tool("read_xlsx").function(
        file_path=str(path),
        sheet="Users",
    )

    assert result["success"] is True
    assert result["result"] == [
        {"name": "Alice", "age": 30},
        {"name": "Bob", "age": 25},
    ]
    assert result["data"] == result["result"]
    assert result["meta"]["sheet"] == "Users"
    assert result["meta"]["rows"] == 2
    assert result["meta"]["columns"] == ["name", "age"]


def test_write_xlsx_writes_rows_from_dicts(registry: ToolRegistry, tmp_path: Path) -> None:
    path = tmp_path / "users.xlsx"

    result = registry.get_tool("write_xlsx").function(
        file_path=str(path),
        data=[
            {"name": "Alice", "age": 30},
            {"name": "Bob", "age": 25},
        ],
        sheet="Users",
    )

    assert result["success"] is True
    assert result["result"] == str(path)
    assert result["file"] == str(path)
    assert result["meta"]["sheet"] == "Users"
    assert result["meta"]["rows"] == 2
    assert result["meta"]["columns"] == ["name", "age"]

    read_back = registry.get_tool("read_xlsx").function(
        file_path=str(path),
        sheet="Users",
    )
    assert read_back["success"] is True
    assert read_back["result"] == [
        {"name": "Alice", "age": 30},
        {"name": "Bob", "age": 25},
    ]


def test_append_file(registry: ToolRegistry, tmp_path: Path) -> None:
    p = tmp_path / "log.txt"
    a1 = registry.get_tool("append_file").function(file_path=str(p), content="one\n")
    assert a1["success"] is True
    a2 = registry.get_tool("append_file").function(file_path=str(p), content="two")
    assert a2["success"] is True
    raw = p.read_text()
    assert raw == "one\ntwo"


def test_write_file_accepts_data_alias(
    registry: ToolRegistry, tmp_path: Path
) -> None:
    path = tmp_path / "alias.txt"
    result = registry.get_tool("write_file").function(
        file_path=str(path), data="from-data"
    )
    assert result["success"] is True
    assert path.read_text() == "from-data"


def test_get_current_time_utc(registry: ToolRegistry) -> None:
    t = registry.get_tool("get_current_time").function(timezone="UTC")
    assert t["success"] is True
    assert "T" in t["iso"]
    assert t["unix"] > 0


def test_copy_move_delete_and_mkdir(
    registry: ToolRegistry, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    mkdir = registry.get_tool("create_directory").function(directory="nested")
    assert mkdir["success"] is True
    src = tmp_path / "src.txt"
    src.write_text("payload")
    copied = registry.get_tool("copy_file").function(
        source="src.txt", destination="nested/copy.txt"
    )
    assert copied["success"] is True
    assert (tmp_path / "nested" / "copy.txt").read_text() == "payload"
    moved = registry.get_tool("move_file").function(
        source="nested/copy.txt", destination="nested/moved.txt"
    )
    assert moved["success"] is True
    deleted = registry.get_tool("delete_file").function(file_path="nested/moved.txt")
    assert deleted["success"] is True
    assert not (tmp_path / "nested" / "moved.txt").exists()


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


def test_compress_files_reports_actual_count_and_skipped_files(
    registry: ToolRegistry, tmp_path: Path
) -> None:
    existing = tmp_path / "exists.txt"
    missing = tmp_path / "missing.txt"
    existing.write_text("one")

    archive = tmp_path / "pack.zip"
    result = registry.get_tool("compress_files").function(
        files=[str(existing), str(missing)],
        archive_path=str(archive),
        include_dirs=False,
    )

    assert result["success"] is True
    assert result["files"] == 1
    assert result["meta"]["files"] == 1
    assert result["meta"]["skipped"] == [str(missing)]
    with zipfile.ZipFile(archive) as zf:
        assert zf.namelist() == ["exists.txt"]


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


def _ok_http_response(text: str = "ok", content: bytes | None = None) -> MagicMock:
    response = MagicMock()
    response.status_code = 200
    response.ok = True
    response.reason = "OK"
    response.text = text
    response.content = content if content is not None else text.encode()
    response.headers = {"Content-Type": "text/plain"}
    response.is_redirect = False
    response.is_permanent_redirect = False
    response.raise_for_status = lambda: None
    return response


def test_download_uses_requests(registry: ToolRegistry, monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_request(method: str, url: str, timeout: object = 30, **_: object) -> MagicMock:
        assert method == "GET"
        assert url.startswith("http")
        if isinstance(timeout, tuple):
            assert timeout[0] >= 1 and timeout[1] >= 1
        else:
            assert float(timeout) >= 1
        return _ok_http_response('{"ok": true}', b'{"ok": true}')

    monkeypatch.setattr(
        "workflowmvp.tools._base.socket.getaddrinfo",
        lambda *_args, **_kwargs: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 0))
        ],
    )
    monkeypatch.setattr("workflowmvp.tools._base.requests.request", fake_request)
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

    def flaky_request(method: str, url: str, timeout: object = 30, **_: object):  # type: ignore[no-untyped-def]
        calls["count"] += 1
        if calls["count"] < 3:
            raise requests.RequestException("transient")
        return _ok_http_response()

    monkeypatch.setattr(
        "workflowmvp.tools._base.socket.getaddrinfo",
        lambda *_args, **_kwargs: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 0))
        ],
    )
    monkeypatch.setattr("workflowmvp.tools._base.requests.request", flaky_request)
    result = registry.get_tool("download").function(url="https://example.com")
    assert result["success"] is True
    assert calls["count"] == 3


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "http://localhost:5050",
        "http://127.0.0.1:5050",
        "http://169.254.169.254/latest/meta-data",
        "http://10.0.0.1",
    ],
)
def test_download_rejects_internal_or_non_http_urls(
    registry: ToolRegistry, url: str
) -> None:
    result = registry.get_tool("download").function(url=url)

    assert result["success"] is False
    assert result["error"]


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "http://localhost:5050",
        "http://169.254.169.254/latest/meta-data",
    ],
)
def test_http_request_rejects_internal_or_non_http_urls(
    registry: ToolRegistry, url: str
) -> None:
    result = registry.get_tool("http_request").function(url=url)

    assert result["success"] is False
    assert result["error"]


def test_http_request_allows_public_url_with_mocked_request(
    registry: ToolRegistry, monkeypatch: pytest.MonkeyPatch
) -> None:
    mock_response = MagicMock()
    mock_response.ok = True
    mock_response.status_code = 200
    mock_response.reason = "OK"
    mock_response.headers = {"Content-Type": "text/plain"}
    mock_response.text = "ok"

    req = MagicMock(return_value=mock_response)
    mock_response.is_redirect = False
    mock_response.is_permanent_redirect = False
    monkeypatch.setattr(
        "workflowmvp.tools._base.socket.getaddrinfo",
        lambda *_args, **_kwargs: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 0))
        ],
    )
    monkeypatch.setattr("workflowmvp.tools._base.requests.request", req)

    result = registry.get_tool("http_request").function(url="https://example.com")

    assert result["success"] is True
    assert result["result"] == "ok"
    req.assert_called_once()


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


def test_harmless_tools_return_standardized_response_envelope(
    registry: ToolRegistry, tmp_path: Path
) -> None:
    text_path = tmp_path / "note.txt"
    json_path = tmp_path / "data.json"

    responses = [
        registry.get_tool("write_file").function(
            file_path=str(text_path),
            content="hello",
        ),
        registry.get_tool("read_file").function(file_path=str(text_path)),
        registry.get_tool("write_json").function(
            file_path=str(json_path),
            data={"ok": True},
        ),
        registry.get_tool("read_json").function(file_path=str(json_path)),
        registry.get_tool("append_file").function(
            file_path=str(text_path),
            content="!",
        ),
        registry.get_tool("get_current_time").function(timezone="UTC"),
        registry.get_tool("render_template").function(
            template="Hello {{ name }}",
            variables={"name": "Kevin"},
            autoescape=False,
        ),
    ]

    for response in responses:
        assert set(response) >= {"success", "result", "error", "meta"}
        assert isinstance(response["success"], bool)
        assert response["error"] is None
        assert isinstance(response["meta"], dict)
        assert response["meta"]["tool"]


def test_registered_tools_expose_basic_contract_metadata(registry: ToolRegistry) -> None:
    tools = registry.list_tools()
    assert tools

    for tool in tools:
        assert tool.name
        assert tool.description
        assert isinstance(tool.parameters, dict)


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


# ---------------------------------------------------------------------------
# render_template
# ---------------------------------------------------------------------------


def test_render_template_basic(registry: ToolRegistry) -> None:
    result = registry.get_tool("render_template").function(
        template="Hello {{ name }}! You have {{ count }} items.",
        variables={"name": "Kevin", "count": 3},
        autoescape=False,
    )
    assert result["success"] is True
    assert result["rendered"] == "Hello Kevin! You have 3 items."


def test_render_template_autoescape_html(registry: ToolRegistry) -> None:
    result = registry.get_tool("render_template").function(
        template="<p>{{ body }}</p>",
        variables={"body": "<script>alert(1)</script>"},
        autoescape=True,
    )
    assert result["success"] is True
    assert "<script>" not in result["rendered"]
    assert "&lt;script&gt;" in result["rendered"]


def test_render_template_missing_variable_fails(registry: ToolRegistry) -> None:
    result = registry.get_tool("render_template").function(
        template="Hello {{ missing }}!",
        variables={},
    )
    assert result["success"] is False
    assert "missing" in result["error"].lower() or "undefined" in result["error"].lower()


def test_render_template_sandboxed_blocks_attr_access(registry: ToolRegistry) -> None:
    # Jinja2 SandboxedEnvironment blocks access to dunder attributes.
    result = registry.get_tool("render_template").function(
        template="{{ cls.__mro__ }}",
        variables={"cls": str},
    )
    assert result["success"] is False


# ---------------------------------------------------------------------------
# fetch_stock_price (yfinance mocked — no live Yahoo dependency in CI)
# ---------------------------------------------------------------------------


def test_fetch_stock_price_uses_last_close_from_history(
    registry: ToolRegistry,
) -> None:
    import pandas as pd

    hist = pd.DataFrame({"Close": [10.0, 10.5, 11.25]})
    mock_ticker = MagicMock()
    mock_ticker.history.return_value = hist
    mock_ticker.fast_info = MagicMock(currency="USD", long_name="Mock Inc")

    with patch("yfinance.Ticker", return_value=mock_ticker):
        out = registry.get_tool("fetch_stock_price").function(ticker="MOCK", period="5d")

    assert out["success"] is True
    assert out["ticker"] == "MOCK"
    assert out["price"] == 11.25
    assert out["currency"] == "USD"
    mock_ticker.history.assert_called_once_with(period="5d")


def test_fetch_stock_price_empty_history(registry: ToolRegistry) -> None:
    import pandas as pd

    mock_ticker = MagicMock()
    mock_ticker.history.return_value = pd.DataFrame()

    with patch("yfinance.Ticker", return_value=mock_ticker):
        out = registry.get_tool("fetch_stock_price").function(ticker="VOID")

    assert out["success"] is False
    assert "no data" in out["error"].lower()


# ---------------------------------------------------------------------------
# read_pdf
# ---------------------------------------------------------------------------


def _write_minimal_pdf(path: Path, pages_text: list[str]) -> None:
    """Build a real (if tiny) PDF with pypdf so extract_text() has real input."""
    from pypdf import PdfWriter
    from pypdf.generic import (
        ArrayObject,
        ContentStream,
        DecodedStreamObject,
        DictionaryObject,
        FloatObject,
        NameObject,
        NumberObject,
        TextStringObject,
    )

    writer = PdfWriter()
    for text in pages_text:
        writer.add_blank_page(width=612, height=792)
        page = writer.pages[-1]
        # Build a content stream that draws the text at (72, 720) in Helvetica 12.
        stream = DecodedStreamObject()
        # PDF text-showing operators: BT / Tf / Td / Tj / ET
        stream.set_data(
            f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET".encode("latin-1")
        )
        page[NameObject("/Contents")] = stream
        # Register a font resource on the page so /F1 resolves.
        font = DictionaryObject()
        font[NameObject("/Type")] = NameObject("/Font")
        font[NameObject("/Subtype")] = NameObject("/Type1")
        font[NameObject("/BaseFont")] = NameObject("/Helvetica")
        fonts = DictionaryObject()
        fonts[NameObject("/F1")] = font
        resources = DictionaryObject()
        resources[NameObject("/Font")] = fonts
        page[NameObject("/Resources")] = resources
        # MediaBox is set by add_blank_page, but ensure ContentStream type flows.
        _ = ContentStream, ArrayObject, FloatObject, NumberObject, TextStringObject
    with open(path, "wb") as f:
        writer.write(f)


def test_read_pdf_all_pages(registry: ToolRegistry, tmp_path: Path) -> None:
    pdf = tmp_path / "doc.pdf"
    _write_minimal_pdf(pdf, ["Hello PDF World", "Second Page Text"])
    result = registry.get_tool("read_pdf").function(file_path=str(pdf))
    assert result["success"] is True
    assert result["total_pages"] == 2
    assert result["pages_read"] == 2
    # pypdf may introduce whitespace; just assert substrings.
    assert "Hello PDF World" in result["text"]
    assert "Second Page Text" in result["text"]


def test_read_pdf_page_range(registry: ToolRegistry, tmp_path: Path) -> None:
    pdf = tmp_path / "doc.pdf"
    _write_minimal_pdf(pdf, ["Alpha", "Beta", "Gamma"])
    result = registry.get_tool("read_pdf").function(file_path=str(pdf), pages="1-2")
    assert result["success"] is True
    assert result["pages_read"] == 2
    assert "Alpha" in result["text"]
    assert "Beta" in result["text"]
    assert "Gamma" not in result["text"]


def test_read_pdf_missing_file(registry: ToolRegistry, tmp_path: Path) -> None:
    result = registry.get_tool("read_pdf").function(file_path=str(tmp_path / "nope.pdf"))
    assert result["success"] is False


def test_read_pdf_invalid_pages_returns_error(registry: ToolRegistry, tmp_path: Path) -> None:
    pdf = tmp_path / "doc.pdf"
    _write_minimal_pdf(pdf, ["Only page"])
    result = registry.get_tool("read_pdf").function(file_path=str(pdf), pages="5-7")
    assert result["success"] is False
    assert "no valid pages" in result["error"].lower()


def test_scrape_webpage_accepts_discover_urls_row_dict(registry: ToolRegistry) -> None:
    """Passing a discover_urls entry dict should resolve the string URL (common codegen mistake)."""
    html = "<html><body><p>Hello dresser plans</p></body></html>"
    mock_resp = MagicMock()
    mock_resp.text = html

    row = {"url": "https://example.org/plans", "score": 2}
    with patch.object(ToolRegistry, "_request_with_retry", return_value=mock_resp) as req:
        out = registry.get_tool("scrape_webpage").function(url=row)
    assert out["success"] is True
    assert "dresser" in (out.get("result") or "") or "Hello" in (out.get("result") or "")
    req.assert_called_once()
    assert req.call_args[0][0] == "https://example.org/plans"
    assert out.get("url") == "https://example.org/plans"


def test_scrape_webpage_honors_selector_and_extract_text(registry: ToolRegistry) -> None:
    html = """
    <html><body>
      <main><p>Keep this text</p></main>
      <aside>Ignore this text</aside>
    </body></html>
    """
    mock_resp = MagicMock()
    mock_resp.text = html

    with patch.object(ToolRegistry, "_request_with_retry", return_value=mock_resp):
        out = registry.get_tool("scrape_webpage").function(
            url="https://example.org/page",
            selector="main",
            extract_text=True,
        )

    assert out["success"] is True
    assert "Keep this text" in out["result"]
    assert "Ignore this text" not in out["result"]
    assert out["meta"]["selector"] == "main"


def test_scrape_webpage_returns_html_when_extract_text_false(registry: ToolRegistry) -> None:
    mock_resp = MagicMock()
    mock_resp.text = "<html><body><main><p>Keep</p></main></body></html>"

    with patch.object(ToolRegistry, "_request_with_retry", return_value=mock_resp):
        out = registry.get_tool("scrape_webpage").function(
            url="https://example.org/page",
            selector="main",
            extract_text=False,
        )

    assert out["success"] is True
    assert "<main>" in out["result"]
    assert "<p>Keep</p>" in out["result"]


def test_scrape_webpage_returns_error_for_missing_selector(registry: ToolRegistry) -> None:
    mock_resp = MagicMock()
    mock_resp.text = "<html><body><main>Only main</main></body></html>"

    with patch.object(ToolRegistry, "_request_with_retry", return_value=mock_resp):
        out = registry.get_tool("scrape_webpage").function(
            url="https://example.org/page",
            selector=".missing",
        )

    assert out["success"] is False
    assert "selector" in out["error"].lower()


def test_scrape_webpage_rejects_row_dict_without_url_key(registry: ToolRegistry) -> None:
    out = registry.get_tool("scrape_webpage").function(url={"score": 1})
    assert out["success"] is False
    assert "url" in (out.get("error") or "").lower()


def test_discover_urls_accepts_keywords_as_list(registry: ToolRegistry) -> None:
    html = """<html><body>
    <a href="/dresser-plans">Dresser plans</a>
    </body></html>"""
    mock_resp = MagicMock()
    mock_resp.text = html

    with patch.object(ToolRegistry, "_request_with_retry", return_value=mock_resp):
        out = registry.get_tool("discover_urls").function(
            start_url="https://example.org/",
            keywords=["dresser", "plans"],
            use_sitemap=False,
            max_results=10,
        )
    assert out["success"] is True
    urls = [e["url"] for e in out["urls"]]
    assert any("dresser" in u for u in urls)


def test_discover_urls_page_links_and_keywords(registry: ToolRegistry) -> None:
    html = """<html><body>
    <a href="/about">About</a>
    <a href="/festivals/sci-fi-short">Sci-Fi Short Festival</a>
    </body></html>"""
    mock_resp = MagicMock()
    mock_resp.text = html

    with patch.object(ToolRegistry, "_request_with_retry", return_value=mock_resp):
        out = registry.get_tool("discover_urls").function(
            start_url="https://example.org/",
            keywords="sci-fi festival",
            use_sitemap=False,
            max_results=10,
        )
    assert out["success"] is True
    urls = [e["url"] for e in out["urls"]]
    assert out.get("urls_only") == urls
    assert any("sci-fi" in u for u in urls)
    scores = [e["score"] for e in out["urls"]]
    assert scores == sorted(scores, reverse=True)


def test_discover_urls_requires_scheme_and_host(registry: ToolRegistry) -> None:
    out = registry.get_tool("discover_urls").function(
        start_url="example.org",
        use_sitemap=False,
        use_page_links=False,
    )
    assert out["success"] is False


def test_discover_urls_always_includes_start_url_when_no_links(registry: ToolRegistry) -> None:
    """If the page has no extractable anchors, discovery must still return the entry URL."""
    mock_resp = MagicMock()
    mock_resp.text = "<html><body>No anchors here.</body></html>"

    with patch.object(ToolRegistry, "_request_with_retry", return_value=mock_resp):
        out = registry.get_tool("discover_urls").function(
            start_url="https://example.org/howto/build-dresser",
            keywords="dresser",
            use_sitemap=False,
            use_page_links=True,
            max_results=10,
        )
    assert out["success"] is True
    urls = [e["url"] for e in out["urls"]]
    assert "https://example.org/howto/build-dresser" in urls


def test_discover_urls_start_url_only_when_sitemap_and_links_disabled(registry: ToolRegistry) -> None:
    """No HTTP fetch is required to list the seed page when both optional sources are off."""
    out = registry.get_tool("discover_urls").function(
        start_url="https://example.org/explicit-page",
        use_sitemap=False,
        use_page_links=False,
        max_results=5,
    )
    assert out["success"] is True
    assert out["urls"] == [{"url": "https://example.org/explicit-page", "score": 0}]
    assert out["urls_only"] == ["https://example.org/explicit-page"]


def test_discover_urls_expands_sitemap_index(registry: ToolRegistry) -> None:
    """Sitemap-index XML should be followed one level and child URLs merged.

    Cross-host child URLs must be dropped (same-origin only).
    """
    sitemap_index = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        "<sitemap><loc>https://example.org/sitemap-pages.xml</loc></sitemap>"
        "</sitemapindex>"
    )
    sitemap_pages = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        "<url><loc>https://example.org/festivals/sci-fi</loc></url>"
        "<url><loc>https://example.org/festivals/fantasy</loc></url>"
        "<url><loc>https://other-host.example.com/should-be-dropped</loc></url>"
        "</urlset>"
    )
    homepage_html = (
        "<html><body>"
        "<a href=\"/about\">About</a>"
        "</body></html>"
    )

    def fake_request(url: str, **_kwargs):
        resp = MagicMock()
        if url.endswith("/sitemap.xml"):
            resp.text = sitemap_index
        elif url.endswith("/sitemap-pages.xml"):
            resp.text = sitemap_pages
        else:
            resp.text = homepage_html
        return resp

    with patch.object(ToolRegistry, "_request_with_retry", side_effect=fake_request):
        out = registry.get_tool("discover_urls").function(
            start_url="https://example.org/",
            keywords="sci-fi festival",
            use_sitemap=True,
            use_page_links=True,
            max_results=20,
        )

    assert out["success"] is True
    urls = [entry["url"] for entry in out["urls"]]
    assert "https://example.org/festivals/sci-fi" in urls
    assert "https://example.org/festivals/fantasy" in urls
    # Cross-host loc must be filtered out.
    assert not any("other-host.example.com" in u for u in urls)
    # Same-origin homepage anchor still allowed.
    assert any(u.endswith("/about") for u in urls)


def test_contract_guidance_includes_discover_when_custom_research_steps() -> None:
    """Research-shaped ``custom`` steps still get URL/scrape response contracts."""
    text = build_contract_prompt_guidance(
        {"custom", "generate_text"},
        step_descriptions=[
            "Research dresser plans from reputable woodworking websites and collect sources.",
            "Write summary.md",
        ],
    )
    assert "discover_urls response contract" in text
    assert "scrape_webpage response contract" in text


def test_validate_rejects_materials_extend_scrape_result() -> None:
    bad = '''
tools = ToolRegistry()
scrape_webpage_tool = tools.get_tool("scrape_webpage")
materials = []
r = scrape_webpage_tool.function(url="https://example.org/")
materials.extend(r.get("result"))
'''
    with pytest.raises(ValueError, match=r"materials\.extend"):
        validate_tool_contracts(bad)


def test_request_with_retry_uses_short_connect_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Avoid hanging ~30s×N on TCP connect; refuse/DNS-style errors skip extra tries."""
    seen: list[Any] = []

    def fake_request(method, url, timeout=None, headers=None, **kwargs):
        seen.append(timeout)
        raise requests.ConnectionError(
            "HTTPSConnectionPool(host='x', port=443): Max retries exceeded with url: / "
            '(Caused by NewConnectionError("<…>: Failed to establish a new connection: '
            '[Errno 61] Connection refused"))'
        )

    monkeypatch.setattr(
        "workflowmvp.tools._base.socket.getaddrinfo",
        lambda *_args, **_kwargs: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 0))
        ],
    )
    monkeypatch.setattr("workflowmvp.tools._base.requests.request", fake_request)
    monkeypatch.setattr("workflowmvp.tools._base.time.sleep", lambda *a, **k: None)

    with pytest.raises(RuntimeError, match="after 1 attempt"):
        ToolRegistry._request_with_retry("https://example.com/x", timeout=30, attempts=3)

    assert len(seen) == 1
    connect, read = seen[0]
    assert read == 30.0
    assert connect == min(8.0, 30.0)


def test_request_with_retry_still_retries_transient_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    n = 0

    def fake_request(method, url, timeout=None, headers=None, **kwargs):
        nonlocal n
        n += 1
        if n < 2:
            raise requests.ReadTimeout("stall")
        return _ok_http_response()

    monkeypatch.setattr(
        "workflowmvp.tools._base.socket.getaddrinfo",
        lambda *_args, **_kwargs: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 0))
        ],
    )
    monkeypatch.setattr("workflowmvp.tools._base.requests.request", fake_request)
    monkeypatch.setattr("workflowmvp.tools._base.time.sleep", lambda *a, **k: None)
    ToolRegistry._request_with_retry("https://example.com/", timeout=30, attempts=3)
    assert n == 2


def test_sqlite_query_rejects_write_statements(
    registry: ToolRegistry, tmp_path: Path
) -> None:
    db = tmp_path / "app.db"
    result = registry.get_tool("sqlite_query").function(
        database_path=str(db),
        query="CREATE TABLE users (name TEXT)",
    )

    assert result["success"] is False
    assert "SELECT" in result["error"]


def test_sqlite_insert_rejects_invalid_identifiers(
    registry: ToolRegistry, tmp_path: Path
) -> None:
    db = tmp_path / "app.db"
    result = registry.get_tool("sqlite_insert").function(
        database_path=str(db),
        table="users; DROP TABLE users",
        data={"name": "Alice"},
    )

    assert result["success"] is False
    assert "Invalid table or column" in result["error"]


def test_http_request_rejects_redirect_to_private_ip(
    registry: ToolRegistry, monkeypatch: pytest.MonkeyPatch
) -> None:
    hops = {"n": 0}

    def fake_getaddrinfo(host, *args, **kwargs):
        hostname = str(host).rstrip(".").lower()
        if hostname in {"127.0.0.1", "localhost"}:
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 0))]
        if hostname == "169.254.169.254":
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("169.254.169.254", 0))]
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 0))]

    def fake_request(method, url, timeout=None, headers=None, **kwargs):
        hops["n"] += 1
        assert kwargs.get("allow_redirects") is False
        redirect = MagicMock()
        redirect.status_code = 302
        redirect.ok = False
        redirect.headers = {"Location": "http://127.0.0.1/secret"}
        redirect.is_redirect = True
        redirect.is_permanent_redirect = False
        redirect.raise_for_status = lambda: None
        return redirect

    monkeypatch.setattr("workflowmvp.tools._base.socket.getaddrinfo", fake_getaddrinfo)
    monkeypatch.setattr("workflowmvp.tools._base.requests.request", fake_request)

    result = registry.get_tool("http_request").function(url="https://example.com/start")
    assert result["success"] is False
    assert "blocked" in (result.get("error") or "").lower() or "127.0.0.1" in (
        result.get("error") or ""
    )
    assert hops["n"] == 1


def test_download_rejects_redirect_to_metadata_ip(
    registry: ToolRegistry, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fake_getaddrinfo(host, *args, **kwargs):
        hostname = str(host).rstrip(".").lower()
        if hostname == "169.254.169.254":
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("169.254.169.254", 0))]
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 0))]

    def fake_request(method, url, timeout=None, headers=None, **kwargs):
        redirect = MagicMock()
        redirect.status_code = 302
        redirect.headers = {"Location": "http://169.254.169.254/latest/meta-data"}
        redirect.is_redirect = True
        redirect.raise_for_status = lambda: None
        return redirect

    monkeypatch.setattr("workflowmvp.tools._base.socket.getaddrinfo", fake_getaddrinfo)
    monkeypatch.setattr("workflowmvp.tools._base.requests.request", fake_request)
    result = registry.get_tool("download").function(url="https://example.com/go")
    assert result["success"] is False
    assert result["error"]


def test_wait_rejects_above_cap(registry: ToolRegistry) -> None:
    result = registry.get_tool("wait").function(seconds=120)
    assert result["success"] is False
    assert "capped" in result["error"]


def test_sqlite_query_rejects_pragma(registry: ToolRegistry, tmp_path: Path) -> None:
    db = tmp_path / "app.db"
    result = registry.get_tool("sqlite_query").function(
        database_path=str(db),
        query="PRAGMA table_info(users)",
    )
    assert result["success"] is False
    assert "SELECT" in result["error"]


def test_sqlite_insert_and_select_roundtrip(registry: ToolRegistry, tmp_path: Path) -> None:
    db = tmp_path / "app.db"
    conn_create = __import__("sqlite3").connect(db)
    conn_create.execute("CREATE TABLE users (name TEXT, age INTEGER)")
    conn_create.close()

    inserted = registry.get_tool("sqlite_insert").function(
        database_path=str(db),
        table="users",
        data=[{"name": "Ada", "age": 36}, {"name": "Grace", "age": 85}],
    )
    assert inserted["success"] is True

    queried = registry.get_tool("sqlite_query").function(
        database_path=str(db),
        query="SELECT name FROM users WHERE age > ?",
        params=[40],
    )
    assert queried["success"] is True
    assert queried["results"] == [("Grace",)]
    assert queried["columns"] == ["name"]


def test_sqlite_query_rejects_stacked_statements(
    registry: ToolRegistry, tmp_path: Path
) -> None:
    db = tmp_path / "app.db"
    result = registry.get_tool("sqlite_query").function(
        database_path=str(db),
        query="SELECT 1; DROP TABLE users",
    )
    assert result["success"] is False
    assert "single SELECT" in result["error"]


def test_sqlite_insert_dict_row(registry: ToolRegistry, tmp_path: Path) -> None:
    db = tmp_path / "app.db"
    conn = __import__("sqlite3").connect(db)
    conn.execute("CREATE TABLE users (name TEXT)")
    conn.close()
    result = registry.get_tool("sqlite_insert").function(
        database_path=str(db),
        table="users",
        data={"name": "Ada"},
    )
    assert result["success"] is True


def test_sqlite_insert_rejects_empty_list(registry: ToolRegistry, tmp_path: Path) -> None:
    db = tmp_path / "app.db"
    result = registry.get_tool("sqlite_insert").function(
        database_path=str(db),
        table="users",
        data=[],
    )
    assert result["success"] is False
    assert "No data" in result["error"]


def test_send_email_succeeds_with_mocked_smtp(
    registry: ToolRegistry, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("EMAIL_USER", "a@b.com")
    monkeypatch.setenv("EMAIL_PASSWORD", "secret")
    monkeypatch.setenv("EMAIL_FROM", "a@b.com")
    monkeypatch.chdir(tmp_path)
    (tmp_path / "note.txt").write_text("hi")

    class FakeSMTP:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            self.logged_in = False

        def starttls(self) -> None:
            return None

        def login(self, user: str, password: str) -> None:
            self.logged_in = True

        def sendmail(self, *args: Any, **kwargs: Any) -> None:
            return None

        def quit(self) -> None:
            return None

    monkeypatch.setattr("workflowmvp.tools.notifications.smtplib.SMTP", FakeSMTP)
    result = registry.get_tool("send_email").function(
        recipient="x@y.com",
        subject="t",
        body="",
        attachments="note.txt",
    )
    assert result["success"] is True
    assert "x@y.com" in result["result"]


def test_send_email_ssl_port(
    registry: ToolRegistry, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("EMAIL_USER", "a@b.com")
    monkeypatch.setenv("EMAIL_PASSWORD", "secret")
    monkeypatch.setenv("EMAIL_FROM", "a@b.com")

    class FakeSSL:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            return None

        def login(self, *args: Any, **kwargs: Any) -> None:
            return None

        def sendmail(self, *args: Any, **kwargs: Any) -> None:
            return None

        def quit(self) -> None:
            return None

    monkeypatch.setattr("workflowmvp.tools.notifications.smtplib.SMTP_SSL", FakeSSL)
    result = registry.get_tool("send_email").function(
        recipient="x@y.com",
        subject="t",
        body="hi",
        smtp_port=465,
    )
    assert result["success"] is True


def test_send_notification_skips_without_notify_send(
    registry: ToolRegistry, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("workflowmvp.tools.notifications.os.name", "posix")
    monkeypatch.setattr("workflowmvp.tools.notifications.sys.platform", "linux")
    monkeypatch.setattr("workflowmvp.tools.notifications.shutil.which", lambda _name: None)
    result = registry.get_tool("send_notification").function(
        title="Hi", message="There"
    )
    assert result["success"] is True
    assert result.get("note")


def test_send_notification_osascript_success(
    registry: ToolRegistry, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("workflowmvp.tools.notifications.os.name", "posix")
    monkeypatch.setattr("workflowmvp.tools.notifications.sys.platform", "darwin")

    def fake_run(*args: Any, **kwargs: Any) -> Any:
        completed = MagicMock()
        completed.returncode = 0
        completed.stderr = ""
        completed.stdout = ""
        return completed

    monkeypatch.setattr("workflowmvp.tools.notifications.subprocess.run", fake_run)
    result = registry.get_tool("send_notification").function(title='Say "hi"', message="ok")
    assert result["success"] is True


def test_generate_text_uses_llm_client(
    registry: ToolRegistry, monkeypatch: pytest.MonkeyPatch
) -> None:
    class FakeClient:
        provider = "gemini"

        def is_configured(self) -> bool:
            return True

        def generate_text(self, prompt: str, max_tokens: int = 1000, temperature: float = 0.7) -> str:
            assert "haiku" in prompt
            return "  five seven five  "

    monkeypatch.setattr(ToolRegistry, "_get_llm_client", lambda self: FakeClient())
    result = registry.get_tool("generate_text").function(prompt="write a haiku", max_tokens=32)
    assert result["success"] is True
    assert result["result"] == "five seven five"


def test_generate_text_missing_key(registry: ToolRegistry, monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeClient:
        provider = "gemini"

        def is_configured(self) -> bool:
            return False

    monkeypatch.setattr(ToolRegistry, "_get_llm_client", lambda self: FakeClient())
    result = registry.get_tool("generate_text").function(prompt="x")
    assert result["success"] is False
    assert "GEMINI_API_KEY" in result["error"]


def test_get_current_time_named_zone(registry: ToolRegistry) -> None:
    result = registry.get_tool("get_current_time").function(timezone="America/New_York")
    assert result["success"] is True
    assert result["timezone"] == "America/New_York"
    assert "T" in result["iso"]


def test_get_current_time_invalid_zone(registry: ToolRegistry) -> None:
    result = registry.get_tool("get_current_time").function(timezone="Not/AZone")
    assert result["success"] is False


def test_wait_rejects_negative(registry: ToolRegistry) -> None:
    result = registry.get_tool("wait").function(seconds=-1)
    assert result["success"] is False


def test_wait_rejects_non_numeric(registry: ToolRegistry) -> None:
    result = registry.get_tool("wait").function(seconds="nope")  # type: ignore[arg-type]
    assert result["success"] is False


def test_run_command_blocks_deny_list(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("WORKFLOW_SAFETY_PROFILE", "full")
    registry = ToolRegistry()
    tool = registry.get_tool("run_command")
    assert tool is not None
    result = tool.function(command="sudo shutdown -h now")
    assert result["success"] is False
    assert result.get("blocked") is True


def test_run_command_echo_in_full_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("WORKFLOW_SAFETY_PROFILE", "full")
    registry = ToolRegistry()
    tool = registry.get_tool("run_command")
    assert tool is not None
    result = tool.function(command="echo hello-rlimit", timeout=10)
    assert result["success"] is True
    assert "hello-rlimit" in (result.get("stdout") or "")


def test_applescript_literal_escapes_quotes() -> None:
    escaped = ToolRegistry._applescript_literal('say "hi"\\path')
    assert '\\"' in escaped
    assert "\\\\" in escaped
