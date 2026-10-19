"""System-shaped tools: wait, clock, and the opt-in shell escape hatch."""

from __future__ import annotations

import subprocess
import time
from datetime import UTC, datetime
from typing import Any, Dict
from zoneinfo import ZoneInfo

from ._base import _WAIT_MAX_SECONDS, P, Tool, _BaseToolRegistry


class SystemToolsMixin(_BaseToolRegistry):
    def _register_system_tools(self) -> None:
        self.register_tool(Tool(
            name="wait",
            description="Wait for a specified amount of time",
            function=self._wait,
            category="time",
            parameters={"seconds": P("Number of seconds to wait", required=True)},
        ))
        self.register_tool(Tool(
            name="get_current_time",
            description=(
                "Return the current date/time in an IANA timezone (e.g. America/New_York) "
                "as ISO 8601 string and Unix timestamp. Use UTC if unsure."
            ),
            function=self._get_current_time,
            category="time",
            parameters={
                "timezone": P("IANA zone name (default: UTC), e.g. America/Los_Angeles"),
            },
        ))

        # ``run_command`` is only registered when the user has explicitly opted
        # into the ``full`` safety profile. The deny-list is a footgun-catcher,
        # not a real sandbox — dropping the tool entirely is the honest default.
        if self.safety_profile == "full":
            self.register_tool(Tool(
                name="run_command",
                description=(
                    "Execute a system shell command. Available only when "
                    "WORKFLOW_SAFETY_PROFILE=full. Commands run in the sandbox "
                    "cwd but have full user privileges — not a security boundary."
                ),
                function=self._run_command,
                category="system",
                side_effects=("shell",),
                safety_level="full",
                parameters={
                    "command": P("Command to execute", required=True),
                    "timeout": P("Timeout in seconds (default: 30)"),
                },
            ))

    def _wait(self, seconds: int) -> Dict[str, Any]:
        try:
            secs = float(seconds)
            if secs < 0:
                return {"success": False, "error": "seconds must be non-negative"}
            if secs > _WAIT_MAX_SECONDS:
                return {
                    "success": False,
                    "error": f"wait is capped at {_WAIT_MAX_SECONDS} seconds",
                }
            time.sleep(secs)
            return {"success": True, "waited": secs}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def _get_current_time(self, timezone: str = "UTC") -> Dict[str, Any]:
        try:
            tz_name = (timezone or "UTC").strip()
            if tz_name.upper() in ("UTC", "GMT", "Z", "ZULU"):
                now = datetime.now(UTC)
                tz_label = "UTC"
            else:
                tz = ZoneInfo(tz_name)
                now = datetime.now(tz)
                tz_label = tz_name
            iso = now.isoformat()
            return {
                "success": True,
                "iso": iso,
                "timezone": tz_label,
                "unix": int(now.timestamp()),
                "result": iso,
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    def _run_command(self, command: str, timeout: int = 30) -> Dict[str, Any]:
        try:
            blocked_reason = self._blocked_command_reason(command)
            if blocked_reason:
                return {"success": False, "error": blocked_reason, "blocked": True}
            if self.safety_profile == "safe":
                return {
                    "success": False,
                    "error": "run_command is disabled in safe mode",
                    "blocked": True,
                }
            result = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=self.sandbox_root or None,
            )
            return {
                "success": result.returncode == 0,
                "stdout": result.stdout,
                "stderr": result.stderr,
                "returncode": result.returncode,
            }
        except subprocess.TimeoutExpired:
            return {
                "success": False,
                "error": f"Command timed out after {timeout} seconds",
            }
        except Exception as e:
            return {"success": False, "error": str(e)}
