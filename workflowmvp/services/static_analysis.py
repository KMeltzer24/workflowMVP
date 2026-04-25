"""AST helpers used by ``/api/validate-workflow`` to inspect generated scripts.

These run *without* executing the script, so the UI can preview which
tools and imports the workflow would use before the user spends API
credits running it.
"""

from __future__ import annotations

import ast
from typing import List


def extract_tools_from_source(source: str) -> List[str]:
    """Walk the AST of ``source`` and return sorted unique ``get_tool('x')`` args.

    Picks up both ``tools.get_tool("x")`` and bare ``get_tool("x")``. Only
    string literals are collected; dynamic names like ``get_tool(var)`` are
    ignored because we can't know them statically.
    """
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []
    names: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        is_get_tool = (
            isinstance(func, ast.Attribute) and func.attr == "get_tool"
        ) or (isinstance(func, ast.Name) and func.id == "get_tool")
        if not is_get_tool or not node.args:
            continue
        first = node.args[0]
        if isinstance(first, ast.Constant) and isinstance(first.value, str):
            names.add(first.value)
    return sorted(names)


def extract_top_level_imports(source: str) -> List[str]:
    """Return sorted unique top-level imported module names from ``source``."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []
    modules: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.Import):
            for alias in node.names:
                modules.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module.split(".")[0])
    return sorted(modules)
