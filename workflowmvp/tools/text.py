"""Text-processing tools: deterministic extraction and transformation."""

from __future__ import annotations

import re
from typing import Any, Dict, Optional

from ._base import P, Tool, _BaseToolRegistry


class TextToolsMixin(_BaseToolRegistry):
    def _register_text_tools(self) -> None:
        self.register_tool(Tool(
            name="extract_regex",
            description="Extract regex matches from text.",
            function=self._extract_regex,
            category="text",
            parameters={
                "text": P("Input text to search", required=True),
                "pattern": P("Regular expression pattern", required=True),
                "group": P("Optional capture group index or name"),
                "flags": P("Optional regex flags string using i, m, s, x"),
            },
        ))
        self.register_tool(Tool(
            name="replace_text",
            description="Replace occurrences of text with another string.",
            function=self._replace_text,
            category="text",
            parameters={
                "text": P("Input text", required=True),
                "old": P("Substring to replace", required=True),
                "new": P("Replacement string", required=True),
                "count": P("Maximum replacements (default: -1 for all)"),
            },
        ))
        self.register_tool(Tool(
            name="split_text",
            description="Split text by delimiter, whitespace, or lines.",
            function=self._split_text,
            category="text",
            parameters={
                "text": P("Input text", required=True),
                "delimiter": P("Optional delimiter. Uses whitespace when omitted."),
                "lines": P("If true, split into lines instead of using delimiter"),
            },
        ))

    @staticmethod
    def _regex_flags(flags: Optional[str]) -> int:
        out = 0
        for flag in str(flags or "").lower():
            if flag == "i":
                out |= re.IGNORECASE
            elif flag == "m":
                out |= re.MULTILINE
            elif flag == "s":
                out |= re.DOTALL
            elif flag == "x":
                out |= re.VERBOSE
        return out

    def _extract_regex(
        self,
        text: str,
        pattern: str,
        group: Any = None,
        flags: Optional[str] = None,
    ) -> Dict[str, Any]:
        try:
            compiled = re.compile(pattern, self._regex_flags(flags))
            group_key: Any = group
            if isinstance(group_key, str) and group_key.isdigit():
                group_key = int(group_key)
            matches = [
                match.group(group_key) if group_key is not None else match.group(0)
                for match in compiled.finditer(str(text or ""))
            ]
            return {
                "success": True,
                "result": matches,
                "matches": matches,
                "count": len(matches),
                "meta": {"count": len(matches), "pattern": pattern},
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    def _replace_text(
        self,
        text: str,
        old: str,
        new: str,
        count: int = -1,
    ) -> Dict[str, Any]:
        try:
            replaced = str(text or "").replace(str(old), str(new), int(count))
            return {
                "success": True,
                "result": replaced,
                "text": replaced,
                "meta": {"count": count},
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    def _split_text(
        self,
        text: str,
        delimiter: Optional[str] = None,
        lines: bool = False,
    ) -> Dict[str, Any]:
        try:
            raw = str(text or "")
            if bool(lines):
                parts = raw.splitlines()
            elif delimiter is None:
                parts = raw.split()
            else:
                parts = raw.split(str(delimiter))
            return {
                "success": True,
                "result": parts,
                "parts": parts,
                "count": len(parts),
                "meta": {"count": len(parts)},
            }
        except Exception as e:
            return {"success": False, "error": str(e)}
