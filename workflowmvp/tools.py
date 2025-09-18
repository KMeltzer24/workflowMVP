"""
Tool Registry - Common workflow operations and tools
"""

import os
import time
import requests
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Dict, Any, Callable, List
from dataclasses import dataclass


@dataclass
class Tool:
    """Represents a workflow tool"""
    name: str
    description: str
    function: Callable
    parameters: Dict[str, str]  # parameter_name -> description


class ToolRegistry:
    """Registry of available workflow tools"""
    
    def __init__(self):
        self.tools: Dict[str, Tool] = {}
        self._register_default_tools()
    
    def register_tool(self, tool: Tool):
        """Register a new tool"""
        self.tools[tool.name] = tool
    
    def get_tool(self, name: str) -> Tool:
        """Get a tool by name"""
        return self.tools.get(name)
    
    def list_tools(self) -> List[Tool]:
        """List all available tools"""
        return list(self.tools.values())
    
    def _register_default_tools(self):
        """Register default workflow tools"""
        
        # Download tool
        self.register_tool(Tool(
            name="download",
            description="Download content from a URL",
            function=self._download,
            parameters={
                "url": "URL to download from",
                "output_file": "Optional output file path"
            }
        ))
        
        # Read file tool
        self.register_tool(Tool(
            name="read_file",
            description="Read content from a file",
            function=self._read_file,
            parameters={
                "file_path": "Path to the file to read",
                "encoding": "File encoding (default: utf-8)"
            }
        ))
        
        # Write file tool
        self.register_tool(Tool(
            name="write_file",
            description="Write content to a file",
            function=self._write_file,
            parameters={
                "file_path": "Path to the file to write",
                "content": "Content to write",
                "encoding": "File encoding (default: utf-8)"
            }
        ))
        
        # Send email tool
        self.register_tool(Tool(
            name="send_email",
            description="Send an email",
            function=self._send_email,
            parameters={
                "recipient": "Email recipient",
                "subject": "Email subject",
                "body": "Email body",
                "smtp_server": "SMTP server (default: smtp.gmail.com)",
                "smtp_port": "SMTP port (default: 587)"
            }
        ))
        
        # Process data tool
        self.register_tool(Tool(
            name="process_data",
            description="Process or transform data",
            function=self._process_data,
            parameters={
                "data": "Data to process",
                "operation": "Processing operation to perform"
            }
        ))
        
        # Wait tool
        self.register_tool(Tool(
            name="wait",
            description="Wait for a specified amount of time",
            function=self._wait,
            parameters={
                "seconds": "Number of seconds to wait"
            }
        ))
        
        # HTTP request tool
        self.register_tool(Tool(
            name="http_request",
            description="Make an HTTP request",
            function=self._http_request,
            parameters={
                "url": "URL to request",
                "method": "HTTP method (GET, POST, etc.)",
                "headers": "Optional headers",
                "data": "Optional request data"
            }
        ))
        
        # File operations
        self.register_tool(Tool(
            name="list_files",
            description="List files in a directory",
            function=self._list_files,
            parameters={
                "directory": "Directory path to list",
                "pattern": "Optional file pattern filter"
            }
        ))
        
        self.register_tool(Tool(
            name="create_directory",
            description="Create a directory",
            function=self._create_directory,
            parameters={
                "directory": "Directory path to create"
            }
        ))
    
    # Tool implementations
    def _download(self, url: str, output_file: str = None) -> Dict[str, Any]:
        """Download content from URL"""
        try:
            response = requests.get(url, timeout=30)
            response.raise_for_status()
            
            if output_file:
                with open(output_file, 'wb') as f:
                    f.write(response.content)
                return {"success": True, "file": output_file, "size": len(response.content)}
            else:
                return {"success": True, "content": response.text, "size": len(response.content)}
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    def _read_file(self, file_path: str, encoding: str = 'utf-8') -> Dict[str, Any]:
        """Read content from file"""
        try:
            with open(file_path, 'r', encoding=encoding) as f:
                content = f.read()
            return {"success": True, "content": content, "size": len(content)}
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    def _write_file(self, file_path: str, content: str, encoding: str = 'utf-8') -> Dict[str, Any]:
        """Write content to file"""
        try:
            # Create directory if it doesn't exist
            os.makedirs(os.path.dirname(file_path), exist_ok=True)
            
            with open(file_path, 'w', encoding=encoding) as f:
                f.write(content)
            return {"success": True, "file": file_path, "size": len(content)}
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    def _send_email(self, recipient: str, subject: str, body: str, 
                   smtp_server: str = "smtp.gmail.com", smtp_port: int = 587) -> Dict[str, Any]:
        """Send email with interactive SMTP setup"""
        try:
            # Check if credentials are already set
            email_user = os.getenv('EMAIL_USER')
            email_password = os.getenv('EMAIL_PASSWORD')
            email_from = os.getenv('EMAIL_FROM')
            
            # If not set, prompt user for credentials
            if not all([email_user, email_password, email_from]):
                print("\n📧 Email Setup Required")
                print("=" * 30)
                print("Defaults for Gmail:")
                print("- SMTP server: smtp.gmail.com")
                print("- Port 587: STARTTLS (recommended)")
                print("- Port 465: SSL")
                print()
                email_from = input("Enter your email address (e.g., name@gmail.com): ").strip()
                email_user = input("Enter your email username (use full email, e.g., name@gmail.com): ").strip()
                email_password = input("Enter your Gmail App Password (generate in Google Account > Security > App passwords): ").strip()
                smtp_server = input(f"SMTP server [default: {smtp_server}]: ").strip() or smtp_server
                entered_port = input(f"SMTP port [587 for STARTTLS or 465 for SSL | default: {smtp_port}]: ").strip()
                if entered_port:
                    smtp_port = int(entered_port)
                print()
            
            # Create message
            msg = MIMEMultipart()
            msg['From'] = email_from
            msg['To'] = recipient
            msg['Subject'] = subject
            msg.attach(MIMEText(body, 'plain'))
            
            # Send email (auto-select SSL for port 465, STARTTLS otherwise)
            if smtp_port == 465:
                server = smtplib.SMTP_SSL(smtp_server, smtp_port)
            else:
                server = smtplib.SMTP(smtp_server, smtp_port)
                server.starttls()
            server.login(email_user, email_password)
            text = msg.as_string()
            server.sendmail(email_from, recipient, text)
            server.quit()
            
            return {"success": True, "message": f"Email sent successfully to {recipient}"}
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    def _process_data(self, data: Any, operation: str) -> Dict[str, Any]:
        """Process data based on operation"""
        try:
            if operation.lower() == 'uppercase' and isinstance(data, str):
                result = data.upper()
            elif operation.lower() == 'lowercase' and isinstance(data, str):
                result = data.lower()
            elif operation.lower() == 'count' and isinstance(data, str):
                result = len(data)
            elif operation.lower() == 'reverse' and isinstance(data, str):
                result = data[::-1]
            else:
                result = f"Processed: {data} with operation: {operation}"
            
            return {"success": True, "result": result}
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    def _wait(self, seconds: int) -> Dict[str, Any]:
        """Wait for specified seconds"""
        try:
            time.sleep(seconds)
            return {"success": True, "waited": seconds}
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    def _http_request(self, url: str, method: str = "GET", 
                     headers: Dict = None, data: Dict = None) -> Dict[str, Any]:
        """Make HTTP request"""
        try:
            response = requests.request(method, url, headers=headers, json=data, timeout=30)
            return {
                "success": True,
                "status_code": response.status_code,
                "content": response.text,
                "headers": dict(response.headers)
            }
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    def _list_files(self, directory: str, pattern: str = None) -> Dict[str, Any]:
        """List files in directory"""
        try:
            if not os.path.exists(directory):
                return {"success": False, "error": "Directory does not exist"}
            
            files = []
            for item in os.listdir(directory):
                item_path = os.path.join(directory, item)
                if os.path.isfile(item_path):
                    if pattern is None or pattern in item:
                        files.append(item)
            
            return {"success": True, "files": files}
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    def _create_directory(self, directory: str) -> Dict[str, Any]:
        """Create directory"""
        try:
            os.makedirs(directory, exist_ok=True)
            return {"success": True, "directory": directory}
        except Exception as e:
            return {"success": False, "error": str(e)}
