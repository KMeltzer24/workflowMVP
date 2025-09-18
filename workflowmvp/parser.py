"""
Workflow Parser - Extracts structured steps from text descriptions
"""

import re
from typing import List, Dict, Any, Optional
from dataclasses import dataclass


@dataclass
class WorkflowStep:
    """Represents a single step in a workflow"""
    step_id: str
    description: str
    action: str
    parameters: Dict[str, Any]
    dependencies: List[str]
    output: Optional[str] = None


class WorkflowParser:
    """Parses text descriptions into structured workflow steps"""
    
    def __init__(self):
        self.step_patterns = [
            r'(\d+)\.\s*(.+?)(?=\n\d+\.|\n\n|$)',
            r'Step\s+(\d+):\s*(.+?)(?=\nStep\s+\d+:|$)',
            r'-?\s*(.+?)(?=\n-|\n\n|$)',
        ]
    
    def parse_workflow(self, workflow_text: str) -> List[WorkflowStep]:
        """Parse workflow text into structured steps"""
        steps = []
        lines = workflow_text.strip().split('\n')
        
        current_step = None
        step_counter = 1
        
        for line in lines:
            line = line.strip()
            if not line:
                continue
                
            # Check if this is a new step
            if self._is_step_start(line):
                if current_step:
                    steps.append(current_step)
                
                step_id = f"step_{step_counter}"
                description = self._extract_description(line)
                action, parameters = self._extract_action_and_params(description)
                
                current_step = WorkflowStep(
                    step_id=step_id,
                    description=description,
                    action=action,
                    parameters=parameters,
                    dependencies=[]
                )
                step_counter += 1
            elif current_step and line.startswith(('  ', '\t')):
                # This is a continuation or parameter of the current step
                current_step.description += f" {line.strip()}"
                action, params = self._extract_action_and_params(current_step.description)
                current_step.action = action
                current_step.parameters.update(params)
        
        if current_step:
            steps.append(current_step)
        
        # Resolve dependencies
        self._resolve_dependencies(steps)
        
        return steps
    
    def _is_step_start(self, line: str) -> bool:
        """Check if a line starts a new step"""
        patterns = [
            r'^\d+\.',
            r'^Step\s+\d+:',
            r'^-\s+',
            r'^\*\s+',
        ]
        return any(re.match(pattern, line) for pattern in patterns)
    
    def _extract_description(self, line: str) -> str:
        """Extract the description from a step line"""
        # Remove step numbering
        line = re.sub(r'^\d+\.\s*', '', line)
        line = re.sub(r'^Step\s+\d+:\s*', '', line)
        line = re.sub(r'^[-*]\s*', '', line)
        return line.strip()
    
    def _extract_action_and_params(self, description: str) -> tuple[str, Dict[str, Any]]:
        """Extract action and parameters from description"""
        description_lower = description.lower()
        
        # Common action patterns
        if 'download' in description_lower or 'fetch' in description_lower:
            action = 'download'
            params = self._extract_url_params(description)
        elif 'read' in description_lower and 'file' in description_lower:
            action = 'read_file'
            params = self._extract_file_params(description)
        elif 'write' in description_lower and 'file' in description_lower:
            action = 'write_file'
            params = self._extract_file_params(description)
        elif 'send' in description_lower and 'email' in description_lower:
            action = 'send_email'
            params = self._extract_email_params(description)
        elif 'process' in description_lower or 'transform' in description_lower:
            action = 'process_data'
            params = self._extract_process_params(description)
        elif 'wait' in description_lower or 'sleep' in description_lower:
            action = 'wait'
            params = self._extract_wait_params(description)
        else:
            action = 'custom'
            params = {'description': description}
        
        return action, params
    
    def _extract_url_params(self, description: str) -> Dict[str, Any]:
        """Extract URL parameters from description"""
        url_match = re.search(r'https?://[^\s]+', description)
        return {
            'url': url_match.group() if url_match else '',
            'description': description
        }
    
    def _extract_file_params(self, description: str) -> Dict[str, Any]:
        """Extract file parameters from description"""
        file_match = re.search(r'["\']([^"\']*\.[a-zA-Z0-9]+)["\']', description)
        return {
            'file_path': file_match.group(1) if file_match else '',
            'description': description
        }
    
    def _extract_email_params(self, description: str) -> Dict[str, Any]:
        """Extract email parameters from description"""
        email_match = re.search(r'[\w\.-]+@[\w\.-]+\.\w+', description)
        return {
            'recipient': email_match.group() if email_match else '',
            'description': description
        }
    
    def _extract_process_params(self, description: str) -> Dict[str, Any]:
        """Extract processing parameters from description"""
        return {
            'operation': description,
            'description': description
        }
    
    def _extract_wait_params(self, description: str) -> Dict[str, Any]:
        """Extract wait parameters from description"""
        time_match = re.search(r'(\d+)\s*(second|minute|hour|day)s?', description.lower())
        if time_match:
            value = int(time_match.group(1))
            unit = time_match.group(2)
            multiplier = {'second': 1, 'minute': 60, 'hour': 3600, 'day': 86400}
            seconds = value * multiplier.get(unit, 1)
        else:
            seconds = 5  # default
        
        return {
            'seconds': seconds,
            'description': description
        }
    
    def _resolve_dependencies(self, steps: List[WorkflowStep]):
        """Resolve dependencies between steps"""
        for i, step in enumerate(steps):
            # Simple dependency resolution - each step depends on the previous one
            if i > 0:
                step.dependencies.append(steps[i-1].step_id)
