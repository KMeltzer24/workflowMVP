"""Unit tests for WorkflowAgent code extraction helpers."""

from __future__ import annotations

from workflowmvp.agent import WorkflowAgent


def test_extract_python_script_prefers_fenced_block() -> None:
    text = """
### Here is your script
```python
import os
print("hello")
```
Some explanation below.
""".strip()
    code = WorkflowAgent._extract_python_script(text)
    assert code.startswith("import os")
    assert 'print("hello")' in code


def test_extract_python_script_handles_unfenced_markdown_header() -> None:
    text = """
## Python Script
import json
from workflowmvp.tools import ToolRegistry
""".strip()
    code = WorkflowAgent._extract_python_script(text)
    assert code.startswith("import json")
    assert "ToolRegistry" in code
