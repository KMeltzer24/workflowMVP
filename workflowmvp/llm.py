"""Unified LLM client.

Wraps Gemini, Groq, and OpenRouter behind a single `generate_text` method so
`workflowmvp.agent` and the `generate_text` tool in `workflowmvp.tools` don't
have to duplicate provider routing logic.

Design goals:
  - Zero magic: the caller decides temperature + token budget.
  - Lazy: Gemini client is only constructed if/when needed.
  - Honest failures: raise on misconfiguration, return '' only when the model
    itself returned empty content.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, Optional

import requests

SUPPORTED_PROVIDERS = ("gemini", "groq", "openrouter")

DEFAULT_MODELS = {
    "gemini": "gemini-2.5-flash",
    "groq": "llama-3.3-70b-versatile",
    "openrouter": "meta-llama/llama-3.1-70b-instruct",
}

MODEL_ENV_KEYS = {
    "gemini": "GEMINI_MODEL",
    "groq": "GROQ_MODEL",
    "openrouter": "OPENROUTER_MODEL",
}

API_KEY_ENV_KEYS = {
    "gemini": "GEMINI_API_KEY",
    "groq": "GROQ_API_KEY",
    "openrouter": "OPENROUTER_API_KEY",
}

# OpenAI-compatible chat endpoints for providers that are not Gemini.
CHAT_COMPLETION_URLS = {
    "groq": "https://api.groq.com/openai/v1/chat/completions",
    "openrouter": "https://openrouter.ai/api/v1/chat/completions",
}


def required_api_key_name(provider: str) -> str:
    """Return the env var name that holds the API key for `provider`."""
    return API_KEY_ENV_KEYS.get(provider, "GEMINI_API_KEY")


def _quiet_third_party_loggers() -> None:
    """Lower httpx / Google GenAI SDK noise when running workflows in the UI."""
    flag = (os.getenv("WORKFLOW_QUIET_LOGGERS") or "").strip().lower()
    if flag not in ("1", "true", "yes"):
        return
    for name in (
        "httpx",
        "httpcore",
        "urllib3",
        "google_genai",
        "google_genai.models",
    ):
        logging.getLogger(name).setLevel(logging.WARNING)


class LLMClient:
    """Provider-agnostic text generation.

    Instantiate once and call `generate_text(prompt, max_tokens, temperature)`.
    Raises ValueError on misconfiguration (unknown provider, missing key).
    """

    def __init__(
        self,
        provider: Optional[str] = None,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
    ) -> None:
        resolved_provider = (provider or os.getenv("LLM_PROVIDER", "gemini")).strip().lower()
        if resolved_provider not in SUPPORTED_PROVIDERS:
            raise ValueError(
                f"Unsupported provider '{resolved_provider}'. "
                f"Choose from: {', '.join(SUPPORTED_PROVIDERS)}."
            )
        self.provider = resolved_provider
        self.api_key = api_key or os.getenv(API_KEY_ENV_KEYS[self.provider])
        self.model = (
            model
            or os.getenv(MODEL_ENV_KEYS[self.provider])
            or DEFAULT_MODELS[self.provider]
        )
        self._gemini_client: Any = None

    # -- public --------------------------------------------------------------

    def is_configured(self) -> bool:
        return bool(self.api_key)

    def require_configured(self) -> None:
        if not self.is_configured():
            raise ValueError(
                f"{required_api_key_name(self.provider)} is required "
                f"for provider '{self.provider}'."
            )

    def generate_text(
        self,
        prompt: str,
        max_tokens: int = 1000,
        temperature: float = 0.7,
    ) -> str:
        """Send `prompt` to the configured backend and return the text body.

        Returns '' if the backend returned no content. Raises ValueError for
        config errors and HTTP errors for network failures.
        """
        self.require_configured()
        _quiet_third_party_loggers()
        if self.provider == "gemini":
            return self._call_gemini(prompt, max_tokens, temperature)
        return self._call_openai_compatible(prompt, max_tokens, temperature)

    # -- internal ------------------------------------------------------------

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
        return response.text or ""

    def _call_openai_compatible(
        self, prompt: str, max_tokens: int, temperature: float
    ) -> str:
        url = CHAT_COMPLETION_URLS[self.provider]
        extra_headers: Dict[str, str] = {}
        if self.provider == "openrouter":
            extra_headers = {
                "HTTP-Referer": os.getenv("OPENROUTER_SITE_URL", "http://localhost:5050"),
                "X-Title": os.getenv("OPENROUTER_APP_NAME", "WorkflowMVP"),
            }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            **extra_headers,
        }
        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        response = requests.post(url, headers=headers, json=payload, timeout=60)
        response.raise_for_status()
        data = response.json()
        choices = data.get("choices") or []
        if not choices:
            raise ValueError(f"{self.provider} returned no choices.")
        message = choices[0].get("message") or {}
        content = message.get("content", "")
        if isinstance(content, list):
            return "\n".join(
                chunk.get("text", "")
                for chunk in content
                if isinstance(chunk, dict)
            ).strip()
        return str(content)
