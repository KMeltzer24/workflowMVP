"""Shared metadata for registered workflow tools."""

from __future__ import annotations

from typing import Dict

# Tool name -> category. Categories drive prompt grouping and the web registry
# filters returned by /api/tools.
TOOL_CATEGORIES: Dict[str, str] = {
    # filesystem & files
    "read_file": "filesystem",
    "write_file": "filesystem",
    "append_file": "filesystem",
    "list_files": "filesystem",
    "create_directory": "filesystem",
    "copy_file": "filesystem",
    "move_file": "filesystem",
    "delete_file": "filesystem",
    "read_csv": "filesystem",
    "write_csv": "filesystem",
    "read_xlsx": "filesystem",
    "write_xlsx": "filesystem",
    "read_json": "filesystem",
    "write_json": "filesystem",
    "read_pdf": "filesystem",
    # archive
    "compress_files": "archive",
    "extract_archive": "archive",
    # network
    "download": "network",
    "http_request": "network",
    "scrape_webpage": "network",
    "discover_urls": "network",
    # finance
    "fetch_stock_price": "finance",
    # ai
    "generate_text": "ai",
    "render_template": "ai",
    # time
    "wait": "time",
    "get_current_time": "time",
    # comms
    "send_email": "comms",
    "send_notification": "comms",
    # system
    "run_command": "system",
    # database
    "sqlite_query": "database",
    "sqlite_insert": "database",
}

CATEGORY_ORDER = (
    "filesystem",
    "archive",
    "network",
    "finance",
    "ai",
    "time",
    "comms",
    "system",
    "database",
)

CATEGORY_LABELS: Dict[str, str] = {
    "filesystem": "Files & I/O",
    "archive": "Archive",
    "network": "Network & Web",
    "finance": "Finance",
    "ai": "AI & Templating",
    "time": "Time",
    "comms": "Communications",
    "system": "System",
    "database": "Database",
}


def tool_category(tool_name: str) -> str:
    """Return the registry category for a tool name."""
    from workflowmvp.tools import ToolRegistry

    tool = ToolRegistry().get_tool(tool_name)
    if tool is not None and tool.category and tool.category != "general":
        return tool.category
    return TOOL_CATEGORIES.get(tool_name, "system")
