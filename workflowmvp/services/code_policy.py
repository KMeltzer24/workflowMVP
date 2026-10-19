"""AST policy for generated workflow scripts.

This is a denylist on imports and dangerous calls, not an interpreter jail.
Generated code still runs as a normal Python process.
"""

from __future__ import annotations

import ast
from typing import Optional

from workflowmvp.tool_contracts import (
    _collect_generate_text_locals,
    _get_tool_name_from_call,
    _prompt_value_grounding_error,
)

BANNED_MODULES = {
    "subprocess",
    "requests",
    "bs4",
    "pickle",
    "pathos",
}

BANNED_FROM_NAMES = {
    ("os", "system"),
    ("os", "popen"),
    ("os", "exec"),
    ("os", "execv"),
    ("os", "execve"),
    ("os", "spawn"),
    ("os", "spawnl"),
    ("os", "spawnlp"),
    ("os", "spawnv"),
    ("os", "spawnve"),
}

BANNED_CALL_NAMES = {"eval", "exec", "compile", "__import__"}


def _module_root(name: str | None) -> str:
    return (name or "").split(".", 1)[0]


def _banned_import_error(tree: ast.AST) -> Optional[str]:
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = _module_root(alias.name)
                if root in BANNED_MODULES:
                    return (
                        f"Import of {root!r} is not allowed in generated workflows. "
                        "Use ToolRegistry helpers instead of raw process/HTTP/pickle APIs."
                    )
        elif isinstance(node, ast.ImportFrom):
            root = _module_root(node.module)
            if root in BANNED_MODULES:
                return (
                    f"Import of {root!r} is not allowed in generated workflows. "
                    "Use ToolRegistry helpers instead of raw process/HTTP/pickle APIs."
                )
            if node.module == "os" or (node.module or "").startswith("os."):
                for alias in node.names:
                    if ("os", alias.name) in BANNED_FROM_NAMES:
                        return (
                            f"Importing os.{alias.name} is not allowed in generated workflows."
                        )
    return None


def _banned_call_error(tree: ast.AST) -> Optional[str]:
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Name) and func.id in BANNED_CALL_NAMES:
            return (
                f"Call to {func.id}() is not allowed in generated workflows."
            )
        if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
            if func.value.id == "os" and ("os", func.attr) in BANNED_FROM_NAMES:
                return f"Call to os.{func.attr}() is not allowed in generated workflows."
            if func.value.id == "pickle":
                return "pickle is not allowed in generated workflows."
    return None


def validate_import_policy(code: str) -> None:
    """Raise ValueError when generated code uses banned imports or calls."""
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return
    err = _banned_import_error(tree) or _banned_call_error(tree)
    if err:
        raise ValueError(err)


def validate_generate_text_report_grounding(code: str) -> None:
    """Reject meta-only generate_text prompts that ask for a report without sources."""
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return

    gen_locals = _collect_generate_text_locals(tree)

    class Visitor(ast.NodeVisitor):
        def __init__(self, generate_text_vars: set[str]) -> None:
            self._generate_text_vars = generate_text_vars
            self.error: Optional[str] = None

        def visit_Call(self, node: ast.Call) -> None:
            if self.error is not None:
                return
            func = node.func
            if not isinstance(func, ast.Attribute) or func.attr != "function":
                self.generic_visit(node)
                return
            inner = func.value
            is_generate_text = False
            if isinstance(inner, ast.Call):
                is_generate_text = _get_tool_name_from_call(inner) == "generate_text"
            elif isinstance(inner, ast.Name) and inner.id in self._generate_text_vars:
                is_generate_text = True
            if not is_generate_text:
                self.generic_visit(node)
                return
            prompt_kw = next((k for k in node.keywords if k.arg == "prompt"), None)
            if prompt_kw is None:
                self.generic_visit(node)
                return
            err = _prompt_value_grounding_error(prompt_kw.value)
            if err:
                self.error = err
            self.generic_visit(node)

    visitor = Visitor(gen_locals)
    visitor.visit(tree)
    if visitor.error:
        raise ValueError(visitor.error)


def validate_generated_code_policy(code: str) -> None:
    validate_import_policy(code)
    validate_generate_text_report_grounding(code)
