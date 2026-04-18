"""Tests for the unified LLMClient adapter (workflowmvp.llm)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from workflowmvp.llm import (
    API_KEY_ENV_KEYS,
    CHAT_COMPLETION_URLS,
    DEFAULT_MODELS,
    LLMClient,
    required_api_key_name,
)


def _clear_all_llm_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in ("LLM_PROVIDER", *API_KEY_ENV_KEYS.values()):
        monkeypatch.delenv(key, raising=False)


def test_required_api_key_name_mapping() -> None:
    assert required_api_key_name("gemini") == "GEMINI_API_KEY"
    assert required_api_key_name("groq") == "GROQ_API_KEY"
    assert required_api_key_name("openrouter") == "OPENROUTER_API_KEY"
    assert required_api_key_name("bogus") == "GEMINI_API_KEY"


def test_rejects_unknown_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_all_llm_env(monkeypatch)
    with pytest.raises(ValueError, match="Unsupported provider"):
        LLMClient(provider="not-a-provider")


def test_defaults_to_gemini_and_default_model(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_all_llm_env(monkeypatch)
    client = LLMClient()
    assert client.provider == "gemini"
    assert client.model == DEFAULT_MODELS["gemini"]
    assert client.is_configured() is False


def test_require_configured_raises_without_key(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_all_llm_env(monkeypatch)
    client = LLMClient()
    with pytest.raises(ValueError, match="GEMINI_API_KEY"):
        client.require_configured()


def test_groq_uses_openai_compatible_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_all_llm_env(monkeypatch)
    client = LLMClient(provider="groq", api_key="gsk_test", model="llama-3.3-70b")

    fake_response = MagicMock()
    fake_response.raise_for_status.return_value = None
    fake_response.json.return_value = {
        "choices": [{"message": {"content": "hi from groq"}}]
    }

    with patch("workflowmvp.llm.requests.post", return_value=fake_response) as mock_post:
        result = client.generate_text("hello", max_tokens=50, temperature=0.3)

    assert result == "hi from groq"
    args, kwargs = mock_post.call_args
    assert args[0] == CHAT_COMPLETION_URLS["groq"]
    assert kwargs["headers"]["Authorization"] == "Bearer gsk_test"
    assert kwargs["json"]["model"] == "llama-3.3-70b"
    assert kwargs["json"]["temperature"] == 0.3
    assert kwargs["json"]["max_tokens"] == 50


def test_openrouter_adds_ranking_headers(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_all_llm_env(monkeypatch)
    monkeypatch.setenv("OPENROUTER_SITE_URL", "https://example.com")
    monkeypatch.setenv("OPENROUTER_APP_NAME", "TestApp")
    client = LLMClient(provider="openrouter", api_key="sk-or-test")

    fake_response = MagicMock()
    fake_response.raise_for_status.return_value = None
    fake_response.json.return_value = {
        "choices": [{"message": {"content": "ok"}}]
    }

    with patch("workflowmvp.llm.requests.post", return_value=fake_response) as mock_post:
        client.generate_text("hi")

    _, kwargs = mock_post.call_args
    assert kwargs["headers"]["HTTP-Referer"] == "https://example.com"
    assert kwargs["headers"]["X-Title"] == "TestApp"


def test_raises_on_empty_choices(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_all_llm_env(monkeypatch)
    client = LLMClient(provider="groq", api_key="gsk_test")
    fake_response = MagicMock()
    fake_response.raise_for_status.return_value = None
    fake_response.json.return_value = {"choices": []}

    with patch("workflowmvp.llm.requests.post", return_value=fake_response):
        with pytest.raises(ValueError, match="no choices"):
            client.generate_text("hi")


def test_gemini_delegates_to_google_client(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_all_llm_env(monkeypatch)
    client = LLMClient(provider="gemini", api_key="fake-key")

    fake_response = MagicMock()
    fake_response.text = "response text"
    fake_google_client = MagicMock()
    fake_google_client.models.generate_content.return_value = fake_response

    # Patch the lazy import path used by _gemini().
    fake_genai_module = MagicMock()
    fake_genai_module.Client.return_value = fake_google_client

    with patch.dict(
        "sys.modules",
        {"google": MagicMock(genai=fake_genai_module), "google.genai": fake_genai_module},
    ):
        with patch("google.genai.types.GenerateContentConfig") as fake_cfg:
            fake_cfg.return_value = MagicMock()
            # Import is deferred, so set the attribute explicitly.
            with patch("workflowmvp.llm.LLMClient._gemini", return_value=fake_google_client):
                result = client.generate_text("prompt", max_tokens=100, temperature=0.1)

    assert result == "response text"
    fake_google_client.models.generate_content.assert_called_once()


def test_content_list_is_joined(monkeypatch: pytest.MonkeyPatch) -> None:
    """Some OpenAI-compatible endpoints return content as a list of parts."""
    _clear_all_llm_env(monkeypatch)
    client = LLMClient(provider="groq", api_key="gsk_test")

    fake_response = MagicMock()
    fake_response.raise_for_status.return_value = None
    fake_response.json.return_value = {
        "choices": [
            {
                "message": {
                    "content": [
                        {"text": "hello "},
                        {"text": "world"},
                    ]
                }
            }
        ]
    }
    with patch("workflowmvp.llm.requests.post", return_value=fake_response):
        result = client.generate_text("hi")
    assert result == "hello \nworld"
