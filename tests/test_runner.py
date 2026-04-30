"""Tests for runner service helpers."""

from __future__ import annotations

from workflowmvp.services.runner import build_redactor, secret_values_from_env


def test_redactor_replaces_secret_values() -> None:
    redact = build_redactor({"GEMINI_API_KEY": "abc123SECRET"})

    assert redact("key=abc123SECRET") == "key=[REDACTED]"


def test_redactor_ignores_short_values() -> None:
    redact = build_redactor({"SMTP_SERVER": "smtp.io", "EMAIL_PASSWORD": "short"})

    assert redact("smtp.io short") == "smtp.io short"


def test_redactor_does_not_hide_non_secret_email_addresses() -> None:
    redact = build_redactor(
        {
            "EMAIL_USER": "kevinmeltzer1@gmail.com",
            "EMAIL_FROM": "kevinmeltzer1@gmail.com",
            "EMAIL_PASSWORD": "long-enough-secret",
        }
    )

    assert (
        redact("Sent email to kevinmeltzer1@gmail.com")
        == "Sent email to kevinmeltzer1@gmail.com"
    )


def test_redactor_leaves_unrelated_text_unchanged() -> None:
    redact = build_redactor({"EMAIL_PASSWORD": "long-enough-secret"})

    assert redact("nothing sensitive here") == "nothing sensitive here"


def test_redactor_handles_overlapping_values_longest_first() -> None:
    values = secret_values_from_env(
        {
            "GEMINI_API_KEY": "prefix-secret-token",
            "EMAIL_PASSWORD": "secret-token",
        }
    )
    redact = build_redactor(
        {
            "GEMINI_API_KEY": "prefix-secret-token",
            "EMAIL_PASSWORD": "secret-token",
        }
    )

    assert values == ["prefix-secret-token", "secret-token"]
    assert redact("prefix-secret-token secret-token") == "[REDACTED] [REDACTED]"
