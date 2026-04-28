"""Shared base for the tool registry.

Holds the cross-cutting helpers every category mixin needs:

- ``Tool`` dataclass and tool registration plumbing.
- HTTP request retry, browser headers, sandbox path resolver.
- Command deny-list and the response normalizer.

The category mixins (``filesystem``, ``network``, etc.) provide the
implementations and a ``_register_<category>_tools`` hook that the concrete
``ToolRegistry`` calls in order.
"""

from __future__ import annotations

import os
import re
import time
import warnings
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional

# macOS system Python is commonly linked against LibreSSL, which triggers a
# noisy urllib3 warning on import. Silence only that exact warning.
warnings.filterwarnings(
    "ignore",
    message=r"urllib3 v2 only supports OpenSSL 1\.1\.1\+.*LibreSSL.*",
)

import requests  # noqa: E402

# ``requests`` applies a single float to *both* connect and read timeouts. For hosts that
# blackhole TCP (no RST), connect can burn the full budget per attempt × retries (~90s for
# ``timeout=30``, ``attempts=3``). Use a short connect phase by default; override via env.
_HTTP_CONNECT_TIMEOUT = float(os.getenv("WORKFLOW_HTTP_CONNECT_TIMEOUT", "8"))

TimeoutLike = int | float | tuple[float, float]


def _http_timeout_pair(timeout: TimeoutLike) -> tuple[float, float]:
    """Return ``(connect, read)`` timeouts for ``requests``."""
    if isinstance(timeout, tuple):
        if len(timeout) != 2:
            raise ValueError("timeout tuple must be (connect, read)")
        c, r = float(timeout[0]), float(timeout[1])
    else:
        r = float(timeout)
        c = min(_HTTP_CONNECT_TIMEOUT, r)
    if c <= 0 or r <= 0:
        raise ValueError("HTTP timeouts must be positive")
    return (c, r)


def _http_error_unlikely_to_recover(exc: BaseException) -> bool:
    """True when repeating the same GET is unlikely to help (fail fast, no backoff wait)."""
    msg = str(exc).lower()
    return (
        "connection refused" in msg
        or "errno 61" in msg
        or "name or service not known" in msg
        or "nodename nor servname" in msg
        or "failed to resolve" in msg
    )


@dataclass
class Tool:
    """Represents a workflow tool exposed to generated scripts."""

    name: str
    description: str
    function: Callable
    parameters: Dict[str, str]


class _BaseToolRegistry:
    """Cross-cutting helpers shared by every category mixin."""

    COMMAND_DENY_PATTERNS: List[str] = [
        r"\brm\s+-rf\b",
        r"\bsudo\b",
        r"\bmkfs\b",
        r"\bshutdown\b",
        r"\breboot\b",
        r"\bkillall\b",
        r">\s*/",
        r":\(\)\s*\{",
    ]

    _BROWSER_HEADERS: Dict[str, str] = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
    }

    def __init__(self, safety_profile: Optional[str] = None) -> None:
        self.tools: Dict[str, Tool] = {}
        profile = (
            safety_profile or os.getenv("WORKFLOW_SAFETY_PROFILE", "safe")
        ).strip().lower()
        self.safety_profile = profile if profile in {"safe", "full"} else "safe"
        sandbox_root = os.getenv("WORKFLOW_OUTPUT_DIR")
        self.sandbox_root = os.path.abspath(sandbox_root) if sandbox_root else None
        self._register_default_tools()

    # ----- registration plumbing -----------------------------------------

    def _register_default_tools(self) -> None:
        """Populate :attr:`tools`. Concrete registry composes mixins."""

    def register_tool(self, tool: Tool) -> None:
        """Register a tool, wrapping it in the response normalizer."""
        self.tools[tool.name] = Tool(
            name=tool.name,
            description=tool.description,
            function=self._wrap_tool_function(tool.name, tool.function),
            parameters=tool.parameters,
        )

    def get_tool(self, name: str) -> Optional[Tool]:
        return self.tools.get(name)

    def list_tools(self) -> List[Tool]:
        return list(self.tools.values())

    def _wrap_tool_function(self, tool_name: str, func: Callable) -> Callable:
        def wrapped(*args, **kwargs):  # type: ignore[no-untyped-def]
            try:
                raw = func(*args, **kwargs)
            except Exception as exc:  # pragma: no cover - defensive
                raw = {"success": False, "error": str(exc)}
            return self._normalize_tool_response(tool_name, raw)

        return wrapped

    def _normalize_tool_response(self, tool_name: str, payload: Any) -> Dict[str, Any]:
        """Force every tool result through a stable envelope.

        Contract:
          - success: bool
          - error: str | None
          - result: Any
          - meta: dict
        """
        if not isinstance(payload, dict):
            payload = {"success": True, "result": payload}

        normalized = dict(payload)
        success = bool(normalized.get("success"))
        normalized["success"] = success

        if success:
            inferred_result = (
                normalized.get("result")
                if "result" in normalized
                else normalized.get("content")
                if "content" in normalized
                else normalized.get("message")
            )
            normalized["result"] = inferred_result
            normalized["error"] = None
        else:
            normalized["result"] = normalized.get("result")
            normalized["error"] = str(normalized.get("error") or "Unknown tool error")

        meta = normalized.get("meta")
        if not isinstance(meta, dict):
            meta = {}
        meta.setdefault("tool", tool_name)
        normalized["meta"] = meta

        return normalized

    # ----- shared helpers -------------------------------------------------

    @classmethod
    def _request_with_retry(
        cls,
        url: str,
        timeout: TimeoutLike = 30,
        attempts: int = 3,
        base_backoff: float = 0.4,
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        """GET ``url`` with exponential backoff for transient request failures."""
        merged_headers = {**cls._BROWSER_HEADERS, **(headers or {})}
        timeout_pair = _http_timeout_pair(timeout)
        last_exc: Optional[Exception] = None
        for attempt in range(1, attempts + 1):
            try:
                response = requests.get(
                    url, timeout=timeout_pair, headers=merged_headers
                )
                response.raise_for_status()
                return response
            except requests.RequestException as exc:
                last_exc = exc
                if attempt == attempts or _http_error_unlikely_to_recover(exc):
                    break
                time.sleep(base_backoff * (2 ** (attempt - 1)))
        tried = attempt  # loop always assigns on last iteration
        att_word = "attempt" if tried == 1 else "attempts"
        raise RuntimeError(f"Request failed after {tried} {att_word}: {last_exc}")

    def _sandbox_path(self, raw_path: str) -> str:
        """Resolve a user-supplied path and enforce the run sandbox boundary."""
        if not raw_path:
            raise ValueError("Path is required")
        if self.sandbox_root is None:
            return raw_path

        candidate = (
            raw_path
            if os.path.isabs(raw_path)
            else os.path.join(self.sandbox_root, raw_path)
        )
        normalized = os.path.abspath(candidate)
        if not (
            normalized == self.sandbox_root
            or normalized.startswith(self.sandbox_root + os.sep)
        ):
            raise PermissionError(
                f"Path '{raw_path}' is outside sandbox '{self.sandbox_root}'"
            )
        return normalized

    @classmethod
    def _blocked_command_reason(cls, command: str) -> Optional[str]:
        lowered = command.lower()
        for pattern in cls.COMMAND_DENY_PATTERNS:
            if re.search(pattern, lowered):
                return f"Command blocked by safety policy ({pattern})"
        return None
