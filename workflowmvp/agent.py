"""
AI Agent - Generates executable Python code from workflow steps.
Supports Gemini, Groq, and OpenRouter as LLM backends.
"""

import json
import os
import re
from typing import List, Optional

import google.generativeai as genai
import requests

from .parser import WorkflowStep
from .tools import ToolRegistry

DEFAULT_GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
DEFAULT_GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
DEFAULT_OPENROUTER_MODEL = os.getenv("OPENROUTER_MODEL", "meta-llama/llama-3.1-70b-instruct")

# Token budget for code generation. 4000 gives headroom for 6+ step workflows.
_CODE_GEN_MAX_TOKENS = 4000
# Token budget for parse-assist (shorter JSON output, less needed).
_PARSE_ASSIST_MAX_TOKENS = 2000


class WorkflowAgent:
    """Generates executable Python code from structured workflow steps using an LLM."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        provider: Optional[str] = None,
    ):
        self.provider = (provider or os.getenv("LLM_PROVIDER", "gemini")).strip().lower()
        if self.provider not in {"gemini", "groq", "openrouter"}:
            raise ValueError(
                f"Unsupported provider '{self.provider}'. Choose gemini, groq, or openrouter."
            )

        default_model = {
            "gemini": DEFAULT_GEMINI_MODEL,
            "groq": DEFAULT_GROQ_MODEL,
            "openrouter": DEFAULT_OPENROUTER_MODEL,
        }[self.provider]
        self.model = model or default_model
        self.tool_registry = ToolRegistry()

        self.api_key = (
            api_key
            or os.getenv("GEMINI_API_KEY" if self.provider == "gemini"
                         else "GROQ_API_KEY" if self.provider == "groq"
                         else "OPENROUTER_API_KEY")
        )

        if self.api_key and self.provider == "gemini":
            genai.configure(api_key=self.api_key)
            self.client = genai.GenerativeModel(self.model)
        else:
            self.client = None

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

        prompt = f"{self._create_system_prompt()}\n\n{self._create_user_prompt(steps)}"
        generated_code = self._extract_python_script(
            self._generate_text(prompt, max_tokens=_CODE_GEN_MAX_TOKENS)
        )
        if not generated_code:
            raise ValueError("Model returned empty code.")

        with open(output_file, "w", encoding="utf-8") as f:
            f.write(generated_code)

        return generated_code

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

        improved: List[WorkflowStep] = []
        for idx, item in enumerate(payload, start=1):
            if not isinstance(item, dict):
                continue
            improved.append(
                WorkflowStep(
                    step_id=str(item.get("step_id") or f"step_{idx}"),
                    description=str(item.get("description") or "").strip(),
                    action=str(item.get("action") or "custom").strip(),
                    parameters=item.get("parameters") if isinstance(item.get("parameters"), dict) else {},
                    dependencies=item.get("dependencies") if isinstance(item.get("dependencies"), list) else [],
                )
            )
        return improved

    @classmethod
    def required_api_key_name(cls, provider: str) -> str:
        return {"gemini": "GEMINI_API_KEY", "groq": "GROQ_API_KEY", "openrouter": "OPENROUTER_API_KEY"}.get(
            provider, "GEMINI_API_KEY"
        )

    # ------------------------------------------------------------------
    # LLM call
    # ------------------------------------------------------------------

    def _generate_text(self, prompt: str, max_tokens: int = _CODE_GEN_MAX_TOKENS) -> str:
        """Send a prompt to the configured LLM and return the text response."""
        if self.provider == "gemini":
            if not self.client:
                raise ValueError("Gemini client not initialised — check GEMINI_API_KEY.")
            response = self.client.generate_content(
                prompt,
                generation_config=genai.types.GenerationConfig(
                    temperature=0.1,
                    max_output_tokens=max_tokens,
                ),
            )
            return response.text or ""

        # Groq / OpenRouter share the OpenAI-compatible chat completions API.
        if self.provider == "groq":
            url = "https://api.groq.com/openai/v1/chat/completions"
            extra_headers: dict = {}
        else:
            url = "https://openrouter.ai/api/v1/chat/completions"
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
            "temperature": 0.1,
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
            return "\n".join(chunk.get("text", "") for chunk in content if isinstance(chunk, dict)).strip()
        return str(content)

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

    def _create_system_prompt(self) -> str:
        tools_info = "\n".join(
            f"- {t.name}: {t.description}\n  Parameters: {', '.join(t.parameters.keys())}"
            for t in self.tool_registry.list_tools()
        )

        return f"""You are a Python code generator. Given a list of workflow steps, produce a single runnable Python script.

