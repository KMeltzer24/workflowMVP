"""Explicit finance symbol parsing shared by parser and finance tools."""

from __future__ import annotations

import re


def resolve_finance_symbol_hint(text: str) -> str:
    """Return a Yahoo Finance symbol only when the user provides explicit syntax.

    Natural-language identifiers such as "spy", "S&P 500", "Apple", or
    "bitcoin" should be normalized by the AI planning/repair layer, not by a
    growing deterministic alias table.
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

    return ""
