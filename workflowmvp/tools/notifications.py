"""Notification-shaped tools: email + desktop alerts."""

from __future__ import annotations

import os
import shutil
import smtplib
import subprocess
import sys
import time
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Any, Dict, List, Optional

from ._base import Tool


class NotificationToolsMixin:
    def _register_notification_tools(self) -> None:
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
            requires_credentials=("EMAIL_USER", "EMAIL_PASSWORD", "EMAIL_FROM"),
        ))
        self.register_tool(Tool(
            name="send_notification",
            description="Send desktop notification",
            function=self._send_notification,
            parameters={
                "title": "Notification title",
                "message": "Notification message",
                "urgency": "Urgency level (low, normal, critical)",
            },
        ))

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

        Never prompts interactively: the script runs as a subprocess under the
        Flask server with no stdin, so an ``input()`` prompt would hang the run
        indefinitely. Missing creds are reported as a structured error so the
        UI can surface them and re-run with creds attached.

        ``attachments`` may be a list of relative paths or a single path string;
        files are read after :meth:`_sandbox_path` resolution.
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
                "result": f"Email sent successfully to {recipient}",
                "message": f"Email sent successfully to {recipient}",
                "meta": {
                    "recipient": recipient,
                    "subject": subject,
                    "attachments": attach_paths,
                    "smtp_server": smtp_server,
                    "smtp_port": smtp_port,
                    "email_from": email_from,
                },
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    @staticmethod
    def _applescript_literal(value: str) -> str:
        """Quote a string for use inside AppleScript double-quoted text (escape \\ and ")."""
        return str(value).replace("\\", "\\\\").replace('"', '\\"')

    def _send_notification(
        self, title: str, message: str, urgency: str = "normal"
    ) -> Dict[str, Any]:
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
                            return {
                                "success": True,
                                "result": message_s,
                                "title": title_s,
                                "message": message_s,
                                "meta": {
                                    "title": title_s,
                                    "message": message_s,
                                    "urgency": urgency,
                                    "platform": "darwin",
                                    "notifier": "terminal-notifier",
                                },
                            }
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
                        "result": message_s,
                        "title": title_s,
                        "message": message_s,
                        "note": "notify-send not available; notification skipped",
                        "meta": {
                            "title": title_s,
                            "message": message_s,
                            "urgency": urgency,
                            "platform": sys.platform,
                            "notifier": None,
                            "skipped": True,
                        },
                    }

            return {
                "success": True,
                "result": message_s,
                "title": title_s,
                "message": message_s,
                "meta": {
                    "title": title_s,
                    "message": message_s,
                    "urgency": urgency,
                    "platform": sys.platform,
                    "notifier": (
                        "powershell"
                        if os.name == "nt"
                        else "osascript"
                        if sys.platform == "darwin"
                        else "notify-send"
                    ),
                },
            }
        except Exception as e:
            return {"success": False, "error": str(e)}
