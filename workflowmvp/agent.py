"""
AI Agent — Generates executable Python code from parsed workflow steps.

Code generation uses **Google Gemini** via :mod:`workflowmvp.llm`.
"""

import json
import re
from typing import Any, Dict, List, Optional, Tuple

from .json_llm import extract_first_json_value
from .llm import LLMClient, required_api_key_name
from .parser import WorkflowStep
from .prompts import load_prompt_template
from .services.code_policy import validate_generated_code_policy
from .services.tool_metadata import CATEGORY_LABELS, CATEGORY_ORDER, tool_category
from .tool_contracts import (
    build_contract_prompt_guidance,
    build_retry_contract_guidance,
    validate_tool_contracts,
)
from .tools import ToolRegistry

# Token budget for code generation (output). Large scripts need headroom.
_CODE_GEN_MAX_TOKENS = 8192
# Extra output tokens on automatic retry after a syntax failure.
_CODE_GEN_RETRY_EXTRA_TOKENS = 4096
# Token budget for parse-assist (shorter JSON output, less needed).
_PARSE_ASSIST_MAX_TOKENS = 2000


# Per-tool guidance snippets. Only the entries whose key (a tool name OR a
# category) appears in the workflow are emitted in the system prompt. This
# keeps the prompt short for small workflows while preserving the deep
# guidance the agent relies on for the trickier tools.
_TOOL_GUIDANCE: Dict[str, str] = {
    "send_email": (
        "EMAIL — send_email: recipient, subject, body (plain text); optional attachments (path or list of paths). "
        "Short body like \"See attached.\" is fine when files are attached. Never invent email_from — omit or "
        "use os.getenv('EMAIL_FROM'). No sign-offs (\"Best regards\", etc.) unless the step asks. "
        "Copy the recipient **exactly** from the step (spelling/digits); do not substitute.\n"
        "   email_tool = tools.get_tool('send_email')\n"
        "   email_tool.function(recipient='you@example.com', subject='...', body='...', attachments=['report.md'])"
    ),
    "generate_text": (
        "AI TEXT — gen = tools.get_tool('generate_text'); r = gen.function(prompt=..., max_tokens=...); "
        "read r.get('result','') when r.get('success'). Size max_tokens to output (big JSON/lists often 4096–8192; "
        "short prose 512–2048).\n"
        "If output should be structured JSON buried in prose/fences: **never** json.loads(...) the raw string; "
        "use workflowmvp.json_llm.extract_first_json_value and validate dict|list.\n"
        "Research/report steps must include excerpted scraped/API text in the prompt; meta-only prompts "
        "fabricate. If scraping/API failed, do not invent placeholder sources/data — abort before export/email.\n"
    ),
    "scrape_webpage": (
        "SCRAPING — scrape_webpage strips HTML tags and returns clean readable text (up to 4000 chars).\n"
        "   **URL argument:** pass a string URL, or a **`discover_urls` row dict** (the tool reads `url` from it). "
        "When iterating `response['urls']`, either use **`for e in urls: scrape(..., url=e.get('url'))`** or "
        "**`urls_only`** so you pass plain strings.\n"
        "   **URL priority:** (1) exact URL from the step / parameters; (2) else discover candidates, then "
        "scrape the best. Slice before passing to generate_text."
    ),
    "discover_urls": (
        "URL DISCOVERY — discover_urls: `start_url` must be an official https homepage (not google/bing), "
        "`keywords` from the step. Merges sitemap + same-origin links; `start_url` is always a candidate. "
        "Read `urls` (`{url, score}`) or `urls_only`; `result` is a debug string, not a URL list. "
        "If the ranked list is thin, scrape `start_url`."
    ),
    "http_request": (
        "HTTP / REST APIs — use http_request for any POST/PUT/DELETE or API with auth:\n"
        "   api = tools.get_tool('http_request')\n"
        "   r = api.function(url='https://...', method='POST', body={'key': 'value'})"
    ),
    "fetch_stock_price": (
        "STOCK — prefer fetch_stock_price over scraping. Use the **exact** ticker from the step (^GSPC, SPY, "
        "BTC-USD, …). Latest close: fetch_stock_price(ticker='...', period='1d'); read price/ticker/currency from "
        "the dict. For multi-bar comparisons (first vs last in one window), `import yfinance as yf` and use "
        "yf.Ticker(...).history(period=...) — fetch_stock_price is not a full series API."
    ),
    "read_pdf": (
        "PDF — read_pdf: pass file_path and optional pages (range string or list). Extracted text is "
        "in result (and text)."
    ),
    "render_template": (
        "TEMPLATES — render_template: pass template (Jinja2 string) and variables dict. Missing variable "
        "names fail (StrictUndefined). Output string is in result (and rendered)."
    ),
    "read_json": (
        "JSON FILES — read_json / write_json for structured config and API payloads (prefer over manual "
        "string concat):\n"
        "   rj = tools.get_tool('read_json')\n"
        "   r = rj.function(file_path='config.json')\n"
        "   data = r.get('data') if r.get('success') else {}\n"
        "   wj = tools.get_tool('write_json')\n"
        "   wj.function(file_path='out.json', data={'ok': True}, indent=2)"
    ),
    "append_file": "APPEND / LOG LINES — append_file adds text without reading the whole file first.",
    "hash_file": "FILE INTEGRITY — hash_file(file_path='backup.zip', algorithm='sha256') returns hex_digest.",
    "get_current_time": (
        "DATE & TIME — get_current_time(timezone='…') returns iso, unix, timezone (any **IANA** name). "
        "Use for clocks in workflows and emails; combine with `zoneinfo` in code when you need "
        "arithmetic without an extra dependency."
    ),
}

