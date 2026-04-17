"""
AI Agent - Generates executable code from workflow steps
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
DEFAULT_OPENROUTER_MODEL = os.getenv(
    "OPENROUTER_MODEL", "meta-llama/llama-3.1-70b-instruct"
)


class WorkflowAgent:
    """AI agent that generates executable code from workflow steps"""

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        provider: Optional[str] = None,
    ):
        self.provider = (provider or os.getenv("LLM_PROVIDER", "gemini")).strip().lower()
        if self.provider not in {"gemini", "groq", "openrouter"}:
            raise ValueError(
                f"Unsupported provider '{self.provider}'. Use gemini, groq, or openrouter."
            )

        default_model = {
            "gemini": DEFAULT_GEMINI_MODEL,
            "groq": DEFAULT_GROQ_MODEL,
            "openrouter": DEFAULT_OPENROUTER_MODEL,
        }[self.provider]
        self.model = model or default_model
        self.tool_registry = ToolRegistry()

        if api_key:
            self.api_key = api_key
        elif self.provider == "gemini":
            self.api_key = os.getenv("GEMINI_API_KEY")
        elif self.provider == "groq":
            self.api_key = os.getenv("GROQ_API_KEY")
        else:
            self.api_key = os.getenv("OPENROUTER_API_KEY")

        if self.api_key and self.provider == "gemini":
            genai.configure(api_key=self.api_key)
            self.client = genai.GenerativeModel(self.model)
        else:
            self.client = None

    def generate_workflow_code(self, steps: List[WorkflowStep],
                             output_file: str = "generated_workflow.py") -> str:
        """Generate executable Python code from workflow steps"""

        # Create system prompt
        system_prompt = self._create_system_prompt()

        # Create user prompt with workflow steps
        user_prompt = self._create_user_prompt(steps)

        # Require selected provider API key; no offline fallback
        if not self.api_key:
            key_name = self.required_api_key_name(self.provider)
            raise ValueError(
                f"{key_name} is required for code generation. Set env var or pass credentials."
            )

        try:
            generated_code = self._extract_python_script(
                self._generate_text(f"{system_prompt}\n\n{user_prompt}")
            )
            if not generated_code:
                raise ValueError("Model returned empty code.")

            # Write the generated code to file
            with open(output_file, 'w', encoding='utf-8') as f:
                f.write(generated_code)

            return generated_code

        except Exception:
            # Surface the error to the caller
            raise

    @staticmethod
    def _extract_python_script(text: str) -> str:
        """Extract Python code safely from model output."""
        raw = text.strip()
        if not raw:
            return ""

        # Prefer fenced code blocks when available.
        fenced = re.findall(r"```(?:python)?\s*([\s\S]*?)```", raw, flags=re.IGNORECASE)
        if fenced:
            best = max((block.strip() for block in fenced), key=len, default="")
            return best

        # No fenced block: remove obvious markdown fences if partially present.
        raw = re.sub(r"^```[a-zA-Z]*\n?", "", raw)
        raw = re.sub(r"\n?```$", "", raw)

        lines = raw.splitlines()
        start_idx = 0
        starters = (
            "import ",
            "from ",
            "def ",
            "class ",
            "if __name__",
            "tools = ",
            "logger = ",
            "load_dotenv(",
        )
        for i, line in enumerate(lines):
            stripped = line.strip()
            if stripped.startswith(starters) or ("=" in stripped and not stripped.startswith("#")):
                start_idx = i
                break
        cleaned = "\n".join(lines[start_idx:]).strip()
        return cleaned

    @classmethod
    def required_api_key_name(cls, provider: str) -> str:
        mapping = {
            "gemini": "GEMINI_API_KEY",
            "groq": "GROQ_API_KEY",
            "openrouter": "OPENROUTER_API_KEY",
        }
        return mapping.get(provider, "GEMINI_API_KEY")

    def _generate_text(self, prompt: str) -> str:
        if self.provider == "gemini":
            assert self.client is not None
            response = self.client.generate_content(
                prompt,
                generation_config=genai.types.GenerationConfig(
                    temperature=0.1,
                    max_output_tokens=2000,
                ),
            )
            return response.text or ""

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        if self.provider == "groq":
            url = "https://api.groq.com/openai/v1/chat/completions"
        else:
            url = "https://openrouter.ai/api/v1/chat/completions"
            headers["HTTP-Referer"] = os.getenv("OPENROUTER_SITE_URL", "http://localhost:5050")
            headers["X-Title"] = os.getenv("OPENROUTER_APP_NAME", "WorkflowMVP")

        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.1,
            "max_tokens": 2000,
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
            chunks = [chunk.get("text", "") for chunk in content if isinstance(chunk, dict)]
            return "\n".join(chunks).strip()
        return str(content)

    def improve_parsed_steps(
        self, workflow_text: str, rule_steps: List[WorkflowStep]
    ) -> List[WorkflowStep]:
        """Use Gemini to improve low-confidence parser output, returning structured steps."""
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

        prompt = f"""
You improve workflow parsing quality. Convert user text into strict JSON.

Allowed actions: {", ".join(tool_names)}, custom

