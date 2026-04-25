"""Filesystem-shaped tools: file/dir/csv/json/pdf primitives."""

from __future__ import annotations

import csv
import hashlib
import json
import os
import shutil
from typing import Any, Dict, List, Optional

from ._base import Tool


class FilesystemToolsMixin:
    """File and directory operations (no network, no LLMs, no email)."""

    # ----- registration ---------------------------------------------------

    def _register_filesystem_tools(self) -> None:
        self.register_tool(Tool(
            name="read_file",
            description="Read content from a file",
            function=self._read_file,
            parameters={
                "file_path": "Path to the file to read",
                "encoding": "File encoding (default: utf-8)",
            },
        ))
        self.register_tool(Tool(
            name="write_file",
            description="Write content to a file",
            function=self._write_file,
            parameters={
                "file_path": "Path to the file to write",
                "content": "Content to write",
                "encoding": "File encoding (default: utf-8)",
            },
        ))
        self.register_tool(Tool(
            name="list_files",
            description="List files in a directory",
            function=self._list_files,
            parameters={
                "directory": "Directory path to list",
                "pattern": "Optional file pattern filter",
            },
        ))
        self.register_tool(Tool(
            name="create_directory",
            description="Create a directory",
            function=self._create_directory,
            parameters={"directory": "Directory path to create"},
        ))
        self.register_tool(Tool(
            name="copy_file",
            description="Copy file from source to destination",
            function=self._copy_file,
            parameters={
                "source": "Source file path",
                "destination": "Destination file path",
            },
        ))
        self.register_tool(Tool(
            name="move_file",
            description="Move file from source to destination",
            function=self._move_file,
            parameters={
                "source": "Source file path",
                "destination": "Destination file path",
            },
        ))
        self.register_tool(Tool(
            name="delete_file",
            description="Delete a file",
            function=self._delete_file,
            parameters={"file_path": "Path to file to delete"},
        ))
        self.register_tool(Tool(
            name="read_csv",
            description="Read and parse CSV file",
            function=self._read_csv,
            parameters={
                "file_path": "Path to CSV file",
                "delimiter": "CSV delimiter (default: comma)",
                "encoding": "File encoding (default: utf-8)",
            },
        ))
        self.register_tool(Tool(
            name="write_csv",
            description="Write data to CSV file",
            function=self._write_csv,
            parameters={
                "file_path": "Path to CSV file",
                "data": "Data to write (list of dicts)",
                "fieldnames": "Column names (optional)",
            },
        ))
        self.register_tool(Tool(
            name="read_json",
            description=(
                "Read a UTF-8 JSON file and parse it into Python objects "
                "(returned as JSON text and structured data)."
            ),
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
            name="read_pdf",
            description=(
                "Extract plain text from a PDF file using pypdf. "
                "Returns the concatenated text of all pages (or a selected page range)."
            ),
            function=self._read_pdf,
            parameters={
                "file_path": "Path to the .pdf file",
                "pages": (
                    "Optional list of 1-indexed page numbers, or a string "
                    "like '1-3' / '2,4,6'. Reads all pages when omitted."
                ),
            },
        ))

    # ----- implementations ------------------------------------------------

    def _read_file(self, file_path: str, encoding: str = "utf-8") -> Dict[str, Any]:
        try:
            safe_path = self._sandbox_path(file_path)
            with open(safe_path, encoding=encoding) as f:
                content = f.read()
            return {"success": True, "content": content, "size": len(content)}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def _write_file(
        self, file_path: str, content: str, encoding: str = "utf-8"
    ) -> Dict[str, Any]:
        try:
            safe_path = self._sandbox_path(file_path)
            parent = os.path.dirname(safe_path)
            if parent:
                os.makedirs(parent, exist_ok=True)
            with open(safe_path, "w", encoding=encoding) as f:
                f.write(content)
            return {"success": True, "file": safe_path, "size": len(content)}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def _list_files(
        self, directory: str, pattern: Optional[str] = None
    ) -> Dict[str, Any]:
        try:
            safe_dir = self._sandbox_path(directory)
            if not os.path.exists(safe_dir):
                return {"success": False, "error": "Directory does not exist"}

            files: List[str] = []
            for item in os.listdir(safe_dir):
                item_path = os.path.join(safe_dir, item)
                if os.path.isfile(item_path) and (pattern is None or pattern in item):
                    files.append(item)
            return {"success": True, "files": files}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def _create_directory(self, directory: str) -> Dict[str, Any]:
        try:
            safe_dir = self._sandbox_path(directory)
            os.makedirs(safe_dir, exist_ok=True)
            return {"success": True, "directory": safe_dir}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def _copy_file(self, source: str, destination: str) -> Dict[str, Any]:
        try:
            safe_source = self._sandbox_path(source)
            safe_destination = self._sandbox_path(destination)
            parent = os.path.dirname(safe_destination)
            if parent:
                os.makedirs(parent, exist_ok=True)
            shutil.copy2(safe_source, safe_destination)
            return {
                "success": True,
                "source": safe_source,
                "destination": safe_destination,
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    def _move_file(self, source: str, destination: str) -> Dict[str, Any]:
        try:
            safe_source = self._sandbox_path(source)
            safe_destination = self._sandbox_path(destination)
            parent = os.path.dirname(safe_destination)
            if parent:
                os.makedirs(parent, exist_ok=True)
            shutil.move(safe_source, safe_destination)
            return {
                "success": True,
                "source": safe_source,
                "destination": safe_destination,
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    def _delete_file(self, file_path: str) -> Dict[str, Any]:
        try:
            safe_path = self._sandbox_path(file_path)
            if os.path.exists(safe_path):
                os.remove(safe_path)
                return {"success": True, "file": safe_path}
            return {"success": False, "error": "File not found"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def _read_csv(
        self, file_path: str, delimiter: str = ",", encoding: str = "utf-8"
    ) -> Dict[str, Any]:
        try:
            safe_path = self._sandbox_path(file_path)
            with open(safe_path, encoding=encoding) as f:
                reader = csv.DictReader(f, delimiter=delimiter)
                data = list(reader)
            return {"success": True, "data": data, "rows": len(data)}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def _write_csv(
        self,
        file_path: str,
        data: List[Dict],
        fieldnames: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        try:
            if not data:
                return {"success": False, "error": "No data to write"}
            if not fieldnames:
                fieldnames = list(data[0].keys())
            safe_path = self._sandbox_path(file_path)
            parent = os.path.dirname(safe_path)
            if parent:
                os.makedirs(parent, exist_ok=True)
            with open(safe_path, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(data)
            return {"success": True, "file": safe_path, "rows": len(data)}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def _read_json(self, file_path: str, encoding: str = "utf-8") -> Dict[str, Any]:
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
        try:
            if isinstance(data, str):
                try:
                    data = json.loads(data)
                except json.JSONDecodeError:
                    return {
                        "success": False,
                        "error": "data must be dict/list or a JSON string",
                    }
            if not isinstance(data, (dict, list)):
                return {
                    "success": False,
                    "error": "data must be a dict or list (or JSON string)",
                }
            safe_path = self._sandbox_path(file_path)
            parent = os.path.dirname(safe_path)
            if parent:
                os.makedirs(parent, exist_ok=True)
            if indent is None or (
                isinstance(indent, str) and indent.lower() in ("none", "null")
            ):
                ind: Optional[int] = None
            else:
                ind = int(indent)
            text = json.dumps(data, indent=ind, ensure_ascii=False)
            with open(safe_path, "w", encoding=encoding) as f:
                f.write(text)
            return {"success": True, "file": safe_path, "size": len(text)}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def _append_file(
        self, file_path: str, content: str, encoding: str = "utf-8"
    ) -> Dict[str, Any]:
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

    def _hash_file(
        self, file_path: str, algorithm: str = "sha256"
    ) -> Dict[str, Any]:
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

    @staticmethod
    def _parse_page_spec(pages: Any, total_pages: int) -> List[int]:
        """Parse ``pages`` into 0-indexed page numbers, clamped to range."""
        if pages is None:
            return list(range(total_pages))
        if isinstance(pages, int):
            spec_items: List[Any] = [pages]
        elif isinstance(pages, (list, tuple)):
            spec_items = list(pages)
        elif isinstance(pages, str):
            spec_items = [p.strip() for p in pages.split(",") if p.strip()]
        else:
            raise ValueError(f"Unsupported pages spec: {pages!r}")

        collected: List[int] = []
        for item in spec_items:
            if isinstance(item, int):
                collected.append(item - 1)
                continue
            text = str(item).strip()
            if "-" in text:
                start_str, end_str = text.split("-", 1)
                start = int(start_str) - 1
                end = int(end_str) - 1
                if start > end:
                    start, end = end, start
                collected.extend(range(start, end + 1))
            else:
                collected.append(int(text) - 1)

        seen: set[int] = set()
        ordered: List[int] = []
        for idx in collected:
            if 0 <= idx < total_pages and idx not in seen:
                seen.add(idx)
                ordered.append(idx)
        return ordered

    def _read_pdf(self, file_path: str, pages: Any = None) -> Dict[str, Any]:
        try:
            from pypdf import PdfReader
        except ImportError:
            return {
                "success": False,
                "error": "pypdf is not installed. Run: pip install pypdf",
            }
        try:
            safe_path = self._sandbox_path(file_path)
            reader = PdfReader(safe_path)
            total_pages = len(reader.pages)
            page_indices = self._parse_page_spec(pages, total_pages)
            if not page_indices:
                return {
                    "success": False,
                    "error": (
                        f"No valid pages selected (PDF has {total_pages} pages, "
                        f"requested spec: {pages!r})"
                    ),
                }
            parts: List[str] = []
            for idx in page_indices:
                try:
                    parts.append(reader.pages[idx].extract_text() or "")
                except Exception as page_err:  # noqa: BLE001 - per-page best effort
                    parts.append(f"[page {idx + 1} extraction failed: {page_err}]")
            text = "\n".join(parts).strip()
            return {
                "success": True,
                "text": text,
                "pages_read": len(page_indices),
                "total_pages": total_pages,
                "result": text,
            }
        except Exception as e:
            return {"success": False, "error": str(e)}
