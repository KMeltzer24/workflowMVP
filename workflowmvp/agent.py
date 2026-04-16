"""
AI Agent - Generates executable code from workflow steps
"""

import json
import os
import re
from typing import List, Optional

import google.generativeai as genai

from .parser import WorkflowStep
from .tools import ToolRegistry

DEFAULT_GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")


class WorkflowAgent:
    """AI agent that generates executable code from workflow steps"""

    def __init__(self, api_key: Optional[str] = None, model: Optional[str] = None):
        self.model = model or DEFAULT_GEMINI_MODEL
        self.tool_registry = ToolRegistry()

        self.api_key = api_key or os.getenv('GEMINI_API_KEY')
        if self.api_key:
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

        # Require Gemini API key; no offline fallback
        if not self.client:
            raise ValueError("GEMINI_API_KEY is required for code generation. Set env var or pass --api-key.")

        try:
            # Gemini API call
            response = self.client.generate_content(
                f"{system_prompt}\n\n{user_prompt}",
                generation_config=genai.types.GenerationConfig(
                    temperature=0.1,
                    max_output_tokens=2000,
                )
            )
            generated_code = self._extract_python_script(response.text or "")
            if not generated_code:
                raise ValueError("Gemini returned empty code.")

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

    def improve_parsed_steps(
        self, workflow_text: str, rule_steps: List[WorkflowStep]
    ) -> List[WorkflowStep]:
        """Use Gemini to improve low-confidence parser output, returning structured steps."""
        if not self.client:
            raise ValueError("GEMINI_API_KEY is required for AI-assisted parsing.")

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

        response = self.client.generate_content(prompt)
        text = (response.text or "").strip()
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

