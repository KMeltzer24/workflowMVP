"""
Tool Registry - Common workflow operations and tools
"""

import os
import time
import requests
import smtplib
import sqlite3
import json
import csv
import subprocess
import shutil
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Dict, Any, Callable, List, Optional
from dataclasses import dataclass
from pathlib import Path


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
        
        # Database operations
        self.register_tool(Tool(
            name="sqlite_query",
            description="Execute SQL query on SQLite database",
            function=self._sqlite_query,
            parameters={
                "database_path": "Path to SQLite database file",
                "query": "SQL query to execute",
                "params": "Optional query parameters (list or dict)"
            }
        ))
        
        self.register_tool(Tool(
            name="sqlite_insert",
            description="Insert data into SQLite database",
            function=self._sqlite_insert,
            parameters={
                "database_path": "Path to SQLite database file",
                "table": "Table name",
                "data": "Data to insert (dict or list of dicts)"
            }
        ))
        
        # Data processing
        self.register_tool(Tool(
            name="read_csv",
            description="Read and parse CSV file",
            function=self._read_csv,
            parameters={
                "file_path": "Path to CSV file",
                "delimiter": "CSV delimiter (default: comma)",
                "encoding": "File encoding (default: utf-8)"
            }
        ))
        
        self.register_tool(Tool(
            name="write_csv",
            description="Write data to CSV file",
            function=self._write_csv,
            parameters={
                "file_path": "Path to CSV file",
                "data": "Data to write (list of dicts)",
                "fieldnames": "Column names (optional)"
            }
        ))
        
        self.register_tool(Tool(
            name="process_json",
            description="Process and transform JSON data",
            function=self._process_json,
            parameters={
                "json_data": "JSON data (string or dict)",
                "operation": "Operation to perform (extract, filter, transform)",
                "path": "JSONPath for extraction (optional)"
            }
        ))
        
        # File operations
        self.register_tool(Tool(
            name="copy_file",
            description="Copy file from source to destination",
            function=self._copy_file,
            parameters={
                "source": "Source file path",
                "destination": "Destination file path"
            }
        ))
        
        self.register_tool(Tool(
            name="move_file",
            description="Move file from source to destination",
            function=self._move_file,
            parameters={
                "source": "Source file path",
                "destination": "Destination file path"
            }
        ))
        
        self.register_tool(Tool(
            name="delete_file",
            description="Delete a file",
            function=self._delete_file,
            parameters={
                "file_path": "Path to file to delete"
            }
        ))
        
        # System operations
        self.register_tool(Tool(
            name="run_command",
            description="Execute system command",
            function=self._run_command,
            parameters={
                "command": "Command to execute",
                "timeout": "Timeout in seconds (default: 30)"
            }
        ))
        
        # Data analysis
        self.register_tool(Tool(
            name="analyze_data",
            description="Perform basic data analysis",
            function=self._analyze_data,
            parameters={
                "data": "Data to analyze (list of numbers or dicts)",
                "operation": "Analysis type (sum, average, count, min, max)"
            }
        ))
        
        # Web scraping
        self.register_tool(Tool(
            name="scrape_webpage",
            description="Scrape content from webpage",
            function=self._scrape_webpage,
            parameters={
                "url": "URL to scrape",
                "selector": "CSS selector for specific elements (optional)",
                "extract_text": "Extract text content (default: True)"
            }
        ))
        
        # Notification tools
        self.register_tool(Tool(
            name="send_notification",
            description="Send desktop notification",
            function=self._send_notification,
            parameters={
                "title": "Notification title",
                "message": "Notification message",
                "urgency": "Urgency level (low, normal, critical)"
            }
        ))
        
        # File compression
        self.register_tool(Tool(
            name="compress_files",
            description="Compress files into ZIP archive",
            function=self._compress_files,
            parameters={
                "files": "List of file paths to compress",
                "archive_path": "Path for the ZIP archive",
                "include_dirs": "Include directory structure (default: True)"
            }
        ))
        
        self.register_tool(Tool(
            name="extract_archive",
            description="Extract files from ZIP archive",
            function=self._extract_archive,
            parameters={
                "archive_path": "Path to ZIP archive",
                "extract_to": "Directory to extract to",
                "password": "Archive password (optional)"
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
    
    # Database operations
    def _sqlite_query(self, database_path: str, query: str, params: Optional[List] = None) -> Dict[str, Any]:
        """Execute SQL query on SQLite database"""
        try:
            conn = sqlite3.connect(database_path)
            cursor = conn.cursor()
            
            if params:
                cursor.execute(query, params)
            else:
                cursor.execute(query)
            
            if query.strip().upper().startswith('SELECT'):
                results = cursor.fetchall()
                columns = [description[0] for description in cursor.description] if cursor.description else []
                conn.close()
                return {"success": True, "results": results, "columns": columns}
            else:
                conn.commit()
                conn.close()
                return {"success": True, "message": "Query executed successfully"}
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    def _sqlite_insert(self, database_path: str, table: str, data: Dict[str, Any]) -> Dict[str, Any]:
        """Insert data into SQLite database"""
        try:
            conn = sqlite3.connect(database_path)
            cursor = conn.cursor()
            
            if isinstance(data, list):
                # Multiple records
                columns = list(data[0].keys())
                placeholders = ', '.join(['?' for _ in columns])
                query = f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({placeholders})"
                
                values = [tuple(record[col] for col in columns) for record in data]
                cursor.executemany(query, values)
            else:
                # Single record
                columns = list(data.keys())
                values = list(data.values())
                placeholders = ', '.join(['?' for _ in columns])
                query = f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({placeholders})"
                cursor.execute(query, values)
            
            conn.commit()
            conn.close()
            return {"success": True, "message": f"Inserted data into {table}"}
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    # Data processing
    def _read_csv(self, file_path: str, delimiter: str = ',', encoding: str = 'utf-8') -> Dict[str, Any]:
        """Read and parse CSV file"""
        try:
            with open(file_path, 'r', encoding=encoding) as f:
                reader = csv.DictReader(f, delimiter=delimiter)
                data = list(reader)
            return {"success": True, "data": data, "rows": len(data)}
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    def _write_csv(self, file_path: str, data: List[Dict], fieldnames: Optional[List[str]] = None) -> Dict[str, Any]:
        """Write data to CSV file"""
        try:
            if not data:
                return {"success": False, "error": "No data to write"}
            
            if not fieldnames:
                fieldnames = list(data[0].keys())
            
            os.makedirs(os.path.dirname(file_path), exist_ok=True)
            
            with open(file_path, 'w', newline='', encoding='utf-8') as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(data)
            
            return {"success": True, "file": file_path, "rows": len(data)}
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    def _process_json(self, json_data: Any, operation: str, path: Optional[str] = None) -> Dict[str, Any]:
        """Process and transform JSON data"""
        try:
            if isinstance(json_data, str):
                data = json.loads(json_data)
            else:
                data = json_data
            
            if operation == "extract" and path:
                # Simple path extraction (e.g., "data.users[0].name")
                result = data
                for part in path.split('.'):
                    if '[' in part and ']' in part:
                        key, index = part.split('[')
                        index = int(index.rstrip(']'))
                        result = result[key][index]
                    else:
                        result = result[part]
                return {"success": True, "result": result}
            elif operation == "filter" and path:
                # Filter based on path
                if isinstance(data, list):
                    filtered = [item for item in data if path in str(item)]
                    return {"success": True, "result": filtered}
                else:
                    return {"success": True, "result": data}
            else:
                return {"success": True, "result": data}
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    # File operations
    def _copy_file(self, source: str, destination: str) -> Dict[str, Any]:
        """Copy file from source to destination"""
        try:
            os.makedirs(os.path.dirname(destination), exist_ok=True)
            shutil.copy2(source, destination)
            return {"success": True, "source": source, "destination": destination}
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    def _move_file(self, source: str, destination: str) -> Dict[str, Any]:
        """Move file from source to destination"""
        try:
            os.makedirs(os.path.dirname(destination), exist_ok=True)
            shutil.move(source, destination)
            return {"success": True, "source": source, "destination": destination}
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    def _delete_file(self, file_path: str) -> Dict[str, Any]:
        """Delete a file"""
        try:
            if os.path.exists(file_path):
                os.remove(file_path)
                return {"success": True, "file": file_path}
            else:
                return {"success": False, "error": "File not found"}
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    # System operations
    def _run_command(self, command: str, timeout: int = 30) -> Dict[str, Any]:
        """Execute system command"""
        try:
            result = subprocess.run(
                command, 
                shell=True, 
                capture_output=True, 
                text=True, 
                timeout=timeout
            )
            return {
                "success": result.returncode == 0,
                "stdout": result.stdout,
                "stderr": result.stderr,
                "returncode": result.returncode
            }
        except subprocess.TimeoutExpired:
            return {"success": False, "error": f"Command timed out after {timeout} seconds"}
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    # Data analysis
    def _analyze_data(self, data: List, operation: str) -> Dict[str, Any]:
        """Perform basic data analysis"""
        try:
            if not data:
                return {"success": False, "error": "No data provided"}
            
            if operation == "sum":
                result = sum(data)
            elif operation == "average":
                result = sum(data) / len(data)
            elif operation == "count":
                result = len(data)
            elif operation == "min":
                result = min(data)
            elif operation == "max":
                result = max(data)
            else:
                return {"success": False, "error": f"Unknown operation: {operation}"}
            
            return {"success": True, "operation": operation, "result": result}
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    # Web scraping (basic implementation)
    def _scrape_webpage(self, url: str, selector: Optional[str] = None, extract_text: bool = True) -> Dict[str, Any]:
        """Scrape content from webpage"""
        try:
            response = requests.get(url, timeout=30)
            response.raise_for_status()
            
            if extract_text and not selector:
                # Simple text extraction
                content = response.text
                return {"success": True, "content": content, "url": url}
            else:
                # For CSS selector, would need BeautifulSoup
                return {"success": True, "content": response.text, "url": url, "note": "CSS selector parsing not implemented"}
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    # Notifications
    def _send_notification(self, title: str, message: str, urgency: str = "normal") -> Dict[str, Any]:
        """Send desktop notification"""
        try:
            # Try different notification methods based on OS
            if os.name == 'nt':  # Windows
                # Use Windows toast notifications
                subprocess.run(['powershell', '-Command', f'[System.Windows.Forms.MessageBox]::Show("{message}", "{title}")'], 
                             capture_output=True)
            else:  # Linux/Mac
                # Use notify-send or osascript
                subprocess.run(['notify-send', title, message], capture_output=True)
            
            return {"success": True, "title": title, "message": message}
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    # File compression
    def _compress_files(self, files: List[str], archive_path: str, include_dirs: bool = True) -> Dict[str, Any]:
        """Compress files into ZIP archive"""
        try:
            import zipfile
            
            with zipfile.ZipFile(archive_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
                for file_path in files:
                    if os.path.exists(file_path):
                        if include_dirs:
                            zipf.write(file_path)
                        else:
                            zipf.write(file_path, os.path.basename(file_path))
            
            return {"success": True, "archive": archive_path, "files": len(files)}
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    def _extract_archive(self, archive_path: str, extract_to: str, password: Optional[str] = None) -> Dict[str, Any]:
        """Extract files from ZIP archive"""
        try:
            import zipfile
            
            os.makedirs(extract_to, exist_ok=True)
            
            with zipfile.ZipFile(archive_path, 'r') as zipf:
                if password:
                    zipf.setpassword(password.encode())
                zipf.extractall(extract_to)
            
            return {"success": True, "extracted_to": extract_to, "archive": archive_path}
        except Exception as e:
            return {"success": False, "error": str(e)}
