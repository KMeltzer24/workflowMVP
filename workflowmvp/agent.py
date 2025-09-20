"""
AI Agent - Generates executable code from workflow steps
"""

import os
import json
from typing import List, Dict, Any, Optional
import google.generativeai as genai
from .parser import WorkflowStep
from .tools import ToolRegistry


class WorkflowAgent:
    """AI agent that generates executable code from workflow steps"""
    
    def __init__(self, api_key: Optional[str] = None, model: str = "gemini-1.5-flash"):
        self.model = model
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
            generated_code = response.text
            
            # Clean up the code (remove markdown formatting if present)
            generated_code = generated_code.strip()
            
            # Remove markdown code fences
            if generated_code.startswith('```python'):
                generated_code = generated_code[9:]
            elif generated_code.startswith('```'):
                generated_code = generated_code[3:]
            
            if generated_code.endswith('```'):
                generated_code = generated_code[:-3]
            
            # Remove any trailing documentation/explanations after the Python code
            lines = generated_code.split('\n')
            python_lines = []
            
            for line in lines:
                # Stop at markdown-style sections, installation instructions, or code fences
                if (line.strip().startswith('##') or 
                    line.strip().startswith('**') or 
                    'install' in line.lower() or
                    line.strip() == '```' or
                    line.strip().startswith('```')):
                    break
                python_lines.append(line)
            
            generated_code = '\n'.join(python_lines).strip()
            
            # Write the generated code to file
            with open(output_file, 'w', encoding='utf-8') as f:
                f.write(generated_code)
            
            return generated_code
            
        except Exception as e:
            # Surface the error to the caller
            raise
    
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
1. ALWAYS start with these imports:
   ```python
   import logging
   import json
   import os
   from dotenv import load_dotenv
   from workflowmvp.tools import ToolRegistry
   
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

