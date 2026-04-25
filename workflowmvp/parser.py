"""
Workflow Parser - Extracts structured steps from text descriptions
"""

import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional


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

    REQUIRED_ACTION_PARAMS: Dict[str, List[str]] = {
        "download": ["url"],
        "read_file": ["file_path"],
        "read_json": ["file_path"],
        "write_file": ["file_path"],
        "write_json": ["file_path", "data"],
        "append_file": ["file_path", "content"],
        "hash_file": ["file_path"],
        "read_csv": ["file_path"],
        "write_csv": ["file_path"],
        "send_email": ["recipient"],
        "copy_file": ["source", "destination"],
        "move_file": ["source", "destination"],
        "delete_file": ["file_path"],
        "run_command": ["command"],
        "create_directory": ["directory"],
        "list_files": ["directory"],
        "sqlite_query": ["database_path"],
        "sqlite_insert": ["database_path", "table"],
        "compress_files": ["archive_path"],
        "extract_archive": ["archive_path", "extract_to"],
        "fetch_stock_price": ["ticker"],
        "generate_text": ["prompt"],
        "http_request": ["url"],
        "read_pdf": ["file_path"],
        "render_template": ["template"],
        "discover_urls": ["start_url"],
    }

    def parse_workflow(self, workflow_text: str) -> List[WorkflowStep]:
        """Parse workflow text into structured steps"""
        steps = []
        lines = workflow_text.strip().split('\n')

        current_step = None
        step_counter = 1

        i = 0
        while i < len(lines):
            raw_line = lines[i]
            line = raw_line.strip()
            if not line:
                i += 1
                continue

            # Check if this is a new step
            if self._is_step_start(line):
                if current_step:
                    steps.append(current_step)

                step_id = f"step_{step_counter}"
                description = self._extract_description(line)
                if not description and i + 1 < len(lines):
                    next_line = lines[i + 1].strip()
                    if next_line and not self._is_step_start(next_line):
                        description = next_line
                        i += 1
                action, parameters = self._extract_action_and_params(description)

                current_step = WorkflowStep(
                    step_id=step_id,
                    description=description,
                    action=action,
                    parameters=parameters,
                    dependencies=[]
                )
                step_counter += 1
                i += 1
            elif current_step and self._is_continuation_line(raw_line):
                current_step.description += f" {line}"
                action, params = self._extract_action_and_params(current_step.description)
                current_step.action = action
                current_step.parameters.update(params)
                i += 1
            else:
                # Non-step, non-continuation prose between steps is ignored on
                # purpose so pasted intros/outros don't pollute step descriptions.
                i += 1

        if current_step:
            steps.append(current_step)

        # Resolve dependencies
        self._resolve_dependencies(steps)

        return steps

    def assess_parse_confidence(self, steps: List[WorkflowStep]) -> Dict[str, Any]:
        """Score parser confidence and flag when AI assist should be considered."""
        if not steps:
            return {
                "score": 0.0,
                "custom_steps": 0,
                "missing_param_steps": 0,
                "reasons": ["No steps were parsed."],
                "needs_ai_assist": True,
            }

        custom_steps = sum(1 for step in steps if step.action == "custom")
        missing_param_steps = 0
        missing_details: List[str] = []

        for step in steps:
            required = self.REQUIRED_ACTION_PARAMS.get(step.action, [])
            missing = [key for key in required if not str(step.parameters.get(key, "")).strip()]
            if missing:
                missing_param_steps += 1
                missing_details.append(
                    f"{step.step_id} ({step.action}) missing: {', '.join(missing)}"
                )

        total = len(steps)
        custom_ratio = custom_steps / total
        missing_ratio = missing_param_steps / total
        score = max(0.0, 1.0 - (0.6 * custom_ratio) - (0.4 * missing_ratio))

        reasons: List[str] = []
        if custom_steps:
            reasons.append(f"{custom_steps}/{total} steps were classified as custom.")
        if missing_details:
            reasons.extend(missing_details[:5])

        return {
            "score": round(score, 3),
            "custom_steps": custom_steps,
            "missing_param_steps": missing_param_steps,
            "reasons": reasons,
            "needs_ai_assist": score < 0.55,
        }

    def _is_step_start(self, line: str) -> bool:
        """Check if a line starts a new step"""
        patterns = [
            r'^\d+\.',
            r'^Step\s+\d+:',
            r'^-\s+',
            r'^\*\s+',
        ]
        return any(re.match(pattern, line) for pattern in patterns)

    @staticmethod
    def _is_continuation_line(raw_line: str) -> bool:
        """A line is a continuation of the previous step only if it is indented
        or starts with a visible continuation marker. This prevents pasted
        paragraphs between numbered steps from being merged into the previous
        step description.
        """
        if raw_line.startswith(("  ", "\t")):
            return True
        stripped = raw_line.lstrip()
        return stripped.startswith((">", "→", "↳"))

    def _extract_description(self, line: str) -> str:
        """Extract the description from a step line"""
        # Remove step numbering
        line = re.sub(r'^\d+\.\s*', '', line)
        line = re.sub(r'^Step\s+\d+:\s*', '', line)
        line = re.sub(r'^[-*]\s*', '', line)
        return line.strip()

    def _extract_action_and_params(self, description: str) -> tuple[str, Dict[str, Any]]:
        """Map a step description to an action + parameters.

        Uses word-level matching to avoid false positives (e.g. "readme.txt"
        containing the substring "read" should not trigger read_file).
        """
        d = description.lower()
        # Word set for exact-word checks — avoids substring false positives.
        words = set(re.findall(r'\b\w+\b', d))

        # ── Filesystem: directory ops (before file read/write) ───────────────
        if ('create' in words or 'make' in words or 'mkdir' in words) and \
                ('directory' in words or 'folder' in words or 'dir' in words):
            return 'create_directory', self._extract_directory_params(description)

        if 'list' in words and ('file' in words or 'files' in words or
                                'directory' in words or 'folder' in words):
            return 'list_files', self._extract_directory_params(description)

        # ── Network ──────────────────────────────────────────────────────────
        if 'download' in words:
            return 'download', self._extract_url_params(description)

        if 'scrape' in words or ('fetch' in words and 'http' in d):
            return 'scrape_webpage', self._extract_url_params(description)

        if ('post' in words or 'put' in words or 'patch' in words) and \
                ('api' in words or 'webhook' in words or 'http' in words or 'request' in words):
            return 'http_request', self._extract_url_params(description)

        # ── Finance ──────────────────────────────────────────────────────────
        if ('price' in words or 'stock' in words or 'ticker' in words) and \
                ('fetch' in words or 'get' in words or 'find' in words or 'check' in words):
            ticker = self._extract_stock_ticker(description)
            return 'fetch_stock_price', {
                'ticker': ticker,
                'description': description,
            }

        # ── AI text generation ────────────────────────────────────────────────
        _creative = {'poem', 'story', 'message', 'summary', 'haiku', 'limerick',
                     'reminder', 'draft', 'compose', 'generate', 'write'}
        if 'generate_text' in d or \
                ('write' in words and _creative & words and
                 'file' not in words and 'csv' not in words):
            return 'generate_text', {'prompt': description, 'description': description}

        # ── Archive: compress/extract (before read/write — "readme.zip" edge) ─
        if 'compress' in words or ('zip' in words and ('file' in words or 'files' in words)):
            return 'compress_files', self._extract_compression_params(description)

        if 'extract' in words and ('archive' in words or 'zip' in words or 'unzip' in words):
            return 'extract_archive', self._extract_compression_params(description)

        # ── File write (before read — "readme" still contains "read") ─────────
        if 'write' in words:
            if 'csv' in words:
                return 'write_csv', self._extract_file_params(description)
            if 'json' in words:
                fp = self._extract_file_params(description)
                return 'write_json', {**fp, 'data': {}}
            return 'write_file', self._extract_file_params(description)

        # ── File read ─────────────────────────────────────────────────────────
        if ('read' in words or 'extract' in words) and ('pdf' in words or '.pdf' in d):
            return 'read_pdf', self._extract_file_params(description)

        if 'read' in words and (
            'file' in words or 'csv' in words or 'json' in words or '.json' in d
        ):
            if 'csv' in words:
                return 'read_csv', self._extract_file_params(description)
            if 'json' in words or '.json' in d:
                return 'read_json', self._extract_file_params(description)
            return 'read_file', self._extract_file_params(description)

        if 'append' in words and ('file' in words or 'log' in words):
            return 'append_file', self._extract_append_params(description)

        if ('hash' in words or 'checksum' in words or 'sha256' in d) and \
                ('file' in words or '.json' in d or '.txt' in d or '.csv' in d):
            return 'hash_file', self._extract_file_params(description)

        if ('current' in words or 'now' in words) and 'time' in words:
            return 'get_current_time', self._extract_time_params(description)

        # ── File ops ─────────────────────────────────────────────────────────
        if 'copy' in words and 'file' in words:
            return 'copy_file', self._extract_file_operation_params(description)
        if 'move' in words and 'file' in words:
            return 'move_file', self._extract_file_operation_params(description)
        if 'delete' in words and 'file' in words:
            return 'delete_file', self._extract_file_params(description)

        # ── Email / notification ──────────────────────────────────────────────
        has_address = bool(re.search(r'[\w.-]+@[\w.-]+\.\w+', description))
        if has_address and (
            'email' in words
            or 'mail' in words
            or 'send' in words
            or 'forward' in words
        ):
            return 'send_email', self._extract_email_params(description)

        if 'notify' in words or 'notification' in words or \
                ('send' in words and 'notification' in words):
            return 'send_notification', self._extract_notification_params(description)

        # ── Database ─────────────────────────────────────────────────────────
        if 'database' in words or 'sql' in words or 'sqlite' in words:
            if 'insert' in words or 'add' in words:
                return 'sqlite_insert', self._extract_database_params(description)
            return 'sqlite_query', self._extract_database_params(description)

        # ── System ───────────────────────────────────────────────────────────
        if 'run' in words and ('command' in words or 'script' in words or 'shell' in words):
            return 'run_command', self._extract_command_params(description)

        if 'wait' in words or 'sleep' in words or 'pause' in words:
            return 'wait', self._extract_wait_params(description)

        return 'custom', {'description': description}

    # Uppercase abbreviations that users commonly write in workflow descriptions
    # which are NOT stock tickers. Prevents the bare-uppercase fallback from
    # turning "Fetch the API stock price" into ticker="API".
    _NON_TICKER_UPPERCASE = frozenset({
        'AI', 'API', 'APP', 'APPS', 'ASAP', 'AWS', 'BBC', 'CEO', 'CFO', 'CIO',
        'CNBC', 'CNN', 'CSS', 'CSV', 'EOD', 'ETF', 'EU', 'FAQ', 'FBI', 'FTP',
        'FYI', 'GCP', 'GIT', 'GMT', 'GPU', 'HTML', 'HTTP', 'HTTPS', 'ID',
        'IDE', 'IPO', 'JSON', 'LLM', 'ML', 'MLB', 'NBA', 'NFL', 'NHL', 'NEWS',
        'NYSE', 'OK', 'OS', 'PDF', 'PHP', 'RAM', 'RSS', 'SDK', 'SQL', 'SSH',
        'SSL', 'TBD', 'TLS', 'TODO', 'TSV', 'UI', 'UK', 'UN', 'URL', 'US',
        'USA', 'USD', 'UTC', 'UX', 'VPN', 'XML', 'YAML', 'ZIP',
    })

    def _extract_stock_ticker(self, description: str) -> str:
        """Resolve a ticker symbol from explicit markers only.

        Matches (in order):
          - `^GSPC`, `^DJI`, etc. (Yahoo index syntax)
          - `BTC-USD`, `ETH-USD`, etc. (crypto/forex pairs)
          - `$AAPL` / `$BRK.B` (cashtag)
          - "price of <TICKER>" / "cost of <TICKER>" with deny-listed words filtered
          - "ticker <X>" / "ticker is <X>" / "symbol <X>"

        Bare uppercase tokens are NOT treated as tickers anymore — too many
        false positives (USA, ASAP, ETF, etc.). When no explicit marker is
        present we return ''; the user can edit the step or fill the parameter
        manually before code generation.
        """
        d = description.strip()
        m = re.search(r'\^[A-Za-z]{1,10}\b', d)
        if m:
            return m.group(0).upper()
        m = re.search(r'\b[A-Za-z]{1,6}-USD\b', d, re.IGNORECASE)
        if m:
            sym = m.group(0)
            return sym[:-4].upper() + '-USD'
        m = re.search(r'\$([A-Za-z]{1,5}(?:\.[A-Za-z])?)\b', d)
        if m:
            return m.group(1).upper()
        m = re.search(
            r'\b(?:price|cost|quote)\s+of\s+(?:the\s+)?([A-Za-z]{1,5})\b',
            d,
            re.IGNORECASE,
        )
        if m:
            candidate = m.group(1).upper()
            if candidate not in self._NON_TICKER_UPPERCASE:
                return candidate
        m = re.search(
            r'\b(?:ticker|symbol)(?:\s+is)?\s+([A-Za-z]{1,5})\b',
            d,
            re.IGNORECASE,
        )
        if m:
            candidate = m.group(1).upper()
            if candidate not in self._NON_TICKER_UPPERCASE:
                return candidate
        return ''

    def _extract_directory_params(self, description: str) -> Dict[str, Any]:
        """Extract directory path from description."""
        quoted = re.search(r'["\']([^"\']+)["\']', description)
        if quoted:
            return {'directory': quoted.group(1), 'description': description}
        # fallback: word after "called", "named", or "directory"
        word = re.search(
            r'(?:called|named|directory|folder)\s+["\']?(\S+)["\']?',
            description, re.IGNORECASE,
        )
        return {'directory': word.group(1) if word else '', 'description': description}

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

    def _extract_append_params(self, description: str) -> Dict[str, Any]:
        """Extract file path and content for append_file."""
        quoted = re.findall(r'["\']([^"\']*)["\']', description)
        file_path = ""
        content = ""
        for q in quoted:
            if re.search(r'\.[a-zA-Z0-9]+\s*$', q) or "/" in q or "\\" in q:
                if not file_path:
                    file_path = q
            elif q.strip():
                content = q
        if not file_path and quoted:
            file_path = quoted[-1]
        if not content and len(quoted) >= 2:
            for q in quoted:
                if q != file_path:
                    content = q
                    break
        return {'file_path': file_path, 'content': content, 'description': description}

    def _extract_time_params(self, description: str) -> Dict[str, Any]:
        """Optional IANA timezone for get_current_time."""
        d = description.strip()
        m = re.search(
            r'\b([A-Za-z][A-Za-z_]*/[A-Za-z][A-Za-z_]*(?:/[A-Za-z][A-Za-z_]*)?)\b',
            d,
        )
        if m:
            return {'timezone': m.group(1), 'description': description}
        low = d.lower()
        if 'seattle' in low or 'los angeles' in low or 'pacific' in low:
            return {'timezone': 'America/Los_Angeles', 'description': description}
        if 'new york' in low or 'eastern' in low or 'boston' in low:
            return {'timezone': 'America/New_York', 'description': description}
        if 'london' in low or 'uk' in low or 'gmt' in low or 'british' in low:
            return {'timezone': 'Europe/London', 'description': description}
        if 'tokyo' in low or 'japan' in low:
            return {'timezone': 'Asia/Tokyo', 'description': description}
        return {'timezone': 'UTC', 'description': description}

    def _extract_email_params(self, description: str) -> Dict[str, Any]:
        """Extract email parameters from description"""
        email_match = re.search(r'[\w\.-]+@[\w\.-]+\.\w+', description)
        return {
            'recipient': email_match.group() if email_match else '',
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

    _EXPLICIT_DEP_REGEX = re.compile(
        r"\b(?:step[\s_]*(\d+)|previous\s+step|the\s+result|the\s+output|that\s+(?:file|message|email|value))\b",
        re.IGNORECASE,
    )

    def _resolve_dependencies(self, steps: List[WorkflowStep]):
        """Link steps only when the user wrote explicit data-flow markers.

        We deliberately do NOT chain every step to its predecessor. The agent
        prompt already preserves ordering, and unconditional chaining
        over-constrains the LLM and produced spurious deps for parallel work.

        We add a dependency when the description references:
          - ``step <N>`` / ``step_<N>``
          - ``previous step`` / ``the result`` / ``the output`` /
            ``that file|message|email|value``
        In each case we link to the most recent prior step (or the explicit N).
        """
        for i, step in enumerate(steps):
            if i == 0:
                continue
            text = step.description.lower()
            for match in self._EXPLICIT_DEP_REGEX.finditer(text):
                explicit_n = match.group(1)
                if explicit_n is not None:
                    try:
                        n = int(explicit_n)
                    except ValueError:
                        continue
                    target_id = f"step_{n}"
                    if any(s.step_id == target_id for s in steps[:i]) and target_id not in step.dependencies:
                        step.dependencies.append(target_id)
                else:
                    target_id = steps[i - 1].step_id
                    if target_id not in step.dependencies:
                        step.dependencies.append(target_id)
