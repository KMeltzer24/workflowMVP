"""
AI Agent - Generates executable Python code from workflow steps.
Supports Gemini, Groq, and OpenRouter as LLM backends.
"""

import json
import re
from typing import Dict, List, Optional, Tuple

from .llm import LLMClient, required_api_key_name
from .parser import WorkflowStep
from .tools import ToolRegistry

# Token budget for code generation (output). Large scripts need headroom.
_CODE_GEN_MAX_TOKENS = 8192
# Extra output tokens on automatic retry after a syntax failure.
_CODE_GEN_RETRY_EXTRA_TOKENS = 4096
# Token budget for parse-assist (shorter JSON output, less needed).
_PARSE_ASSIST_MAX_TOKENS = 2000


# Tool name -> category. Categories drive how the system prompt groups the
# available-tools listing and which inline guidance blocks get included for
# the steps the user actually asked for.
_TOOL_CATEGORIES: Dict[str, str] = {
    # filesystem & files
    "read_file": "filesystem",
    "write_file": "filesystem",
    "append_file": "filesystem",
    "list_files": "filesystem",
    "create_directory": "filesystem",
    "copy_file": "filesystem",
    "move_file": "filesystem",
    "delete_file": "filesystem",
    "hash_file": "filesystem",
    "read_csv": "filesystem",
    "write_csv": "filesystem",
    "read_json": "filesystem",
    "write_json": "filesystem",
    "read_pdf": "filesystem",
    # archive
    "compress_files": "archive",
    "extract_archive": "archive",
    # network
    "download": "network",
    "http_request": "network",
    "scrape_webpage": "network",
    "discover_urls": "network",
    # finance
    "fetch_stock_price": "finance",
    # ai
    "generate_text": "ai",
    "render_template": "ai",
    # time
    "wait": "time",
    "get_current_time": "time",
    # comms
    "send_email": "comms",
    "send_notification": "comms",
    # system
    "run_command": "system",
    # database
    "sqlite_query": "database",
    "sqlite_insert": "database",
}

_CATEGORY_ORDER = (
    "filesystem",
    "archive",
    "network",
    "finance",
    "ai",
    "time",
    "comms",
    "system",
    "database",
)

_CATEGORY_LABELS: Dict[str, str] = {
    "filesystem": "Files & I/O",
    "archive": "Archive",
    "network": "Network & Web",
    "finance": "Finance",
    "ai": "AI & Templating",
    "time": "Time",
    "comms": "Communications",
    "system": "System",
    "database": "Database",
}