Return ONLY a JSON array with objects:
[
  {{
    "step_id": "step_1",
    "description": "human readable instruction",
    "action": "one_allowed_action_or_custom",
    "parameters": {{}},
    "dependencies": []
  }}
]

Rules:
- Preserve step order and numbering semantics.
- Prefer an allowed action over "custom" when reasonable.
- Include required params when obvious from text (url, file_path, recipient, etc.).
- dependencies should reference previous step_ids only.
- No markdown fences, no commentary.

Original workflow text:
{workflow_text}

Rule parser draft (for context):
{json.dumps(rule_payload, indent=2)}
        """.strip()

        text = (self._generate_text(prompt) or "").strip()
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
                    parameters=item.get("parameters")
                    if isinstance(item.get("parameters"), dict)
                    else {},
                    dependencies=item.get("dependencies")
                    if isinstance(item.get("dependencies"), list)
                    else [],
                )
            )
        return improved

    @staticmethod
    def _extract_json_array(text: str) -> List[dict]:
        """Extract a JSON array from model output."""
        stripped = text.strip()
        if stripped.startswith("```"):
            stripped = re.sub(r"^```[a-zA-Z]*\n?", "", stripped)
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

    def _create_system_prompt(self) -> str:
        """Create system prompt for the AI agent"""
        available_tools = self.tool_registry.list_tools()
        tools_info = "\n".join([
            f"- {tool.name}: {tool.description}\n  Parameters: {', '.join(tool.parameters.keys())}"
            for tool in available_tools
        ])

        return f"""You are a Python code generator that creates executable workflow programs.

Available tools:
{tools_info}

CRITICAL REQUIREMENTS:
0. The generated script runs inside a sandbox working directory. Always use
   RELATIVE file paths (e.g., "users.csv", "sandbox/note.txt"). Never hard-code
   absolute paths or /tmp.

1. ALWAYS start with these imports:
   ```python
   import logging
   import json
   import os
   from dotenv import load_dotenv
   from workflowmvp.tools import ToolRegistry

   logging.basicConfig(level=logging.INFO, format='%(message)s')
   logger = logging.getLogger(__name__)

   # Load environment variables
   load_dotenv()
   ```

2. Tool return values: ALL tools return dictionaries with 'success', 'content'/'result', and 'error' keys
   - download tool returns: {{"success": True, "content": "response_text", "size": 1234}}
   - read_file tool returns: {{"success": True, "content": "file_content", "size": 1234}}
   - NEVER use json.loads() on tool results directly - use result['content']

3. Email configuration: Use environment variables with fallbacks:
   ```python
   smtp_server = os.getenv('SMTP_SERVER', 'smtp.gmail.com')
   smtp_port = int(os.getenv('SMTP_PORT', '587'))
   ```

4. Error handling: Always check tool results with minimal logging:
   ```python
   result = tool.function(...)
   if not result.get('success'):
       logger.error(f"Failed: {{result.get('error')}}")
       return
   # Don't log success for every small operation
   ```

5. Tool usage: ALWAYS use tools.get_tool('tool_name').function() - NEVER use tools.get():
   ```python
   tools = ToolRegistry()
   download_tool = tools.get_tool('download')
   result = download_tool.function(url='https://example.com')
   ```

6. JSON parsing: When processing downloaded JSON data:
   ```python
   download_result = download_tool.function(url=api_url)
   if download_result.get('success'):
       json_data = json.loads(download_result['content'])
   ```

8. COLLAPSE email GUI steps into single send_email call with extracted recipient/subject/body
   - CRITICAL: Extract recipient, subject, and body from step descriptions
   - Look for patterns like "enter `email@example.com`" or "enter 'email@example.com'"
   - Use the EXACT values from the step descriptions, not generic placeholders
9. Use meaningful variable names and add high-level logging for major accomplishments only:
   ```python
   # LOG THESE: Major operations and results
   logger.info("Fetching Bitcoin price from API...")
   logger.info("✅ Price retrieved: $45,230")
   logger.info("Sending email notification...")
   logger.info("✅ Email sent to user@example.com")

   # DON'T LOG: Small steps like filling forms, clicking buttons, etc.
   # Skip: "Filling subject field", "Clicking send button", "Opening email client"
   ```
10. MUST have main() function and if __name__ == "__main__": main() pattern

IMPORTANT: Generate ONLY Python code - no markdown, no documentation, no explanations.
Output a complete, runnable Python script that properly handles tool responses and uses environment variables.
Start with imports and end with if __name__ == "__main__": main()"""

    def _create_user_prompt(self, steps: List[WorkflowStep]) -> str:
        """Create user prompt with workflow steps"""
        steps_info = []
        for i, step in enumerate(steps, 1):
            steps_info.append(f"""
Step {i} ({step.step_id}):
- Description: {step.description}
- Action: {step.action}
- Parameters: {json.dumps(step.parameters, indent=2)}
- Dependencies: {step.dependencies}
""")

        return f"""Generate a Python script for the following workflow:

{''.join(steps_info)}

The script should execute these steps in order, handling dependencies and errors appropriately.

CRITICAL: When you see step descriptions that contain specific values (like email addresses, subjects, URLs, etc.),
you MUST extract and use those EXACT values in your generated code. Do not use generic placeholders or
make up values - use what's actually written in the step descriptions."""

