"""Small finance symbol hints shared by parser and finance tools."""

from __future__ import annotations

import re

_COMMON_SYMBOL_ALIASES = (
    (re.compile(r"s\s*&\s*p\s*(\d\s*)?500\b", re.IGNORECASE), "^GSPC"),
    (re.compile(r"\bsp\s*500\b", re.IGNORECASE), "^GSPC"),
    (re.compile(r"\bsp500\b", re.IGNORECASE), "^GSPC"),
    (re.compile(r"\bnasdaq\s+composite\b", re.IGNORECASE), "^IXIC"),
    (re.compile(r"\bnasdaq\s*100\b", re.IGNORECASE), "^NDX"),
    (re.compile(r"\bdow\s+jones\b", re.IGNORECASE), "^DJI"),
    (re.compile(r"\bdjia\b", re.IGNORECASE), "^DJI"),
    (re.compile(r"\bspy\b", re.IGNORECASE), "SPY"),
)


def resolve_finance_symbol_hint(text: str) -> str:
    """Return a Yahoo Finance symbol only when the text provides a strong hint.

    This intentionally avoids broad natural-language company-name resolution.
    Ambiguous names such as "Apple" should be handled by an LLM-assisted parse
    or a dedicated resolver, not by the generic workflow parser.
    """
    value = text.strip()
    for pattern, symbol in _COMMON_SYMBOL_ALIASES:
        if pattern.search(value):
            return symbol

    match = re.search(r"\^[A-Za-z]{1,10}\b", value)
    if match:
        return match.group(0).upper()

    match = re.search(r"\b[A-Za-z]{1,6}-USD\b", value, re.IGNORECASE)
    if match:
        symbol = match.group(0)
        return symbol[:-4].upper() + "-USD"

    match = re.search(r"\$([A-Za-z]{1,5}(?:\.[A-Za-z])?)\b", value)
    if match:
        return match.group(1).upper()

    match = re.search(
        r"\b(?:ticker|symbol)(?:\s+is)?\s+([A-Za-z]{1,5}(?:\.[A-Za-z])?)\b",
        value,
        re.IGNORECASE,
    )
    if match:
        return match.group(1).upper()

    return ""
