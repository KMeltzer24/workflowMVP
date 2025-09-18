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
            if generated_code.startswith('```python'):
                generated_code = generated_code[9:]
            if generated_code.endswith('```'):
                generated_code = generated_code[:-3]
            
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

Instructions:
1. Generate a complete Python script that executes the given workflow steps
2. Use the available tools from the tool registry
3. Handle errors gracefully with try-catch blocks
4. Include proper imports and setup
5. Add logging to track workflow progress
6. Make the code executable and well-structured
7. Use meaningful variable names
8. Include comments explaining each step
9. CRITICAL: The script MUST have a main() function that executes the workflow
10. Use if __name__ == "__main__": main() pattern

The generated code should be a complete, runnable Python script with a main() function."""

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

The script should execute these steps in order, handling dependencies and errors appropriately."""

    def _generate_fallback_code(self, steps: List[WorkflowStep], output_file: str) -> str:
        """Generate code using template-based approach if AI fails"""
        code_lines = [
            "#!/usr/bin/env python3",
            '"""Generated workflow script"""',
            "",
            "import os",
            "import sys",
            "import logging",
            "import json",
            "from typing import Dict, Any",
            "",
            "# Import tool registry",
            "from workflowmvp.tools import ToolRegistry",
            "",
            "# Setup logging",
            "logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')",
            "logger = logging.getLogger(__name__)",
            "",
            "def main():",
            "    \"\"\"Main workflow execution\"\"\"",
            "    logger.info('Starting workflow execution')",
            "    ",
            "    # Initialize tool registry",
            "    tools = ToolRegistry()",
            "    ",
            "    # Workflow results storage",
            "    results = {}",
            "    ",
        ]
        
        # Add each step
        for i, step in enumerate(steps):
            # Filter out description from parameters
            tool_params = {k: v for k, v in step.parameters.items() if k != 'description'}
            
            code_lines.extend([
                f"    # Step {i+1}: {step.description}",
                f"    try:",
                f"        logger.info('Executing step {i+1}: {step.action}')",
                f"        tool = tools.get_tool('{step.action}')",
                f"        if tool:",
                f"            result = tool.function(**{json.dumps(tool_params)})",
                f"            results['{step.step_id}'] = result",
                f"            logger.info(f'Step {i+1} completed: {{result}}')",
                f"        else:",
                f"            logger.error(f'Tool not found: {step.action}')",
                f"            results['{step.step_id}'] = {{'success': False, 'error': 'Tool not found'}}",
                f"    except Exception as e:",
                f"        logger.error(f'Step {i+1} failed: {{e}}')",
                f"        results['{step.step_id}'] = {{'success': False, 'error': str(e)}}",
                f"    ",
            ])
        
        code_lines.extend([
            "    # Final results",
            "    logger.info('Workflow completed')",
            "    print(json.dumps(results, indent=2))",
            "    return results",
            "",
            "if __name__ == '__main__':",
            "    main()",
        ])
        
        generated_code = "\n".join(code_lines)
        
        # Write to file
        with open(output_file, 'w', encoding='utf-8') as f:
            f.write(generated_code)
        
        return generated_code
