"""AI-shaped tools: LLM text generation and Jinja2 templating."""

from __future__ import annotations

from typing import Any, Dict, Optional

from ._base import Tool


class AIToolsMixin:
    def _get_llm_client(self):  # type: ignore[no-untyped-def]
        """Memoize LLMClient per ToolRegistry process."""
        client = getattr(self, "_cached_llm_client", None)
        if client is not None:
            return client
        from ..llm import LLMClient

        client = LLMClient()
        self._cached_llm_client = client
        return client

    def _register_ai_tools(self) -> None:
        self.register_tool(Tool(
            name="generate_text",
            description=(
                "Generate text using the configured AI model (Gemini / Groq / OpenRouter). "
                "Use for writing, summarising, translating, classifying, formatting data as prose, "
                "or any task that requires language understanding. "
                "Pass the full instruction in 'prompt'; the model returns plain text."
            ),
            function=self._generate_text,
            parameters={
                "prompt": "Full instruction for the AI (e.g. 'Write a limerick about 5432.10')",
                "max_tokens": "Maximum tokens to generate (default: 1000)",
            },
        ))
        self.register_tool(Tool(
            name="render_template",
            description=(
                "Render a Jinja2 template string with a variables dict. "
                "Safe autoescape is ON for HTML-like templates. "
                "Use for email bodies, reports, and any structured text output."
            ),
            function=self._render_template,
            parameters={
                "template": "Jinja2 template string (e.g. 'Hello {{ name }}!')",
                "variables": "Dict of values to substitute (e.g. {'name': 'World'})",
                "autoescape": "Set False to disable HTML autoescape (default: True)",
            },
        ))

    def _generate_text(
        self, prompt: str, max_tokens: int = 1000
    ) -> Dict[str, Any]:
        """Call the configured LLM to generate text via the shared LLMClient."""
        try:
            client = self._get_llm_client()
            if not client.is_configured():
                from ..llm import required_api_key_name

                return {
                    "success": False,
                    "error": (
                        f"No API key found for provider '{client.provider}'. "
                        f"Set {required_api_key_name(client.provider)} in .env."
                    ),
                }
            text = client.generate_text(prompt, max_tokens=max_tokens, temperature=0.7)
            return {"success": True, "result": (text or "").strip()}
        except Exception as exc:
            return {"success": False, "error": str(exc)}

    def _render_template(
        self,
        template: str,
        variables: Optional[Dict[str, Any]] = None,
        autoescape: bool = True,
    ) -> Dict[str, Any]:
        """Render a Jinja2 template string with sandboxed execution."""
        try:
            from jinja2 import StrictUndefined
            from jinja2.sandbox import SandboxedEnvironment
        except ImportError:
            return {
                "success": False,
                "error": "Jinja2 is not installed. Run: pip install jinja2",
            }
        try:
            env = SandboxedEnvironment(
                autoescape=bool(autoescape),
                undefined=StrictUndefined,
            )
            tmpl = env.from_string(template or "")
            rendered = tmpl.render(**(variables or {}))
            return {
                "success": True,
                "rendered": rendered,
                "result": rendered,
            }
        except Exception as e:
            return {"success": False, "error": str(e)}
