"""Tests for the Gemini LLMClient (workflowmvp.llm)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from workflowmvp.llm import (
    DEFAULT_GEMINI_MODEL,
    LLMClient,
    gemini_response_to_text,
    required_api_key_name,
)


def _clear_llm_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in ("GEMINI_API_KEY", "GEMINI_MODEL"):
        monkeypatch.delenv(key, raising=False)


def test_required_api_key_name() -> None:
    assert required_api_key_name() == "GEMINI_API_KEY"
    assert required_api_key_name(None) == "GEMINI_API_KEY"
    assert required_api_key_name("ignored") == "GEMINI_API_KEY"


def test_defaults_to_gemini_and_default_model(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_llm_env(monkeypatch)
    client = LLMClient()
    assert client.provider == "gemini"
    assert client.model == DEFAULT_GEMINI_MODEL
    assert client.is_configured() is False


def test_require_configured_raises_without_key(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_llm_env(monkeypatch)
    client = LLMClient()
    with pytest.raises(ValueError, match="GEMINI_API_KEY"):
        client.require_configured()


def test_gemini_response_to_text_ignores_non_list_candidates_on_mocks() -> None:
    """MagicMock ``candidates`` is truthy but not iterable as real parts — fall back to .text."""
    r = MagicMock()
    r.candidates = MagicMock()
    r.text = "only text"
    assert gemini_response_to_text(r) == "only text"


def test_joins_candidate_parts(monkeypatch: pytest.MonkeyPatch) -> None:
    """Concatenate candidates[].content.parts[].text — response.text alone can truncate."""
    _clear_llm_env(monkeypatch)
    client = LLMClient(api_key="fake-key")

    part_a = MagicMock()
    part_a.text = "The S&P reached quite a high,\n"
    part_b = MagicMock()
    part_b.text = "At seven thousand, a cheerful sigh."
    content = MagicMock()
    content.parts = [part_a, part_b]
    cand = MagicMock()
    cand.content = content
    fake_response = MagicMock()
    fake_response.candidates = [cand]
    fake_response.text = "The S&P reached quite a high,\n"

    fake_google_client = MagicMock()
    fake_google_client.models.generate_content.return_value = fake_response

    with patch("workflowmvp.llm.LLMClient._gemini", return_value=fake_google_client):
        result = client.generate_text("limerick", max_tokens=256, temperature=0.7)

    assert "seven thousand" in result
    fake_google_client.models.generate_content.assert_called_once()


def test_gemini_delegates_to_google_client(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_llm_env(monkeypatch)
    client = LLMClient(api_key="fake-key")

    fake_response = MagicMock()
    fake_response.text = "response text"
    fake_google_client = MagicMock()
    fake_google_client.models.generate_content.return_value = fake_response

    fake_genai_module = MagicMock()
    fake_genai_module.Client.return_value = fake_google_client

    with patch.dict(
        "sys.modules",
        {"google": MagicMock(genai=fake_genai_module), "google.genai": fake_genai_module},
    ):
        with patch("google.genai.types.GenerateContentConfig") as fake_cfg:
            fake_cfg.return_value = MagicMock()
            with patch("workflowmvp.llm.LLMClient._gemini", return_value=fake_google_client):
                result = client.generate_text("prompt", max_tokens=100, temperature=0.1)

    assert result == "response text"
    fake_google_client.models.generate_content.assert_called_once()


def test_model_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_llm_env(monkeypatch)
    monkeypatch.setenv("GEMINI_MODEL", "custom-gemini")
    assert LLMClient().model == "custom-gemini"
