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
        pass
    
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
        """Extract action and parameters from description with enhanced pattern matching"""
        description_lower = description.lower()
        
        # Enhanced action patterns with more specific matching
        if 'download' in description_lower or 'fetch' in description_lower:
            action = 'download'
            params = self._extract_url_params(description)
        elif 'read' in description_lower and ('file' in description_lower or 'csv' in description_lower):
            if 'csv' in description_lower:
                action = 'read_csv'
                params = self._extract_file_params(description)
            else:
                action = 'read_file'
                params = self._extract_file_params(description)
        elif 'write' in description_lower and ('file' in description_lower or 'csv' in description_lower):
            if 'csv' in description_lower:
                action = 'write_csv'
                params = self._extract_file_params(description)
            else:
                action = 'write_file'
                params = self._extract_file_params(description)
        elif 'send' in description_lower and 'email' in description_lower:
            action = 'send_email'
            params = self._extract_email_params(description)
        elif 'process' in description_lower or 'transform' in description_lower:
            if 'json' in description_lower:
                action = 'process_json'
                params = self._extract_json_params(description)
            else:
                action = 'process_data'
                params = self._extract_process_params(description)
        elif 'wait' in description_lower or 'sleep' in description_lower:
            action = 'wait'
            params = self._extract_wait_params(description)
        elif 'copy' in description_lower and 'file' in description_lower:
            action = 'copy_file'
            params = self._extract_file_operation_params(description)
        elif 'move' in description_lower and 'file' in description_lower:
            action = 'move_file'
            params = self._extract_file_operation_params(description)
        elif 'delete' in description_lower and 'file' in description_lower:
            action = 'delete_file'
            params = self._extract_file_params(description)
        elif 'run' in description_lower and ('command' in description_lower or 'script' in description_lower):
            action = 'run_command'
            params = self._extract_command_params(description)
        elif 'database' in description_lower or 'sql' in description_lower:
            if 'insert' in description_lower or 'add' in description_lower:
                action = 'sqlite_insert'
                params = self._extract_database_params(description)
            else:
                action = 'sqlite_query'
                params = self._extract_database_params(description)
        elif 'scrape' in description_lower or 'extract' in description_lower:
            action = 'scrape_webpage'
            params = self._extract_url_params(description)
        elif 'compress' in description_lower or 'zip' in description_lower:
            action = 'compress_files'
            params = self._extract_compression_params(description)
        elif 'extract' in description_lower and 'archive' in description_lower:
            action = 'extract_archive'
            params = self._extract_compression_params(description)
        elif 'analyze' in description_lower or 'calculate' in description_lower:
            action = 'analyze_data'
            params = self._extract_analysis_params(description)
        elif 'notify' in description_lower or 'notification' in description_lower:
            action = 'send_notification'
            params = self._extract_notification_params(description)
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
    
    def _extract_json_params(self, description: str) -> Dict[str, Any]:
        """Extract JSON processing parameters"""
        return {
            'operation': 'extract' if 'extract' in description.lower() else 'filter',
            'path': self._extract_json_path(description),
            'description': description
        }
    
    def _extract_json_path(self, description: str) -> str:
        """Extract JSONPath from description"""
        # Look for patterns like "extract price from data.bitcoin.usd"
        path_match = re.search(r'(?:extract|get|find)\s+(\w+)\s+from\s+([\w\.\[\]]+)', description.lower())
        if path_match:
            return path_match.group(2)
        return ""
    
    def _extract_file_operation_params(self, description: str) -> Dict[str, Any]:
        """Extract file operation parameters (copy, move)"""
        # Look for "from X to Y" pattern
        from_match = re.search(r'from\s+["\']?([^"\']+)["\']?\s+to\s+["\']?([^"\']+)["\']?', description)
        if from_match:
            return {
                'source': from_match.group(1),
                'destination': from_match.group(2),
                'description': description
            }
        return {'description': description}
    
    def _extract_command_params(self, description: str) -> Dict[str, Any]:
        """Extract command parameters"""
        # Look for command in quotes or after "run"
        cmd_match = re.search(r'["\']([^"\']+)["\']', description)
        if cmd_match:
            return {
                'command': cmd_match.group(1),
                'description': description
            }
        return {'description': description}
    
    def _extract_database_params(self, description: str) -> Dict[str, Any]:
        """Extract database parameters"""
        # Look for table name and database path
        table_match = re.search(r'table\s+["\']?(\w+)["\']?', description.lower())
        db_match = re.search(r'database\s+["\']?([^"\']+)["\']?', description.lower())
        
        params = {'description': description}
        if table_match:
            params['table'] = table_match.group(1)
        if db_match:
            params['database_path'] = db_match.group(1)
        
        return params
    
    def _extract_compression_params(self, description: str) -> Dict[str, Any]:
        """Extract compression parameters"""
        # Look for file patterns and archive path
        files_match = re.findall(r'["\']([^"\']*\.[\w]+)["\']', description)
        archive_match = re.search(r'to\s+["\']?([^"\']+)["\']?', description)
        
        params = {'description': description}
        if files_match:
            params['files'] = files_match
        if archive_match:
            params['archive_path'] = archive_match.group(1)
        
        return params
    
    def _extract_analysis_params(self, description: str) -> Dict[str, Any]:
        """Extract data analysis parameters"""
        # Look for analysis type
        analysis_types = ['sum', 'average', 'count', 'min', 'max', 'total']
        for analysis_type in analysis_types:
            if analysis_type in description.lower():
                return {
                    'operation': analysis_type,
                    'description': description
                }
        return {'operation': 'count', 'description': description}
    
    def _extract_notification_params(self, description: str) -> Dict[str, Any]:
        """Extract notification parameters"""
        # Look for title and message
        title_match = re.search(r'title[:\s]+["\']?([^"\']+)["\']?', description.lower())
        message_match = re.search(r'message[:\s]+["\']?([^"\']+)["\']?', description.lower())
        
        params = {'description': description}
        if title_match:
            params['title'] = title_match.group(1)
        if message_match:
            params['message'] = message_match.group(1)
        
        return params
    
    def _resolve_dependencies(self, steps: List[WorkflowStep]):
        """Resolve dependencies between steps with enhanced logic"""
        for i, step in enumerate(steps):
            # Enhanced dependency resolution
            if i > 0:
                step.dependencies.append(steps[i-1].step_id)
            
            # Look for explicit dependencies in the description
            if 'using' in step.description.lower() or 'from' in step.description.lower():
                # Try to find which previous step this depends on
                for j in range(i):
                    if any(word in step.description.lower() for word in steps[j].description.lower().split()):
                        if steps[j].step_id not in step.dependencies:
                            step.dependencies.append(steps[j].step_id)
