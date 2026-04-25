"""Credential plumbing for the web layer.

Keeps the allow-list and provider-resolution logic out of ``main.py`` so
the routes stay short and the rules are easy to test.

The web layer never persists request credentials — they are forwarded into
subprocess environment variables and forgotten when the run completes.
"""

from __future__ import annotations

import json
import os
from typing import Any, Dict, Optional

# Allow-list of credential keys the web layer will inject into subprocess
# environments. Anything else in the request body is dropped.
ALLOWED_CRED_KEYS = {
    "LLM_PROVIDER",
    "LLM_MODEL",
    "GEMINI_API_KEY",
    "GROQ_API_KEY",
    "OPENROUTER_API_KEY",
    "GROQ_MODEL",
    "OPENROUTER_MODEL",
    "EMAIL_USER",
    "EMAIL_PASSWORD",
    "EMAIL_FROM",
    "SMTP_SERVER",
    "SMTP_PORT",
}


def sanitize_credentials(raw: Optional[Dict[str, Any]]) -> Dict[str, str]:
    """Keep only allow-listed credential keys with non-empty string values."""
    if not raw or not isinstance(raw, dict):
        return {}
    out: Dict[str, str] = {}
    for key, value in raw.items():
        if key not in ALLOWED_CRED_KEYS:
            continue
        if value is None:
            continue
        text = str(value).strip()
        if text:
            out[key] = text
    return out


def resolve_llm_provider(creds: Dict[str, str]) -> str:
    provider = (
        creds.get("LLM_PROVIDER") or os.getenv("LLM_PROVIDER") or "gemini"
    ).strip().lower()
    return provider if provider in {"gemini", "groq", "openrouter"} else "gemini"


def resolve_llm_model(provider: str, creds: Dict[str, str]) -> Optional[str]:
    if creds.get("LLM_MODEL"):
        return creds["LLM_MODEL"]
    if provider == "gemini":
        return creds.get("GEMINI_MODEL") or os.getenv("GEMINI_MODEL")
    if provider == "groq":
        return creds.get("GROQ_MODEL") or os.getenv("GROQ_MODEL")
    return creds.get("OPENROUTER_MODEL") or os.getenv("OPENROUTER_MODEL")


def resolve_api_key(provider: str, creds: Dict[str, str]) -> Optional[str]:
    """Resolve provider-specific API key. Request creds take precedence."""
    if provider == "groq":
        return creds.get("GROQ_API_KEY") or os.getenv("GROQ_API_KEY")
    if provider == "openrouter":
        return creds.get("OPENROUTER_API_KEY") or os.getenv("OPENROUTER_API_KEY")
    return creds.get("GEMINI_API_KEY") or os.getenv("GEMINI_API_KEY")


def missing_llm_key(provider: str) -> str:
    return {
        "gemini": "GEMINI_API_KEY",
        "groq": "GROQ_API_KEY",
        "openrouter": "OPENROUTER_API_KEY",
    }.get(provider, "GEMINI_API_KEY")


def creds_from_form_or_json(raw: Any) -> Dict[str, Any]:
    """Parse a credentials blob from JSON body or multipart form field."""
    if not raw:
        return {}
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
            return parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            return {}
    return {}