Available tools:
{tools_info}

━━━ SCRIPT STRUCTURE ━━━

Always begin with:
   import logging, json, os
   from dotenv import load_dotenv
   from workflowmvp.tools import ToolRegistry
   logging.basicConfig(level=logging.INFO, format='%(message)s')
   logger = logging.getLogger(__name__)
   load_dotenv()

Always end with a main() function and:
   if __name__ == "__main__":
       main()

Always use RELATIVE file paths ("report.txt", "data/output.csv"). Never hardcode absolute paths or /tmp.

━━━ TOOL USAGE ━━━

Get tools like this — always use get_tool(), never use get():
   tools = ToolRegistry()
   dl = tools.get_tool('download')
   result = dl.function(url='https://example.com')

Every tool returns a dict with 'success', 'error', and 'result' (or 'content') keys:
   if not result.get('success'):
       logger.error(f"Failed: {{result.get('error')}}")
       return
   value = result.get('result') or result.get('content')

When a tool returns JSON text (e.g. download), parse the content string — not the result dict:
   data = json.loads(result.get('result') or result.get('content', '{{}}'))

━━━ SPECIFIC TOOL GUIDANCE ━━━

EMAIL — send_email reads credentials from env automatically:
   email_tool = tools.get_tool('send_email')
   email_tool.function(recipient='you@example.com', subject='...', body='...')

AI TEXT GENERATION — for any writing, summarising, translating, or creative task:
   gen = tools.get_tool('generate_text')
   r = gen.function(prompt="Write a short poem about SPY closing at $582.10")
   text = r.get('result', '') if r.get('success') else ''

SCRAPING — scrape_webpage truncates to 4000 chars automatically; still slice before passing to generate_text.
   CRITICAL: when building a generate_text prompt from scraped content, explicitly tell the model
   to use ONLY information found in the content and to report missing details rather than inventing
   placeholder text. Never allow [Insert date] / [Insert location] style placeholders in output:
   scrape = tools.get_tool('scrape_webpage')
   r = scrape.function(url='https://example.com')
   content = (r.get('result') or r.get('content', ''))[:3000]
   gen.function(prompt=(
       f"Using ONLY the information in this webpage content, write a reminder message.\\n"
       f"If specific details (dates, times, location) are not present in the content, "
       f"say so clearly — do NOT use placeholder text like [Insert date].\\n\\n"
       f"Content:\\n{{content}}"
   ))

STOCK / FINANCIAL DATA — always use fetch_stock_price, never scrape finance sites:
   stock = tools.get_tool('fetch_stock_price')
   r = stock.function(ticker='SPY')          # latest close
   price = r['price'] if r.get('success') else None
   # Common tickers: ^GSPC S&P500, ^DJI Dow, ^IXIC Nasdaq, BTC-USD Bitcoin

PRICE COMPARISON — for "up or down vs N days ago", use yfinance directly in the script:
   import yfinance as yf
   hist = yf.Ticker('SPY').history(period='5d')
   price_now   = float(hist['Close'].iloc[-1])
   price_then  = float(hist['Close'].iloc[0])
   change      = price_now - price_then
   direction   = 'up' if change >= 0 else 'down'

HTTP / REST APIs — use http_request for any POST/PUT/DELETE or API with auth:
   api = tools.get_tool('http_request')
   r = api.function(url='https://...', method='POST', body={{'key': 'value'}})

DATA ANALYSIS — analyze_data supports ONLY: sum, average, count, min, max.
   For comparisons, trends, or differences, write plain Python arithmetic instead.

━━━ LOGGING ━━━

Log major milestones only — not every sub-step:
   logger.info("Fetching SPY price...")
   logger.info(f"✅ SPY: ${{price:.2f}}")
   logger.info("Sending email...")
   logger.info("✅ Email sent to you@example.com")

━━━ OUTPUT ━━━

Generate ONLY the Python script — no markdown, no explanation, no comments beyond what is needed.
Extract EXACT values from step descriptions (email addresses, URLs, tickers, etc.) — never use placeholders."""

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
            "Use the EXACT values from the descriptions (emails, URLs, tickers, etc.)."
        )
