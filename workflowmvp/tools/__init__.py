"""Tool registry split by category.

The package exposes the same surface as the old monolithic ``tools.py``:

- :class:`Tool` — dataclass for each registered tool.
- :class:`ToolRegistry` — composes the per-category mixins so generated
  scripts see the same public API as before (``registry.get_tool(name)``).

Tests that monkey-patch ``workflowmvp.tools.requests.get`` continue to work:
``import requests`` here keeps the module attribute reachable by that path.
"""

from __future__ import annotations

import requests  # re-exported for monkey-patching in tests

from ._base import Tool, _BaseToolRegistry
from .ai import AIToolsMixin
from .archive import ArchiveToolsMixin
from .database import DatabaseToolsMixin
from .filesystem import FilesystemToolsMixin
from .finance import FinanceToolsMixin
from .network import NetworkToolsMixin
from .notifications import NotificationToolsMixin
from .system import SystemToolsMixin


class ToolRegistry(
    FilesystemToolsMixin,
    NetworkToolsMixin,
    FinanceToolsMixin,
    AIToolsMixin,
    NotificationToolsMixin,
    SystemToolsMixin,
    DatabaseToolsMixin,
    ArchiveToolsMixin,
    _BaseToolRegistry,
):
    """Concrete registry composed from per-category mixins.

    The order in :meth:`_register_default_tools` controls how tools appear in
    the agent's prompt; keep it stable so prompt diffs stay reviewable.
    """

    def _register_default_tools(self) -> None:
        self._register_filesystem_tools()
        self._register_network_tools()
        self._register_finance_tools()
        self._register_ai_tools()
        self._register_notification_tools()
        self._register_system_tools()
        self._register_database_tools()
        self._register_archive_tools()


__all__ = ["Tool", "ToolRegistry", "requests"]
