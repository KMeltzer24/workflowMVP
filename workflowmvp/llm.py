"""Google Gemini client for text generation.

Used by :class:`workflowmvp.agent.WorkflowAgent` and the ``generate_text`` tool
(:mod:`workflowmvp.tools.ai`).
"""

from __future__ import annotations

import logging
import os
from typing import Any

DEFAULT_GEMINI_MODEL = "gemini-2.5-flash"


def gemini_response_to_text(response: Any) -> str:
    """Extract plain text from a ``google.genai`` ``generate_content`` response.

    Concatenates ``candidates[].content.parts[].text`` when present — ``response.text``
    alone can be incomplete on multi-part completions. Matches :class:`LLMClient` behavior.
    """
    chunks: list[str] = []
    raw_candidates = getattr(response, "candidates", None)
    candidates: tuple[Any, ...] = ()
    if isinstance(raw_candidates, (list, tuple)):
        candidates = tuple(raw_candidates)
    for cand in candidates:
        content = getattr(cand, "content", None)
        parts = getattr(content, "parts", None) if content is not None else None
        if not parts:
            continue
        for part in parts:
            fragment = getattr(part, "text", None)
            if fragment:
                chunks.append(fragment)
    if chunks:
        return "\n".join(chunks).strip()
    direct = getattr(response, "text", None)
    return (direct or "").strip()


def required_api_key_name(_provider: str | None = None) -> str:
    """Env var that holds the Gemini API key."""
    return "GEMINI_API_KEY"


def _suppress_noisy_client_loggers() -> None:
    for name in (
        "httpx",
        "httpcore",
        "urllib3",
        "google_genai",
        "google_genai.models",
    ):
        logging.getLogger(name).setLevel(logging.WARNING)


class LLMClient:
    """Gemini-backed text generation via ``generate_text``."""

    def __init__(
        self,
        provider: str | None = None,
        api_key: str | None = None,
        model: str | None = None,
    ) -> None:
        _ = provider  # historical signature — only Gemini is supported
        self.provider = "gemini"
        self.api_key = api_key or os.getenv("GEMINI_API_KEY")
        self.model = (
            model
            or os.getenv("GEMINI_MODEL")
            or DEFAULT_GEMINI_MODEL
        )
        self._gemini_client: Any = None

    def is_configured(self) -> bool:
        return bool(self.api_key)

    def require_configured(self) -> None:
        if not self.is_configured():
            raise ValueError(
                f"{required_api_key_name()} is required for text generation "
                "(set GEMINI_API_KEY)."
            )

    def generate_text(
        self,
        prompt: str,
        max_tokens: int = 1000,
        temperature: float = 0.7,
    ) -> str:
        self.require_configured()
        _suppress_noisy_client_loggers()
        return self._call_gemini(prompt, max_tokens, temperature)

    def _gemini(self) -> Any:
        if self._gemini_client is None:
            from google import genai as google_genai

            self._gemini_client = google_genai.Client(api_key=self.api_key)
        return self._gemini_client

    def _call_gemini(self, prompt: str, max_tokens: int, temperature: float) -> str:
        from google.genai import types as genai_types

        response = self._gemini().models.generate_content(
            model=self.model,
            contents=prompt,
            config=genai_types.GenerateContentConfig(
                temperature=temperature,
                max_output_tokens=max_tokens,
            ),
        )
        return gemini_response_to_text(response)
