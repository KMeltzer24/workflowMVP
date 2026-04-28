"""Parse JSON values embedded in LLM prose (Gemini ``generate_text`` output).

Generated workflows must **not** call ``json.loads`` on ``result`` verbatim: models prepend
clarifying sentences, emit fenced `` ```json `` blocks, and sometimes truncate mid-value. Prefer::

    from workflowmvp.json_llm import extract_first_json_value

    raw = resp.get("result") or ""
    data = extract_first_json_value(raw)  # dict | list | None

Use a **large enough** ``max_tokens`` when the model must emit long JSON arrays.
"""

from __future__ import annotations

import json
import re
from typing import Any

_JSON_DECODER = json.JSONDecoder()


def extract_first_json_value(raw: str) -> Any | None:
    """Return the first JSON object or array decodable from *raw*, or ``None``.

    Handles preamble before ``{``/``[``, trailing commentary, and markdown fences around
    *complete* JSON. Truncated output still fails — increase ``max_tokens`` or shorten input.
    """
    if not raw or not str(raw).strip():
        return None
    text = raw.strip()
    text = re.sub(r"^\s*```(?:json)?\s*", "", text, flags=re.IGNORECASE | re.MULTILINE)
    text = re.sub(r"\s*```\s*$", "", text, flags=re.MULTILINE)
    text = text.strip()
    for i, ch in enumerate(text):
        if ch not in "[{":
            continue
        try:
            value, _end = _JSON_DECODER.raw_decode(text[i:])
            return value
        except json.JSONDecodeError:
            continue
    return None


__all__ = ["extract_first_json_value"]