# Always-on guidance (regardless of which tools the workflow uses).
_ALWAYS_ON_GUIDANCE_KEYS = ("generate_text",)


class WorkflowAgent:
    """Generates executable Python code from structured workflow steps using an LLM."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        provider: Optional[str] = None,
    ):
        self._llm = LLMClient(provider=provider, api_key=api_key, model=model)
        self.provider = self._llm.provider
        self.model = self._llm.model
        self.api_key = self._llm.api_key
        self.tool_registry = ToolRegistry()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def generate_workflow_code(
        self, steps: List[WorkflowStep], output_file: str = "generated_workflow.py"
    ) -> str:
        """Generate and write executable Python code from parsed workflow steps."""
        if not self.api_key:
            key_name = self.required_api_key_name(self.provider)
            raise ValueError(
                f"{key_name} is required for code generation. Set it in .env or pass via credentials."
            )

        base_prompt = f"{self._create_system_prompt(steps)}\n\n{self._create_user_prompt(steps)}"
        generated_code, err = self._generate_and_validate_code(base_prompt)
        if err is not None:
            raise err

        with open(output_file, "w", encoding="utf-8") as f:
            f.write(generated_code)

        return generated_code

    def _generate_and_validate_code(
        self, base_prompt: str
    ) -> Tuple[str, Optional[ValueError]]:
        """Call the LLM once; on empty or syntax error, retry with a completion nudge."""
        last_problem: Optional[ValueError] = None
        for attempt in range(2):
            extra = ""
            if attempt == 1:
                extra = (
                    "\n\n## FIX REQUIRED\n"
                    "The previous answer was rejected: not valid Python (truncated, unfinished, "
                    "or a syntax/logic validation error). Output the **entire** script again as a single runnable "
                    "file: every import through a complete `if __name__ == \"__main__\":` block, "
                    "with all compound statements having non-empty bodies. No markdown.\n"
                    "\nTool contract fixes:\n"
                    f"{build_retry_contract_guidance()}\n"
                    "Do NOT emit placeholder logic that says custom steps produced no output and then "
                    "continues to side effects (e.g., sending email with 'no data'). Operationalize the "
                    "steps with tools when possible; otherwise fail fast with a clear log and stop.\n"
                )
            budget = _CODE_GEN_MAX_TOKENS + (attempt * _CODE_GEN_RETRY_EXTRA_TOKENS)
            raw = self._generate_text(base_prompt + extra, max_tokens=budget)
            code = self._extract_python_script(raw)
            if not code:
                last_problem = ValueError("Model returned empty code.")
                continue
            try:
                self._validate_generated_python(code)
                return code, None
            except ValueError as exc:
                last_problem = exc
                continue
        return "", last_problem or ValueError("Code generation failed.")

    def improve_parsed_steps(
        self, workflow_text: str, rule_steps: List[WorkflowStep]
    ) -> List[WorkflowStep]:
        """Use the configured LLM to improve low-confidence parser output.

        Takes the rule-based draft steps as context and asks the model to
        produce a corrected JSON array with better action/parameter mapping.
        """
        if not self.api_key:
            key_name = self.required_api_key_name(self.provider)
            raise ValueError(f"{key_name} is required for AI-assisted parsing.")

        tool_names = [tool.name for tool in self.tool_registry.list_tools()]
        rule_payload = [
            {
                "step_id": step.step_id,
                "description": step.description,
                "action": step.action,
                "parameters": step.parameters,
                "dependencies": step.dependencies,
            }
            for step in rule_steps
        ]

        prompt = f"""You improve workflow parsing quality. Convert user text into strict JSON.

Allowed actions: {", ".join(tool_names)}, custom

Return ONLY a valid JSON array. Each object must have these keys:
  step_id, description, action, parameters (object), dependencies (array)

