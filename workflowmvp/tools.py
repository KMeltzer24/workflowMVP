"""
Tool Registry - Common workflow operations and tools
"""

import csv
import hashlib
import json
import os
import re
import shutil
import smtplib
import sqlite3
import subprocess
import sys
import time
from datetime import datetime
from datetime import timezone as dt_timezone
from zoneinfo import ZoneInfo
import warnings
from dataclasses import dataclass
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Any, Callable, Dict, List, Optional

# macOS system Python is commonly linked against LibreSSL, which triggers a noisy
# urllib3 warning on import. Suppress only that exact warning message.
warnings.filterwarnings(
    "ignore",
    message=r"urllib3 v2 only supports OpenSSL 1\.1\.1\+.*LibreSSL.*",
)

import requests  # noqa: E402


@dataclass
class Tool:
    """Represents a workflow tool"""
    name: str
    description: str
    function: Callable
    parameters: Dict[str, str]  # parameter_name -> description


class ToolRegistry:
    """Registry of available workflow tools"""

    COMMAND_DENY_PATTERNS = [
        r"\brm\s+-rf\b",
        r"\bsudo\b",
        r"\bmkfs\b",
        r"\bshutdown\b",
        r"\breboot\b",
        r"\bkillall\b",
        r">\s*/",
        r":\(\)\s*\{",
    ]

    def __init__(self, safety_profile: Optional[str] = None):
        self.tools: Dict[str, Tool] = {}
        profile = (
            safety_profile or os.getenv("WORKFLOW_SAFETY_PROFILE", "safe")
        ).strip().lower()
        self.safety_profile = profile if profile in {"safe", "full"} else "safe"
        sandbox_root = os.getenv("WORKFLOW_OUTPUT_DIR")
        self.sandbox_root = os.path.abspath(sandbox_root) if sandbox_root else None
        self._register_default_tools()

    def _wrap_tool_function(self, tool_name: str, func: Callable) -> Callable:
        """Wrap tool calls with a standardized response envelope."""

        def wrapped(*args, **kwargs):  # type: ignore[no-untyped-def]
            try:
                raw = func(*args, **kwargs)
            except Exception as exc:  # pragma: no cover - defensive
                raw = {"success": False, "error": str(exc)}
            return self._normalize_tool_response(tool_name, raw)

        return wrapped

    def _normalize_tool_response(self, tool_name: str, payload: Any) -> Dict[str, Any]:
        """Ensure all tool responses have consistent keys.

        Contract:
          - success: bool
          - error: str | None
          - result: Any
          - meta: dict
        """
        if not isinstance(payload, dict):
            payload = {"success": True, "result": payload}

        normalized = dict(payload)
        success = bool(normalized.get("success"))
        normalized["success"] = success

        if success:
            inferred_result = (
                normalized.get("result")
                if "result" in normalized
                else normalized.get("content")
                if "content" in normalized
                else normalized.get("message")
            )
            normalized["result"] = inferred_result
            normalized["error"] = None
        else:
            normalized["result"] = normalized.get("result")
            normalized["error"] = str(normalized.get("error") or "Unknown tool error")

        meta = normalized.get("meta")
        if not isinstance(meta, dict):
            meta = {}
        meta.setdefault("tool", tool_name)
        normalized["meta"] = meta

        return normalized

    _BROWSER_HEADERS = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
    }

    @classmethod
    def _request_with_retry(
        cls,
        url: str,
        timeout: int = 30,
        attempts: int = 3,
        base_backoff: float = 0.4,
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        """GET a URL with exponential backoff for transient request failures."""
        merged_headers = {**cls._BROWSER_HEADERS, **(headers or {})}
        last_exc: Optional[Exception] = None
        for attempt in range(1, attempts + 1):
            try:
                response = requests.get(url, timeout=timeout, headers=merged_headers)
                response.raise_for_status()
                return response
            except requests.RequestException as exc:
                last_exc = exc
                if attempt == attempts:
                    break
                time.sleep(base_backoff * (2 ** (attempt - 1)))
        raise RuntimeError(f"Request failed after {attempts} attempts: {last_exc}")

    def _sandbox_path(self, raw_path: str) -> str:
        """Resolve path and enforce run sandbox boundaries when configured."""
        if not raw_path:
            raise ValueError("Path is required")
        if self.sandbox_root is None:
            return raw_path

        candidate = (
            raw_path
            if os.path.isabs(raw_path)
            else os.path.join(self.sandbox_root, raw_path)
        )
        normalized = os.path.abspath(candidate)
        if not (
            normalized == self.sandbox_root
            or normalized.startswith(self.sandbox_root + os.sep)
        ):
            raise PermissionError(
                f"Path '{raw_path}' is outside sandbox '{self.sandbox_root}'"
            )
        return normalized

    @classmethod
    def _blocked_command_reason(cls, command: str) -> Optional[str]:
        lowered = command.lower()
        for pattern in cls.COMMAND_DENY_PATTERNS:
            if re.search(pattern, lowered):
                return f"Command blocked by safety policy ({pattern})"
        return None

    def register_tool(self, tool: Tool):
        """Register a new tool"""
        self.tools[tool.name] = Tool(
            name=tool.name,
            description=tool.description,
            function=self._wrap_tool_function(tool.name, tool.function),
            parameters=tool.parameters,
        )

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

        self.register_tool(Tool(
            name="send_email",
            description=(
                "Send an email via SMTP. Credentials come from arguments or env vars (never from input()). "
                "Optional attachments: list of relative file paths (read from sandbox cwd)."
            ),
            function=self._send_email,
            parameters={
                "recipient": "Email recipient",
                "subject": "Email subject",
                "body": "Email body (plain text); use a short line like 'See attached.' when sending files",
                "attachments": "Optional: list of file paths to attach, or a single path string",
                "smtp_server": "SMTP server (default: env SMTP_SERVER or smtp.gmail.com)",
                "smtp_port": "SMTP port (default: env SMTP_PORT or 587)",
                "email_user": "SMTP username (default: env EMAIL_USER)",
                "email_password": "SMTP password / app password (default: env EMAIL_PASSWORD)",
                "email_from": "From address (default: env EMAIL_FROM or email_user)",
            },
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

        # Web scraping
        self.register_tool(Tool(
            name="scrape_webpage",
            description="Scrape content from webpage",
            function=self._scrape_webpage,
            parameters={
                "url": "URL to scrape",
            }
        ))

        # HTTP / API tools
        self.register_tool(Tool(
            name="http_request",
            description=(
                "Make an HTTP request (GET, POST, PUT, PATCH, DELETE) to any URL. "
                "Use this to call REST APIs, send webhooks, or submit forms. "
                "Supports custom headers and a JSON or text body."
            ),
            function=self._http_request,
            parameters={
                "url": "Target URL",
                "method": "HTTP method: GET, POST, PUT, PATCH, DELETE (default: GET)",
                "body": "Request body as a dict (sent as JSON) or string (sent as text). Optional.",
                "headers": "Extra headers as a dict (e.g. {'Authorization': 'Bearer token'}). Optional.",
                "timeout": "Timeout in seconds (default: 30)",
            },
        ))

        # AI text generation
        self.register_tool(Tool(
            name="generate_text",
            description=(
                "Generate text using the configured AI model (Gemini / Groq / OpenRouter). "
                "Use for writing, summarising, translating, classifying, formatting data as prose, "
                "or any task that requires language understanding. "
                "Pass the full instruction in 'prompt'; the model returns plain text."
            ),
            function=self._generate_text,
            parameters={
                "prompt": "Full instruction for the AI (e.g. 'Write a limerick about 5432.10')",
                "max_tokens": "Maximum tokens to generate (default: 1000)",
            },
        ))

        # Financial data
        self.register_tool(Tool(
            name="fetch_stock_price",
            description=(
                "Fetch the current or recent price of a stock or index using its ticker symbol "
                "(e.g. ^GSPC for S&P 500, AAPL for Apple). Returns price, currency, and metadata."
            ),
            function=self._fetch_stock_price,
            parameters={
                "ticker": "Ticker symbol (e.g. '^GSPC', 'AAPL', 'BTC-USD')",
                "period": "Data period: '1d', '5d', '1mo', etc. (default: '1d')",
            },
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

        self.register_tool(Tool(
            name="read_json",
            description="Read a UTF-8 JSON file and parse it into Python objects (returned as JSON text and structured data).",
            function=self._read_json,
            parameters={
                "file_path": "Path to the .json file",
                "encoding": "File encoding (default: utf-8)",
            },
        ))

        self.register_tool(Tool(
            name="write_json",
            description="Write a dict or list to a JSON file (pretty-printed by default).",
            function=self._write_json,
            parameters={
                "file_path": "Path to the output .json file",
                "data": "Dict or list to serialize (may be passed from json.loads or Python literals)",
                "indent": "Indent level for pretty-printing (default: 2; use None for compact)",
                "encoding": "File encoding (default: utf-8)",
            },
        ))

        self.register_tool(Tool(
            name="append_file",
            description="Append text to the end of a file (creates the file if it does not exist).",
            function=self._append_file,
            parameters={
                "file_path": "Path to the file",
                "content": "Text to append",
                "encoding": "File encoding (default: utf-8)",
            },
        ))

        self.register_tool(Tool(
            name="hash_file",
            description="Compute a cryptographic hash of file contents (default SHA-256, hex-encoded).",
            function=self._hash_file,
            parameters={
                "file_path": "Path to the file",
                "algorithm": "Hash name, e.g. sha256, sha1, md5 (default: sha256)",
            },
        ))

        self.register_tool(Tool(
            name="get_current_time",
            description=(
                "Return the current date/time in an IANA timezone (e.g. America/New_York) "
                "as ISO 8601 string and Unix timestamp. Use UTC if unsure."
            ),
            function=self._get_current_time,
            parameters={
                "timezone": "IANA zone name (default: UTC), e.g. America/Los_Angeles",
            },
        ))

    # Tool implementations
    def _download(self, url: str, output_file: str = None) -> Dict[str, Any]:
        """Download content from URL"""
        try:
            response = self._request_with_retry(url, timeout=30, attempts=3)

            if output_file:
                safe_output = self._sandbox_path(output_file)
                parent = os.path.dirname(safe_output)
                if parent:
                    os.makedirs(parent, exist_ok=True)
                with open(safe_output, 'wb') as f:
                    f.write(response.content)
                return {"success": True, "file": safe_output, "size": len(response.content)}
            else:
                return {"success": True, "content": response.text, "size": len(response.content)}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def _read_file(self, file_path: str, encoding: str = 'utf-8') -> Dict[str, Any]:
        """Read content from file"""
        try:
            safe_path = self._sandbox_path(file_path)
            with open(safe_path, encoding=encoding) as f:
                content = f.read()
            return {"success": True, "content": content, "size": len(content)}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def _write_file(self, file_path: str, content: str, encoding: str = 'utf-8') -> Dict[str, Any]:
        """Write content to file"""
        try:
            safe_path = self._sandbox_path(file_path)
            parent = os.path.dirname(safe_path)
            if parent:
                os.makedirs(parent, exist_ok=True)
            with open(safe_path, 'w', encoding=encoding) as f:
                f.write(content)
            return {"success": True, "file": safe_path, "size": len(content)}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def _read_json(self, file_path: str, encoding: str = "utf-8") -> Dict[str, Any]:
        """Read and parse JSON from a file."""
        try:
            safe_path = self._sandbox_path(file_path)
            with open(safe_path, encoding=encoding) as f:
                raw = f.read()
            data = json.loads(raw)
            text = json.dumps(data, indent=2, ensure_ascii=False)
            return {"success": True, "content": text, "data": data, "size": len(raw)}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def _write_json(
        self,
        file_path: str,
        data: Any,
        indent: Any = 2,
        encoding: str = "utf-8",
    ) -> Dict[str, Any]:
        """Write JSON-serializable data to a file."""
        try:
            if isinstance(data, str):
                try:
                    data = json.loads(data)
                except json.JSONDecodeError:
                    return {"success": False, "error": "data must be dict/list or a JSON string"}
            if not isinstance(data, (dict, list)):
                return {"success": False, "error": "data must be a dict or list (or JSON string)"}
            safe_path = self._sandbox_path(file_path)
            parent = os.path.dirname(safe_path)
            if parent:
                os.makedirs(parent, exist_ok=True)
            if indent is None or (isinstance(indent, str) and indent.lower() in ("none", "null")):
                ind = None
            else:
                ind = int(indent)
            text = json.dumps(data, indent=ind, ensure_ascii=False)
            with open(safe_path, "w", encoding=encoding) as f:
                f.write(text)
            return {"success": True, "file": safe_path, "size": len(text)}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def _append_file(self, file_path: str, content: str, encoding: str = "utf-8") -> Dict[str, Any]:
        """Append text to a file."""
        try:
            safe_path = self._sandbox_path(file_path)
            parent = os.path.dirname(safe_path)
            if parent:
                os.makedirs(parent, exist_ok=True)
            with open(safe_path, "a", encoding=encoding) as f:
                f.write(content)
            return {"success": True, "file": safe_path, "size": len(content)}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def _hash_file(self, file_path: str, algorithm: str = "sha256") -> Dict[str, Any]:
        """Hash file contents."""
        try:
            safe_path = self._sandbox_path(file_path)
            algo = (algorithm or "sha256").lower()
            h = hashlib.new(algo)
            with open(safe_path, "rb") as f:
                for chunk in iter(lambda: f.read(65536), b""):
                    h.update(chunk)
            digest = h.hexdigest()
            return {
                "success": True,
                "hex_digest": digest,
                "algorithm": algo,
                "file_path": file_path,
                "result": digest,
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    def _get_current_time(self, timezone: str = "UTC") -> Dict[str, Any]:
        """Current time in an IANA timezone."""
        try:
            tz_name = (timezone or "UTC").strip()
            if tz_name.upper() in ("UTC", "GMT", "Z", "ZULU"):
                now = datetime.now(dt_timezone.utc)
                tz_label = "UTC"
            else:
                tz = ZoneInfo(tz_name)
                now = datetime.now(tz)
                tz_label = tz_name
            iso = now.isoformat()
            return {
                "success": True,
                "iso": iso,
                "timezone": tz_label,
                "unix": int(now.timestamp()),
                "result": iso,
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    def _send_email(
        self,
        recipient: str,
        subject: str,
        body: str,
        attachments: Any = None,
        smtp_server: Optional[str] = None,
        smtp_port: Optional[int] = None,
        email_user: Optional[str] = None,
        email_password: Optional[str] = None,
        email_from: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Send email using explicit args first, falling back to environment variables.

        Never prompts interactively: when the script runs as a subprocess under
        the Flask server there is no stdin, so an input() prompt would hang the
        run indefinitely. Missing creds are reported as a structured error so
        the UI can surface them and re-run with creds attached.

        ``attachments`` may be a list of relative paths or a single path string;
        files are read after ``_sandbox_path`` resolution.
        """
        try:
            email_user = email_user or os.getenv("EMAIL_USER")
            email_password = email_password or os.getenv("EMAIL_PASSWORD")
            email_from = email_from or os.getenv("EMAIL_FROM") or email_user
            smtp_server = smtp_server or os.getenv("SMTP_SERVER") or "smtp.gmail.com"
            if smtp_port is None:
                smtp_port_raw = os.getenv("SMTP_PORT", "587")
                try:
                    smtp_port = int(smtp_port_raw)
                except (TypeError, ValueError):
                    smtp_port = 587

            missing = [
                name
                for name, value in (
                    ("EMAIL_USER", email_user),
                    ("EMAIL_PASSWORD", email_password),
                    ("EMAIL_FROM", email_from),
                )
                if not value
            ]
            if missing:
                return {
                    "success": False,
                    "error": (
                        "Missing SMTP credentials: "
                        + ", ".join(missing)
                        + ". Set them in Settings or .env."
                    ),
                    "required": missing,
                }

            attach_paths: List[str] = []
            if attachments is not None:
                if isinstance(attachments, str):
                    attach_paths = [attachments] if attachments.strip() else []
                elif isinstance(attachments, (list, tuple)):
                    attach_paths = [str(p) for p in attachments if p and str(p).strip()]

            text_body = (body or "").strip()
            if not text_body and attach_paths:
                text_body = "See attached."

            msg = MIMEMultipart()
            msg["From"] = email_from
            msg["To"] = recipient
            msg["Subject"] = subject
            msg.attach(MIMEText(text_body, "plain", "utf-8"))

            for rel in attach_paths:
                safe = self._sandbox_path(rel)
                if not os.path.isfile(safe):
                    return {
                        "success": False,
                        "error": f"Attachment not found or not a file: {rel}",
                    }
                with open(safe, "rb") as f:
                    blob = f.read()
                part = MIMEApplication(blob)
                part.add_header(
                    "Content-Disposition",
                    "attachment",
                    filename=os.path.basename(safe),
                )
                msg.attach(part)

            attempts = 3
            for attempt in range(1, attempts + 1):
                server = None
                try:
                    if smtp_port == 465:
                        server = smtplib.SMTP_SSL(smtp_server, smtp_port, timeout=30)
                    else:
                        server = smtplib.SMTP(smtp_server, smtp_port, timeout=30)
                        server.starttls()
                    server.login(email_user, email_password)
                    server.sendmail(email_from, recipient, msg.as_string())
                    break
                except (smtplib.SMTPException, OSError, TimeoutError):
                    if attempt == attempts:
                        raise
                    time.sleep(0.4 * (2 ** (attempt - 1)))
                finally:
                    if server is not None:
                        try:
                            server.quit()
                        except Exception:
                            pass

            return {
                "success": True,
                "message": f"Email sent successfully to {recipient}",
            }
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
            safe_dir = self._sandbox_path(directory)
            if not os.path.exists(safe_dir):
                return {"success": False, "error": "Directory does not exist"}

            files = []
            for item in os.listdir(safe_dir):
                item_path = os.path.join(safe_dir, item)
                if os.path.isfile(item_path):
                    if pattern is None or pattern in item:
                        files.append(item)

            return {"success": True, "files": files}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def _create_directory(self, directory: str) -> Dict[str, Any]:
        """Create directory"""
        try:
            safe_dir = self._sandbox_path(directory)
            os.makedirs(safe_dir, exist_ok=True)
            return {"success": True, "directory": safe_dir}
        except Exception as e:
            return {"success": False, "error": str(e)}

    # Database operations
    def _sqlite_query(self, database_path: str, query: str, params: Optional[List] = None) -> Dict[str, Any]:
        """Execute SQL query on SQLite database"""
        try:
            safe_db = self._sandbox_path(database_path)
            conn = sqlite3.connect(safe_db)
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
            safe_db = self._sandbox_path(database_path)
            conn = sqlite3.connect(safe_db)
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
            safe_path = self._sandbox_path(file_path)
            with open(safe_path, encoding=encoding) as f:
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

            safe_path = self._sandbox_path(file_path)
            parent = os.path.dirname(safe_path)
            if parent:
                os.makedirs(parent, exist_ok=True)

            with open(safe_path, 'w', newline='', encoding='utf-8') as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(data)

            return {"success": True, "file": safe_path, "rows": len(data)}
        except Exception as e:
            return {"success": False, "error": str(e)}

    # File operations
    def _copy_file(self, source: str, destination: str) -> Dict[str, Any]:
        """Copy file from source to destination"""
        try:
            safe_source = self._sandbox_path(source)
            safe_destination = self._sandbox_path(destination)
            parent = os.path.dirname(safe_destination)
            if parent:
                os.makedirs(parent, exist_ok=True)
            shutil.copy2(safe_source, safe_destination)
            return {"success": True, "source": safe_source, "destination": safe_destination}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def _move_file(self, source: str, destination: str) -> Dict[str, Any]:
        """Move file from source to destination"""
        try:
            safe_source = self._sandbox_path(source)
            safe_destination = self._sandbox_path(destination)
            parent = os.path.dirname(safe_destination)
            if parent:
                os.makedirs(parent, exist_ok=True)
            shutil.move(safe_source, safe_destination)
            return {"success": True, "source": safe_source, "destination": safe_destination}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def _delete_file(self, file_path: str) -> Dict[str, Any]:
        """Delete a file"""
        try:
            safe_path = self._sandbox_path(file_path)
            if os.path.exists(safe_path):
                os.remove(safe_path)
                return {"success": True, "file": safe_path}
            else:
                return {"success": False, "error": "File not found"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    # System operations
    def _run_command(self, command: str, timeout: int = 30) -> Dict[str, Any]:
        """Execute system command"""
        try:
            blocked_reason = self._blocked_command_reason(command)
            if blocked_reason:
                return {"success": False, "error": blocked_reason, "blocked": True}
            if self.safety_profile == "safe":
                return {
                    "success": False,
                    "error": "run_command is disabled in safe mode",
                    "blocked": True,
                }
            result = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=self.sandbox_root or None,
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

    # Web scraping
    _SCRAPE_MAX_CHARS = 4000  # keep payloads well inside LLM context limits

    def _scrape_webpage(self, url: str, selector: Optional[str] = None, extract_text: bool = True) -> Dict[str, Any]:
        """Scrape a webpage and return clean readable text (HTML tags stripped).

        Uses BeautifulSoup when available to extract only visible text, removing
        scripts, styles, navigation, and other noise. Falls back to raw HTML if
        BeautifulSoup is not installed. Content is truncated to _SCRAPE_MAX_CHARS
        to stay within LLM context limits.
        """
        try:
            response = self._request_with_retry(url, timeout=30, attempts=3)
            raw_html = response.text

            try:
                from bs4 import BeautifulSoup

                soup = BeautifulSoup(raw_html, "html.parser")
                # Remove non-content elements
                for tag in soup(["script", "style", "nav", "header", "footer",
                                  "aside", "noscript", "iframe", "form"]):
                    tag.decompose()
                # Get visible text with whitespace normalised
                text = soup.get_text(separator="\n")
                text = "\n".join(
                    line.strip() for line in text.splitlines() if line.strip()
                )
            except ImportError:
                text = raw_html  # fallback: raw HTML

            truncated = len(text) > self._SCRAPE_MAX_CHARS
            content = text[: self._SCRAPE_MAX_CHARS] if truncated else text
            result: Dict[str, Any] = {"success": True, "content": content, "url": url}
            if truncated:
                result["note"] = f"Content truncated to {self._SCRAPE_MAX_CHARS} chars (original: {len(text)})"
            return result
        except Exception as e:
            return {"success": False, "error": str(e)}

    def _generate_text(self, prompt: str, max_tokens: int = 1000) -> Dict[str, Any]:
        """Call the configured LLM to generate text."""
        try:
            provider = os.getenv("LLM_PROVIDER", "gemini").strip().lower()
            api_key = None
            if provider == "gemini":
                api_key = os.getenv("GEMINI_API_KEY")
            elif provider == "groq":
                api_key = os.getenv("GROQ_API_KEY")
            else:
                provider = "openrouter"
                api_key = os.getenv("OPENROUTER_API_KEY")

            if not api_key:
                return {
                    "success": False,
                    "error": (
                        f"No API key found for provider '{provider}'. "
                        "Set GEMINI_API_KEY / GROQ_API_KEY / OPENROUTER_API_KEY in .env."
                    ),
                }

            if provider == "gemini":
                from google import genai as google_genai
                from google.genai import types as genai_types

                model_name = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
                client = google_genai.Client(api_key=api_key)
                response = client.models.generate_content(
                    model=model_name,
                    contents=prompt,
                    config=genai_types.GenerateContentConfig(
                        temperature=0.7,
                        max_output_tokens=max_tokens,
                    ),
                )
                text = response.text or ""
            else:
                if provider == "groq":
                    url = "https://api.groq.com/openai/v1/chat/completions"
                    model_name = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
                    extra_headers: Dict[str, str] = {}
                else:
                    url = "https://openrouter.ai/api/v1/chat/completions"
                    model_name = os.getenv("OPENROUTER_MODEL", "meta-llama/llama-3.1-70b-instruct")
                    extra_headers = {
                        "HTTP-Referer": os.getenv("OPENROUTER_SITE_URL", "http://localhost:5050"),
                        "X-Title": os.getenv("OPENROUTER_APP_NAME", "WorkflowMVP"),
                    }
                headers = {
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                    **extra_headers,
                }
                payload = {
                    "model": model_name,
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.7,
                    "max_tokens": max_tokens,
                }
                resp = requests.post(url, headers=headers, json=payload, timeout=60)
                resp.raise_for_status()
                data = resp.json()
                choices = data.get("choices") or []
                if not choices:
                    return {"success": False, "error": f"{provider} returned no choices."}
                text = (choices[0].get("message") or {}).get("content", "") or ""

            return {"success": True, "result": text.strip()}
        except Exception as exc:
            return {"success": False, "error": str(exc)}

    def _http_request(
        self,
        url: str,
        method: str = "GET",
        body: Any = None,
        headers: Optional[Dict[str, str]] = None,
        timeout: int = 30,
    ) -> Dict[str, Any]:
        """Make an HTTP request with optional body and headers."""
        try:
            method = method.upper()
            if method not in {"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD"}:
                return {"success": False, "error": f"Unsupported HTTP method: {method}"}

            req_headers = {**self._BROWSER_HEADERS, **(headers or {})}

            kwargs: Dict[str, Any] = {"timeout": timeout, "headers": req_headers}
            if body is not None:
                if isinstance(body, dict):
                    kwargs["json"] = body
                    req_headers.setdefault("Content-Type", "application/json")
                else:
                    kwargs["data"] = str(body)

            response = requests.request(method, url, **kwargs)
            content_type = response.headers.get("Content-Type", "")
            if "application/json" in content_type:
                try:
                    result = response.json()
                except Exception:
                    result = response.text
            else:
                result = response.text

            return {
                "success": response.ok,
                "status_code": response.status_code,
                "result": result,
                "error": None if response.ok else f"HTTP {response.status_code}: {response.reason}",
            }
        except Exception as exc:
            return {"success": False, "error": str(exc)}

    def _fetch_stock_price(self, ticker: str, period: str = "1d") -> Dict[str, Any]:
        """Fetch stock/index price via yfinance (no scraping, no rate-limits)."""
        try:
            import yfinance as yf  # optional dep; graceful error if missing
        except ImportError:
            return {
                "success": False,
                "error": (
                    "yfinance is not installed. Run: pip3 install yfinance"
                ),
            }
        try:
            t = yf.Ticker(ticker)
            hist = t.history(period=period)
            if hist.empty:
                return {"success": False, "error": f"No data returned for ticker '{ticker}'"}
            latest = hist["Close"].iloc[-1]
            info = t.fast_info
            currency = getattr(info, "currency", "USD") or "USD"
            name = getattr(info, "long_name", ticker) or ticker
            return {
                "success": True,
                "ticker": ticker,
                "name": name,
                "price": round(float(latest), 2),
                "currency": currency,
                "period": period,
            }
        except Exception as exc:
            return {"success": False, "error": str(exc)}

    # Notifications
    @staticmethod
    def _applescript_literal(value: str) -> str:
        """Quote a string for use inside AppleScript double-quoted text (escape \\ and ")."""
        return str(value).replace("\\", "\\\\").replace('"', '\\"')

    def _send_notification(self, title: str, message: str, urgency: str = "normal") -> Dict[str, Any]:
        """Send a desktop notification.

        On macOS, uses ``osascript`` (Notification Center). If that fails, tries
        ``terminal-notifier`` when installed. Failures return ``success=False``
        with stderr so callers are not misled when nothing appeared.

        On Linux without ``notify-send``, returns success with a note (CI/headless).
        """
        try:
            title_s = str(title)
            message_s = str(message)

            if os.name == "nt":  # Windows
                safe_title = title_s.replace("'", "''")
                safe_msg = message_s.replace("'", "''")
                proc = subprocess.run(
                    [
                        "powershell",
                        "-Command",
                        (
                            "[reflection.assembly]::loadwithpartialname('System.Windows.Forms')|Out-Null;"
                            f"[System.Windows.Forms.MessageBox]::Show('{safe_msg}','{safe_title}')"
                        ),
                    ],
                    capture_output=True,
                    timeout=10,
                    text=True,
                )
                if proc.returncode != 0:
                    err = (proc.stderr or proc.stdout or "").strip() or f"exit {proc.returncode}"
                    return {"success": False, "error": err}
            elif sys.platform == "darwin":  # macOS
                astitle = self._applescript_literal(title_s)
                asmsg = self._applescript_literal(message_s)
                script = f'display notification "{asmsg}" with title "{astitle}"'
                proc = subprocess.run(
                    ["osascript", "-e", script],
                    capture_output=True,
                    timeout=10,
                    text=True,
                )
                if proc.returncode != 0:
                    tn = shutil.which("terminal-notifier")
                    if tn:
                        proc2 = subprocess.run(
                            [tn, "-title", title_s, "-message", message_s],
                            capture_output=True,
                            timeout=10,
                            text=True,
                        )
                        if proc2.returncode == 0:
                            return {"success": True, "title": title_s, "message": message_s}
                    err = (proc.stderr or proc.stdout or "").strip() or f"osascript exit {proc.returncode}"
                    return {
                        "success": False,
                        "error": (
                            f"{err} — If you ran the workflow from a remote/headless environment, "
                            "macOS cannot show Notification Center banners there. Run locally in "
                            "Terminal (same user as the logged-in desktop), or allow automation "
                            "for your terminal app in System Settings → Privacy & Security."
                        ),
                    }
            else:  # Linux and other Unix
                if shutil.which("notify-send"):
                    proc = subprocess.run(
                        ["notify-send", title_s, message_s],
                        capture_output=True,
                        timeout=10,
                        text=True,
                    )
                    if proc.returncode != 0:
                        err = (proc.stderr or proc.stdout or "").strip() or f"exit {proc.returncode}"
                        return {"success": False, "error": err}
                else:
                    return {
                        "success": True,
                        "title": title_s,
                        "message": message_s,
                        "note": "notify-send not available; notification skipped",
                    }

            return {"success": True, "title": title_s, "message": message_s}
        except Exception as e:
            return {"success": False, "error": str(e)}

    # File compression
    def _compress_files(self, files: List[str], archive_path: str, include_dirs: bool = True) -> Dict[str, Any]:
        """Compress files into ZIP archive"""
        try:
            import zipfile

            safe_archive = self._sandbox_path(archive_path)
            parent = os.path.dirname(safe_archive)
            if parent:
                os.makedirs(parent, exist_ok=True)

            with zipfile.ZipFile(safe_archive, 'w', zipfile.ZIP_DEFLATED) as zipf:
                for file_path in files:
                    safe_file = self._sandbox_path(file_path)
                    if os.path.exists(safe_file):
                        if include_dirs:
                            arcname = (
                                os.path.relpath(safe_file, self.sandbox_root)
                                if self.sandbox_root
                                else safe_file
                            )
                            zipf.write(safe_file, arcname=arcname)
                        else:
                            zipf.write(safe_file, os.path.basename(safe_file))

            return {"success": True, "archive": safe_archive, "files": len(files)}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def _extract_archive(self, archive_path: str, extract_to: str, password: Optional[str] = None) -> Dict[str, Any]:
        """Extract files from ZIP archive"""
        try:
            import zipfile

            safe_archive = self._sandbox_path(archive_path)
            safe_extract_to = self._sandbox_path(extract_to)
            os.makedirs(safe_extract_to, exist_ok=True)

            with zipfile.ZipFile(safe_archive, 'r') as zipf:
                if password:
                    zipf.setpassword(password.encode())
                for member in zipf.namelist():
                    member_target = os.path.abspath(os.path.join(safe_extract_to, member))
                    if not (
                        member_target == safe_extract_to
                        or member_target.startswith(safe_extract_to + os.sep)
                    ):
                        return {
                            "success": False,
                            "error": f"Archive entry escapes destination: {member}",
                        }
                zipf.extractall(safe_extract_to)

            return {
                "success": True,
                "extracted_to": safe_extract_to,
                "archive": safe_archive,
            }
        except Exception as e:
            return {"success": False, "error": str(e)}
