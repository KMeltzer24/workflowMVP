"""Credential plumbing for the web layer.

Keeps the allow-list and API-key resolution out of ``main.py`` so the routes stay
short and the rules are easy to test.

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
    "GEMINI_API_KEY",
    "GEMINI_MODEL",
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


def resolve_gemini_api_key(creds: Dict[str, str]) -> Optional[str]:
    return creds.get("GEMINI_API_KEY") or os.getenv("GEMINI_API_KEY")


def resolve_gemini_model(creds: Dict[str, str]) -> Optional[str]:
    if creds.get("GEMINI_MODEL"):
        return creds["GEMINI_MODEL"].strip()
    return os.getenv("GEMINI_MODEL") or None


def missing_gemini_api_key_hint() -> str:
    """Env var documented in README / Settings."""
    return "GEMINI_API_KEY"


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
