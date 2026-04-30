"""Explicit finance symbol parsing shared by parser and finance tools."""

from __future__ import annotations

import re

_COMMON_FINANCE_SYMBOLS = {
    "bitcoin": "BTC-USD",
    "btc": "BTC-USD",
    "ethereum": "ETH-USD",
    "eth": "ETH-USD",
    "spy": "SPY",
}


def resolve_finance_symbol_hint(text: str) -> str:
    """Return a Yahoo Finance symbol for explicit syntax or very common assets.

    This intentionally avoids resolving arbitrary company names. The small
    common set covers identifiers that users reasonably expect to work without
    AI repair while keeping broad name-to-symbol lookup out of the parser.
    """
    value = text.strip()

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

    lowered = value.lower()
    if re.search(r"\bs\s*&\s*p\s*500\b|\bsp\s*500\b|\bsp500\b", lowered):
        return "^GSPC"

    for name, symbol in _COMMON_FINANCE_SYMBOLS.items():
        if re.search(rf"\b{re.escape(name)}\b", lowered):
            return symbol

    return ""