Rules:
- Preserve step order and numbering.
- Prefer a specific allowed action over "custom" when reasonable.
- Include obvious parameters from the text (url, file_path, recipient, ticker, etc.).
- Normalize identifiers into the format expected by the chosen tool when the user intent is clear.
  Examples: finance price checks should use Yahoo-compatible tickers such as "SPY",
  "^GSPC" for the S&P 500 index, or "BTC-USD" for Bitcoin USD.
- dependencies must reference earlier step_ids only.
- Do not invent runtime facts such as dates, prices, event times, statistics, or scraped content.
  Only normalize identifiers and parameters needed to call tools.
- Do not write Python, JavaScript, pseudocode, or implementation snippets in any field.
- Do not use templating syntax such as "{{step_1.output}}"; use dependencies to express data flow.
- Keep parameter values short: strings, numbers, booleans, lists, or objects only.
- No markdown, no code fences, no commentary — valid raw JSON only.

Original workflow text:
{workflow_text}

Rule-parser draft (for reference):
{json.dumps(rule_payload, indent=2)}""".strip()

        text = (self._generate_text(prompt, max_tokens=_PARSE_ASSIST_MAX_TOKENS) or "").strip()
        payload = self._extract_json_array(text)

        valid_actions = set(tool_names) | {"custom"}
        improved: List[WorkflowStep] = []
        for idx, item in enumerate(payload, start=1):
            if not isinstance(item, dict):
                continue
            action = str(item.get("action") or "custom").strip()
            if action not in valid_actions:
                # The model invented an action that the registry can't run.
                # Down-grade rather than passing a bogus name to codegen.
                action = "custom"
            raw_params = item.get("parameters")
            raw_deps = item.get("dependencies")
            parameters: Dict[str, Any] = raw_params if isinstance(raw_params, dict) else {}
            dependencies: List[str] = raw_deps if isinstance(raw_deps, list) else []
            improved.append(
                WorkflowStep(
                    step_id=str(item.get("step_id") or f"step_{idx}"),
                    description=str(item.get("description") or "").strip(),
                    action=action,
                    parameters=parameters,
                    dependencies=dependencies,
                )
            )
        return improved

    @staticmethod
    def required_api_key_name(provider: str) -> str:
        return required_api_key_name(provider)

    # ------------------------------------------------------------------
    # LLM call (delegates to LLMClient — agent-specific temp defaults only)
    # ------------------------------------------------------------------

    def _generate_text(self, prompt: str, max_tokens: int = _CODE_GEN_MAX_TOKENS) -> str:
        """Send a prompt to the configured LLM and return the text response."""
        # Code generation and parse-assist both want near-deterministic output,
        # hence temperature=0.1. The generate_text tool uses a higher default.
        return self._llm.generate_text(prompt, max_tokens=max_tokens, temperature=0.1)

    # ------------------------------------------------------------------
    # Output extraction helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_python_script(text: str) -> str:
        """Pull clean Python code out of raw model output.

        Strategy:
        1. If fenced code blocks exist, take the longest one.
        2. Otherwise strip any partial fences and scan for the first Python line.
        """
        raw = text.strip()
        if not raw:
            return ""

        fenced = re.findall(r"```(?:python)?\s*([\s\S]*?)```", raw, flags=re.IGNORECASE)
        if fenced:
            return max((b.strip() for b in fenced), key=len, default="")

        raw = re.sub(r"^```[a-zA-Z]*\n?", "", raw)
        raw = re.sub(r"\n?```$", "", raw)

        starters = ("import ", "from ", "def ", "class ", "if __name__", "tools = ", "logger = ", "load_dotenv(")
        for i, line in enumerate(raw.splitlines()):
            stripped = line.strip()
            if stripped.startswith(starters) or ("=" in stripped and not stripped.startswith("#")):
                return "\n".join(raw.splitlines()[i:]).strip()
        return raw.strip()

    @staticmethod
    def _validate_generated_python(code: str) -> None:
        """Reject malformed scripts and known tool-contract pitfalls."""
        try:
            compile(code, "<generated_workflow>", "exec")
        except SyntaxError as exc:
            raise ValueError(
                f"Invalid Python from model (line {exc.lineno}: {exc.msg})."
            ) from exc

        # Reject "looks successful but did no work" placeholders for custom
        # upstream steps. These scripts frequently end by sending an email that
        # just states no data was generated.
        copout_markers = (
            "custom step, no concrete output generated",
            "did not generate specific data",
            "no specific research findings or material costs",
        )
        lowered = code.lower()
        if any(marker in lowered for marker in copout_markers):
            raise ValueError(
                "Placeholder custom-step output detected. Implement the step with tools "
                "or fail fast before side effects."
            )

        validate_generated_code_policy(code)
        validate_tool_contracts(code)

    @staticmethod
    def _extract_json_array(text: str) -> List[dict]:
        """Pull a JSON array out of raw model output, tolerating prose and fenced JSON."""
        parsed = extract_first_json_value(text)
        if isinstance(parsed, list):
            return parsed

        stripped = re.sub(r"^```[a-zA-Z]*\n?", "", text.strip())
        stripped = re.sub(r"\n?```$", "", stripped)
        try:
            retry = json.loads(stripped)
            if isinstance(retry, list):
                return retry
        except json.JSONDecodeError:
            pass
        match = re.search(r"\[[\s\S]*\]", stripped)
        if not match:
            raise ValueError("AI parse assistant returned invalid JSON.")
        outer = json.loads(match.group(0))
        if not isinstance(outer, list):
            raise ValueError("AI parse assistant returned non-list JSON.")
        return outer

    # ------------------------------------------------------------------
    # Prompt construction
    # ------------------------------------------------------------------

    def _build_grouped_tool_listing(self) -> str:
        """Group the available-tools listing by category for readability.

        The LLM still sees every tool; grouping keeps scanning cost lower than
        a single flat alphabetical list.
        """
        by_category: Dict[str, List[str]] = {}
        for tool in self.tool_registry.list_tools():
            category = tool_category(tool.name)
            line = (
                f"- {tool.name}: {tool.description}\n"
                f"  Parameters: {', '.join(tool.parameters.keys())}"
            )
            by_category.setdefault(category, []).append(line)

        sections: List[str] = []
        for category in CATEGORY_ORDER:
            entries = by_category.get(category)
            if not entries:
                continue
            label = CATEGORY_LABELS.get(category, category.title())
            sections.append(f"### {label}\n" + "\n".join(entries))
        # Append any unrecognised categories at the end (defensive).
        for category, entries in by_category.items():
            if category in CATEGORY_ORDER:
                continue
            label = CATEGORY_LABELS.get(category, category.title())
            sections.append(f"### {label}\n" + "\n".join(entries))
        return "\n\n".join(sections)

    def _build_relevant_guidance(self, steps: List[WorkflowStep]) -> str:
        """Inline only the per-tool guidance that matches actions in steps.

        The full guidance text is sizeable (~2 KB). For a 3-step "fetch SPY,
        write file, send email" workflow we only need the EMAIL +
        fetch_stock_price + generate_text snippets. For the bigger festival
        workflow we additionally pull in scraping + discovery.

        Always-on entries (e.g. ``generate_text``) are included even when no
        step explicitly maps to them, because the agent often falls back to
        ``generate_text`` to format an email body.
        """
        actions = {step.action for step in steps if step.action}
        included: List[str] = []
        seen: set[str] = set()
        for key in (*_ALWAYS_ON_GUIDANCE_KEYS, *actions):
            if key in seen:
                continue
            snippet = _TOOL_GUIDANCE.get(key)
            if snippet:
                included.append(snippet)
                seen.add(key)
        if not included:
            return ""
        return "## SPECIFIC TOOL GUIDANCE\n\n" + "\n\n".join(included)

    def _build_tool_contract_guidance(self, steps: List[WorkflowStep]) -> str:
        """Inline response-shape contracts for tools likely to be used."""
        actions = {step.action for step in steps if step.action}
        descriptions = (step.description for step in steps)
        return build_contract_prompt_guidance(actions, step_descriptions=descriptions)

    def _create_system_prompt(self, steps: Optional[List[WorkflowStep]] = None) -> str:
        steps = steps or []
        tools_info = self._build_grouped_tool_listing()
        relevant_guidance = self._build_relevant_guidance(steps)
        contract_guidance = self._build_tool_contract_guidance(steps)

        guidance_parts = [block for block in (relevant_guidance, contract_guidance) if block]
        guidance_block = "\n\n" + "\n\n".join(guidance_parts) + "\n" if guidance_parts else "\n"

        template = load_prompt_template("codegen_system.txt")
        return template.replace("{{TOOLS_INFO}}", tools_info).replace(
            "{{GUIDANCE_BLOCK}}", guidance_block
        )

    def _create_user_prompt(self, steps: List[WorkflowStep]) -> str:
        steps_text = "".join(
            f"\nStep {i} ({step.step_id}):\n"
            f"  Description : {step.description}\n"
            f"  Action      : {step.action}\n"
            f"  Parameters  : {json.dumps(step.parameters)}\n"
            f"  Depends on  : {step.dependencies}\n"
            for i, step in enumerate(steps, 1)
        )
        return (
            f"Generate a Python script for this workflow:\n{steps_text}\n"
            "Follow SCRIPT STRUCTURE, TOOL USAGE, and SPECIFIC TOOL GUIDANCE above. "
            "Apply ## NO FABRICATION.\n"
            "For UI-heavy or transcript-like steps, apply ## RECORDINGS VS. INTENT.\n"
            "Honor **Depends on**: pass real outputs from earlier steps into later tools "
            "(e.g. fetched text into generate_text)."
        )