# Per-tool guidance snippets. Only the entries whose key (a tool name OR a
# category) appears in the workflow are emitted in the system prompt. This
# keeps the prompt short for small workflows while preserving the deep
# guidance the agent relies on for the trickier tools.
_TOOL_GUIDANCE: Dict[str, str] = {
    "send_email": (
        "EMAIL — send_email: recipient, subject, body (plain text), plus optional attachments "
        "(list of relative file paths or one string path). Files are sent as real MIME attachments. "
        "You may use a short body like \"See attached.\" when attaching. Without attachments, body "
        "carries the full message. Never invent email_from — omit it or use os.getenv('EMAIL_FROM').\n"
        "   **Recipient:** use the address **exactly** as written in the send-email step (same spelling "
        "and digits, e.g. `kevinmeltzer1@gmail.com` vs `kevinnmeltzer@gmail.com`). Do not substitute a "
        "different address.\n"
        "   email_tool = tools.get_tool('send_email')\n"
        "   email_tool.function(recipient='you@example.com', subject='...', body='...', attachments=['report.md'])"
    ),
    "generate_text": (
        "AI TEXT GENERATION — for summarising, translating, or **creative** tasks when the step allows it:\n"
        "   gen = tools.get_tool('generate_text')\n"
        "   r = gen.function(prompt=\"Write a short poem about SPY closing at $582.10\")\n"
        "   text = r.get('result', '') if r.get('success') else ''\n"
        "   For **reminders, paragraphs, and email bodies**, pass a large enough **max_tokens** "
        "(typically **512–1024**, not ~200) so the model is not cut off mid-sentence."
    ),
    "scrape_webpage": (
        "SCRAPING — scrape_webpage strips HTML tags and returns clean readable text (up to 4000 chars).\n"
        "   **URL priority:** (1) exact URL from the step / parameters; (2) else discover candidates, then "
        "scrape the best.\n"
        "   Slice before passing to generate_text:\n"
        "   content = (r.get('result') or '')[:3000]\n"
        "   AVOID scraping Google News / Google Search HTML (news.google.com/topics, /search?, etc.) — "
        "servers often return 400/403 to automated clients even with browser headers."
    ),
    "discover_urls": (
        "URL DISCOVERY — discover_urls: When the step names an org/site but **not** a specific program "
        "page, call `discover_urls` with `start_url` = the official homepage (must include `https://`), "
        "and `keywords` = distinctive words from the step (e.g. `sci-fi fantasy short festival seattle`). "
        "It merges **sitemap.xml** (and index → child sitemaps, bounded) with **same-origin links** from "
        "the homepage, ranks by keyword hits, returns JSON in `result`. Pick the **top-scoring** URL "
        "(or scrape the top 1–2 if the first is thin), then `scrape_webpage` that URL. Do **not** "
        "manually guess paths like `/festivals` unless `discover_urls` fails and the step gives no "
        "better option."
    ),
    "http_request": (
        "HTTP / REST APIs — use http_request for any POST/PUT/DELETE or API with auth:\n"
        "   api = tools.get_tool('http_request')\n"
        "   r = api.function(url='https://...', method='POST', body={'key': 'value'})"
    ),
    "fetch_stock_price": (
        "STOCK / FINANCIAL DATA — prefer fetch_stock_price over scraping finance websites.\n"
        "- **Ticker:** use the **exact** symbol from the step description or parameters (e.g. `SPY` vs "
        "`BTC-USD`). Never swap in a different instrument.\n"
        "- **Single latest close:** fetch_stock_price(ticker='SPY', period='1d'). On success read price, "
        "ticker, and currency from the returned dict. Common tickers: ^GSPC, ^DJI, ^IXIC, BTC-USD.\n"
        "- **Multi-bar math** (e.g. compare first vs last close in the same history window): import "
        "yfinance as yf inside the script and use Ticker(...).history(period=...). Use yfinance only "
        "for this price series, not for scraping webpages. fetch_stock_price exposes the latest bar "
        "from its window, not the full DataFrame for custom comparisons.\n"
        "   import yfinance as yf\n"
        "   hist = yf.Ticker('SPY').history(period='5d')\n"
        "   price_now   = float(hist['Close'].iloc[-1])\n"
        "   price_then  = float(hist['Close'].iloc[0])\n"
        "   change      = price_now - price_then\n"
        "   direction   = 'up' if change >= 0 else 'down'"
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
                    "or a syntax error). Output the **entire** script again as a single runnable "
                    "file: every import through a complete `if __name__ == \"__main__\":` block, "
                    "with all compound statements having non-empty bodies. No markdown.\n"
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

Return ONLY a JSON array. Each object must have these keys:
  step_id, description, action, parameters (object), dependencies (array)

Rules:
- Preserve step order and numbering.
- Prefer a specific allowed action over "custom" when reasonable.
- Include obvious parameters from the text (url, file_path, recipient, ticker, etc.).
- dependencies must reference earlier step_ids only.
- No markdown, no commentary — raw JSON only.

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
            improved.append(
                WorkflowStep(
                    step_id=str(item.get("step_id") or f"step_{idx}"),
                    description=str(item.get("description") or "").strip(),
                    action=action,
                    parameters=item.get("parameters") if isinstance(item.get("parameters"), dict) else {},
                    dependencies=item.get("dependencies") if isinstance(item.get("dependencies"), list) else [],
                )
            )
        return improved

    @classmethod
    def required_api_key_name(cls, provider: str) -> str:
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
        """Reject truncated or malformed scripts before they are written to disk."""
        try:
            compile(code, "<generated_workflow>", "exec")
        except SyntaxError as exc:
            raise ValueError(
                f"Invalid Python from model (line {exc.lineno}: {exc.msg})."
            ) from exc

    @staticmethod
    def _extract_json_array(text: str) -> List[dict]:
        """Pull a JSON array out of raw model output, tolerating markdown fences."""
        stripped = re.sub(r"^```[a-zA-Z]*\n?", "", text.strip())
        stripped = re.sub(r"\n?```$", "", stripped)
        try:
            parsed = json.loads(stripped)
            if isinstance(parsed, list):
                return parsed
        except json.JSONDecodeError:
            pass
        match = re.search(r"\[[\s\S]*\]", stripped)
        if not match:
            raise ValueError("AI parse assistant returned invalid JSON.")
        parsed = json.loads(match.group(0))
        if not isinstance(parsed, list):
            raise ValueError("AI parse assistant returned non-list JSON.")
        return parsed

    # ------------------------------------------------------------------
    # Prompt construction
    # ------------------------------------------------------------------

    def _build_grouped_tool_listing(self) -> str:
        """Group the available-tools listing by category for readability.

        The LLM still sees every tool, but the list is organised so smaller
        models stay on-task and bigger models waste fewer tokens scanning a
        flat block of 30 entries.
        """
        by_category: Dict[str, List[str]] = {}
        for tool in self.tool_registry.list_tools():
            category = _TOOL_CATEGORIES.get(tool.name, "system")
            line = (
                f"- {tool.name}: {tool.description}\n"
                f"  Parameters: {', '.join(tool.parameters.keys())}"
            )
            by_category.setdefault(category, []).append(line)

        sections: List[str] = []
        for category in _CATEGORY_ORDER:
            entries = by_category.get(category)
            if not entries:
                continue
            label = _CATEGORY_LABELS.get(category, category.title())
            sections.append(f"### {label}\n" + "\n".join(entries))
        # Append any unrecognised categories at the end (defensive).
        for category, entries in by_category.items():
            if category in _CATEGORY_ORDER:
                continue
            label = _CATEGORY_LABELS.get(category, category.title())
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

    def _create_system_prompt(self, steps: Optional[List[WorkflowStep]] = None) -> str:
        steps = steps or []
        tools_info = self._build_grouped_tool_listing()
        relevant_guidance = self._build_relevant_guidance(steps)

        guidance_block = f"\n\n{relevant_guidance}\n" if relevant_guidance else "\n"

        return f"""You are a Python code generator. Given a list of workflow steps, produce a single runnable Python script.

## NO FABRICATION (SOURCE OF TRUTH)

Do **not** invent facts, dates, times, prices, statistics, schedules, quotes, or other specifics just to make the workflow "succeed." Ground every substantive claim in **tool outputs** (scrape, http_request, download, fetch_stock_price, files, etc.), **deterministic code** the steps require (e.g. `datetime` / `zoneinfo` math), or **verbatim** stable values from the step text (emails, tickers, URLs).

If information is missing or retrieval fails: **stop, log clearly, or say in the user-facing message that it could not be obtained** — never fill gaps with plausible guesses. **`generate_text` must not be used to hallucinate missing real-world facts**; use it only to summarize, rephrase, or format **supplied** text, unless a step explicitly asks for creative or fictional content.

**Schedules / "when is …":** Retrieve page or feed text first (`scrape_webpage`, `http_request`, `download`), then summarize or email. If the step names an organization but gives no URL, one reasonable attempt at its **official public** site is OK; on failure, do not invent dates. **Best:** put a **direct link** to the program or festival page in the step text when you have one — homepages often omit schedule detail.

Available tools:
{tools_info}

## SCRIPT STRUCTURE

Always begin with:
   import logging, json, os
   from dotenv import load_dotenv
   from workflowmvp.tools import ToolRegistry
   logging.basicConfig(level=logging.INFO, format='%(message)s')
   # Keep noisy SDK request logs quiet in the *generated subprocess*.
   # (The parent Flask/LLM process separately suppresses these in llm.py.)
   for _lib in ('httpx', 'httpcore', 'urllib3', 'google_genai'):
       logging.getLogger(_lib).setLevel(logging.WARNING)
   logger = logging.getLogger(__name__)
   load_dotenv()

Always end with a main() function and:
   if __name__ == "__main__":
       main()

Always use RELATIVE file paths ("report.txt", "data/output.csv"). Never hardcode absolute paths or /tmp.

**Imports:** Use the Python **standard library** (`datetime`, **`zoneinfo`**) plus packages **already in** project requirements (e.g. `yfinance` when needed). **Do not import `pytz` or `holidays`** — they are not dependencies. For IANA timezones use `zoneinfo.ZoneInfo`. For a **nominal** NYSE/Nasdaq regular cash session close, **16:00 America/New_York on weekdays (Mon–Fri)** is acceptable unless steps say otherwise; **market holidays and early closes are not modeled** unless you use an external API or explicit rules in the step text.

## TOOL USAGE

Get tools like this — always use get_tool(), never use get():
   tools = ToolRegistry()
   dl = tools.get_tool('download')
   result = dl.function(url='https://example.com')

Every tool call returns a dict that (after wrapping) always includes: success, error, result, and meta (use meta['tool'] for logging).
On failure: success is False — read error and stop.
On success: read result for the primary string/object output when set. Many tools also set extra keys on the same dict (e.g. read_json → data, fetch_stock_price → price/ticker/currency, read_pdf → text, render_template → rendered). Use those fields when documented for that tool.

   if not result.get('success'):
       logger.error(f"Failed: {{result.get('error')}}")
       return

When a tool returns JSON as text (e.g. download), parse from result:
   data = json.loads(result.get('result') or '{{}}'){guidance_block}
## RECORDINGS VS. INTENT (UI-HEAVY STEPS)

If steps read like a **screen recording** (Navigate, Type in search bar, Gmail compose, "Enter X into To/Subject/Body",
long google.com URLs with tracking params, many consecutive `custom` steps before `send_email`):
- Treat them as **demonstration of intent**, not a script to replay with logger.info per click.
- Implement the **underlying goal**: compute or fetch fresh facts at runtime (datetime, zoneinfo, http_request to a time/market API, etc.), then call tools (e.g. send_email) with **computed** subject/body.
- **Never** hardcode time-sensitive phrases copied from the narration (e.g. "closes in 22 mins") in email bodies — recompute or fetch; see ## NO FABRICATION.
- Users **edit parsed steps in the app** before codegen; treat each step's **final description, action, and parameters** as the source of truth (not an earlier draft or guessed frame read).

Constants vs. dynamic: use descriptions **exactly** for stable user data (emails, file paths, API URLs, tickers). Recompute anything that depends on "now" or on-page search results.

## LOGGING

Log **major milestones** only — not every sub-step. Prefer **short, single-line** `logger.info` messages so streamed run logs stay readable (avoid dumping multi-line LLM output into the log).
   logger.info("Fetching SPY price...")
   logger.info(f"✅ SPY: ${{price:.2f}}")
   logger.info("Sending email...")
   logger.info("✅ Email sent to you@example.com")

## OUTPUT

Generate ONLY the Python script — no markdown, no explanation, no comments beyond what is needed.
Extract exact values from step descriptions for **stable** fields only; compute time-sensitive values at runtime where the steps require it.

**Completeness:** Emit the **entire** script in one piece through `if __name__ == "__main__": main()` (or equivalent). Do not stop mid-statement.
Every compound statement (`if`, `while`, `for`, `def`, `with`, `try`, `class`) MUST have a **non-empty** indented body on the following line(s). Example weekend skip:
   while next_close_et.weekday() >= 5:
       next_close_et += datetime.timedelta(days=1)"""

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
