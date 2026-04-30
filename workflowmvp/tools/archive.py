"""Archive-shaped tools: zip/unzip primitives."""

from __future__ import annotations

import os
import zipfile
from typing import Any, Dict, List, Optional

from ._base import Tool


class ArchiveToolsMixin:
    def _register_archive_tools(self) -> None:
        self.register_tool(Tool(
            name="compress_files",
            description="Compress files into ZIP archive",
            function=self._compress_files,
            parameters={
                "files": "List of file paths to compress",
                "archive_path": "Path for the ZIP archive",
                "include_dirs": "Include directory structure (default: True)",
            },
        ))
        self.register_tool(Tool(
            name="extract_archive",
            description="Extract files from ZIP archive",
            function=self._extract_archive,
            parameters={
                "archive_path": "Path to ZIP archive",
                "extract_to": "Directory to extract to",
                "password": "Archive password (optional)",
            },
        ))

    def _compress_files(
        self,
        files: List[str],
        archive_path: str,
        include_dirs: bool = True,
    ) -> Dict[str, Any]:
        try:
            safe_archive = self._sandbox_path(archive_path)
            parent = os.path.dirname(safe_archive)
            if parent:
                os.makedirs(parent, exist_ok=True)

            compressed = 0
            skipped: List[str] = []
            with zipfile.ZipFile(safe_archive, "w", zipfile.ZIP_DEFLATED) as zipf:
                for file_path in files:
                    safe_file = self._sandbox_path(file_path)
                    if not os.path.exists(safe_file):
                        skipped.append(file_path)
                        continue
                    if include_dirs:
                        arcname = (
                            os.path.relpath(safe_file, self.sandbox_root)
                            if self.sandbox_root
                            else safe_file
                        )
                        zipf.write(safe_file, arcname=arcname)
                    else:
                        zipf.write(safe_file, os.path.basename(safe_file))
                    compressed += 1
            return {
                "success": True,
                "result": safe_archive,
                "archive": safe_archive,
                "files": compressed,
                "meta": {
                    "archive": safe_archive,
                    "files": compressed,
                    "include_dirs": include_dirs,
                    "skipped": skipped,
                },
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    def _extract_archive(
        self,
        archive_path: str,
        extract_to: str,
        password: Optional[str] = None,
    ) -> Dict[str, Any]:
        try:
            safe_archive = self._sandbox_path(archive_path)
            safe_extract_to = self._sandbox_path(extract_to)
            os.makedirs(safe_extract_to, exist_ok=True)

            with zipfile.ZipFile(safe_archive, "r") as zipf:
                if password:
                    zipf.setpassword(password.encode())
                for member in zipf.namelist():
                    member_target = os.path.abspath(
                        os.path.join(safe_extract_to, member)
                    )
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
                "result": safe_extract_to,
                "extracted_to": safe_extract_to,
                "archive": safe_archive,
                "meta": {
                    "archive": safe_archive,
                    "extracted_to": safe_extract_to,
                },
            }
        except Exception as e:
            return {"success": False, "error": str(e)}
