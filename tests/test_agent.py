"""Unit tests for WorkflowAgent code extraction, system prompt, and code generation."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from workflowmvp.agent import WorkflowAgent
from workflowmvp.parser import WorkflowStep
from workflowmvp.tools import ToolRegistry

# ---------------------------------------------------------------------------
# _extract_python_script helpers
# ---------------------------------------------------------------------------


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


def test_extract_python_script_picks_longest_fenced_block() -> None:
    text = """
First try (short):
```python
x = 1
```

Better version:
```python
import json
from workflowmvp.tools import ToolRegistry
tools = ToolRegistry()
print("ok")
```
""".strip()
    code = WorkflowAgent._extract_python_script(text)
    assert "ToolRegistry" in code
    assert code.count("\n") >= 3


# ---------------------------------------------------------------------------
# System prompt dynamic tool list
# ---------------------------------------------------------------------------


@pytest.fixture()
def agent(monkeypatch: pytest.MonkeyPatch) -> WorkflowAgent:
    monkeypatch.setenv("GEMINI_API_KEY", "fake-key-for-test")
    return WorkflowAgent(api_key="fake-key-for-test", provider="gemini")


def test_system_prompt_lists_every_registered_tool(agent: WorkflowAgent) -> None:
    prompt = agent._create_system_prompt()
    registry_names = {tool.name for tool in ToolRegistry().list_tools()}
    assert registry_names, "registry unexpectedly empty"
    for name in registry_names:
        assert name in prompt, f"system prompt missing tool '{name}'"


def test_system_prompt_omits_removed_tools(agent: WorkflowAgent) -> None:
    prompt = agent._create_system_prompt()
    for removed in ("process_data", "analyze_data", "process_json"):
        assert removed not in prompt, f"removed tool '{removed}' leaked into prompt"


def test_system_prompt_has_structural_sections(agent: WorkflowAgent) -> None:
    prompt = agent._create_system_prompt()
    for header in ("SCRIPT STRUCTURE", "TOOL USAGE", "OUTPUT"):
        assert header in prompt, f"system prompt missing section '{header}'"
    assert "`http_request` may already return a parsed dict/list" in prompt
    assert "CUSTOM STEP HANDLING" in prompt
    assert "Do not treat `custom` as \"log and skip\"" in prompt
    assert "April 17 - 30" in prompt
    assert "time not listed" in prompt


def test_system_prompt_groups_tools_by_category(agent: WorkflowAgent) -> None:
    prompt = agent._create_system_prompt()
    for label in ("Files & I/O", "Network & Web", "Communications"):
        assert f"### {label}" in prompt


def test_system_prompt_inlines_only_relevant_guidance(agent: WorkflowAgent) -> None:
    """Steps that don't use scraping/discovery should not get those snippets."""
    steps = [
        WorkflowStep(
            step_id="step_1",
            description="Write hi to file out.txt",
            action="write_file",
            parameters={"file_path": "out.txt"},
            dependencies=[],
        )
    ]
    prompt = agent._create_system_prompt(steps)
    # generate_text guidance is always-on for codegen flexibility.
    assert "AI TEXT —" in prompt
    # No scraping in this workflow → no SCRAPING block.
    assert "SCRAPING — scrape_webpage" not in prompt
    # No fetch_stock_price step → no STOCK guidance.
    assert "STOCK / FINANCIAL DATA" not in prompt


def test_system_prompt_includes_specific_guidance_when_action_present(
    agent: WorkflowAgent,
) -> None:
    steps = [
        WorkflowStep(
            step_id="step_1",
            description="Send email to me@example.com",
            action="send_email",
            parameters={"recipient": "me@example.com"},
            dependencies=[],
        )
    ]
    prompt = agent._create_system_prompt(steps)
    assert "EMAIL — send_email" in prompt


# ---------------------------------------------------------------------------
# generate_workflow_code with a fully mocked LLM response
# ---------------------------------------------------------------------------


_FAKE_GENERATED_SCRIPT = '''
```python
import logging
from workflowmvp.tools import ToolRegistry

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)


def main() -> None:
    tools = ToolRegistry()
    write = tools.get_tool("write_file").function
    result = write(file_path="hello.txt", content="hi")
    logger.info("WRITE_OK=%s", result.get("success"))


if __name__ == "__main__":
    main()
```
'''.strip()


def test_generate_workflow_code_writes_valid_python(
    agent: WorkflowAgent, tmp_path: Path
) -> None:
    steps = [
        WorkflowStep(
            step_id="step_1",
            description='Write "hi" to file "hello.txt"',
            action="write_file",
            parameters={"file_path": "hello.txt", "content": "hi"},
            dependencies=[],
        )
    ]
    output = tmp_path / "generated.py"

    with patch.object(WorkflowAgent, "_generate_text", return_value=_FAKE_GENERATED_SCRIPT):
        code = agent.generate_workflow_code(steps, output_file=str(output))

    assert output.exists()
    assert "ToolRegistry" in code
    compile(code, str(output), "exec")  # raises SyntaxError if invalid


def test_generate_workflow_code_raises_on_empty_model_output(
    agent: WorkflowAgent, tmp_path: Path
) -> None:
    steps = [
        WorkflowStep(
            step_id="step_1",
            description="do a thing",
            action="custom",
            parameters={},
            dependencies=[],
        )
    ]
    output = tmp_path / "generated.py"

    with patch.object(WorkflowAgent, "_generate_text", return_value=""):
        with pytest.raises(ValueError, match="empty"):
            agent.generate_workflow_code(steps, output_file=str(output))


def test_validate_generated_python_rejects_naive_json_loads_after_scrape_and_generate_text() -> None:
    bad = """
import json
from workflowmvp.tools import ToolRegistry
tools = ToolRegistry()
tools.get_tool("scrape_webpage").function(url="https://example.org/")
g = tools.get_tool("generate_text")
r = g.function(prompt="x", max_tokens=100)
data = json.loads(r.get("result") or "{}")
""".strip()
    with pytest.raises(ValueError, match="extract_first_json_value"):
        WorkflowAgent._validate_generated_python(bad)


def test_validate_generated_python_allows_json_llm_after_scrape_and_generate_text() -> None:
    ok = """
from workflowmvp.tools import ToolRegistry
from workflowmvp.json_llm import extract_first_json_value
tools = ToolRegistry()
tools.get_tool("scrape_webpage").function(url="https://example.org/")
g = tools.get_tool("generate_text")
r = g.function(prompt="x", max_tokens=100)
data = extract_first_json_value(r.get("result") or "")
""".strip()
    WorkflowAgent._validate_generated_python(ok)


def test_validate_generated_python_rejects_unsafe_http_request_json_loads() -> None:
    bad = """
import json
from workflowmvp.tools import ToolRegistry
tools = ToolRegistry()
http = tools.get_tool("http_request")
response = http.function(url="https://example.com", method="GET")
data = json.loads(response.get("result") or "{}")
""".strip()
    with pytest.raises(ValueError, match="http_request result handling"):
        WorkflowAgent._validate_generated_python(bad)


def test_validate_generated_python_allows_guarded_http_request_result() -> None:
    ok = """
import json
from workflowmvp.tools import ToolRegistry
tools = ToolRegistry()
http = tools.get_tool("http_request")
response = http.function(url="https://example.com", method="GET")
raw = response.get("result")
data = raw if isinstance(raw, (dict, list)) else json.loads(raw or "{}")
""".strip()
    # Should not raise.
    WorkflowAgent._validate_generated_python(ok)


def test_validate_generated_python_rejects_custom_step_copout_script() -> None:
    bad = """
import logging
from workflowmvp.tools import ToolRegistry
tools = ToolRegistry()
logger = logging.getLogger(__name__)
logger.info("custom step, no concrete output generated by script")
email = tools.get_tool("send_email")
email.function(recipient="x@example.com", subject="update", body="no specific research findings or material costs")
""".strip()
    with pytest.raises(ValueError, match="Placeholder custom-step output"):
        WorkflowAgent._validate_generated_python(bad)


def test_validate_generated_python_rejects_discover_urls_result_misuse() -> None:
    bad = """
from workflowmvp.tools import ToolRegistry
tools = ToolRegistry()
d = tools.get_tool("discover_urls")
result = d.function(start_url="https://example.org", keywords="dresser", max_results=3)
urls = result.get("result", [])
for url in urls:
    print(url)
""".strip()
    with pytest.raises(ValueError, match="discover_urls result handling"):
        WorkflowAgent._validate_generated_python(bad)


def test_validate_generated_python_rejects_google_as_discover_start_url() -> None:
    bad = """
from workflowmvp.tools import ToolRegistry
tools = ToolRegistry()
tools.get_tool("discover_urls").function(start_url="https://www.google.com", keywords="x")
""".strip()
    with pytest.raises(ValueError, match="google.com"):
        WorkflowAgent._validate_generated_python(bad)


def test_validate_generated_python_rejects_phony_hardcoded_materials() -> None:
    bad = """
from workflowmvp.tools import ToolRegistry
tools = ToolRegistry()
tools.get_tool("scrape_webpage").function(url="https://example.org")
materials = []
materials.extend([{"material": "wood", "quantity": 1}])
""".strip()
    with pytest.raises(ValueError, match="hardcoded"):
        WorkflowAgent._validate_generated_python(bad)


def test_validate_generated_python_rejects_example_unit_price_in_research_workflow() -> None:
    bad = """
from workflowmvp.tools import ToolRegistry
tools = ToolRegistry()
unit_price = 10.0  # Example unit price
tools.get_tool("write_json").function(file_path="dresser_research.json", data=[], indent=2)
""".strip()
    with pytest.raises(ValueError, match="example"):
        WorkflowAgent._validate_generated_python(bad)


def test_validate_generated_python_rejects_discover_result_string_used_as_url_list() -> None:
    bad = """
from workflowmvp.tools import ToolRegistry
tools = ToolRegistry()
discover_urls_tool = tools.get_tool("discover_urls")
discover_result = discover_urls_tool.function(start_url="https://example.org/", keywords="x", max_results=5)
candidate_urls = []
candidate_urls.extend(discover_result.get("result", []))
""".strip()
    with pytest.raises(ValueError, match="urls_only"):
        WorkflowAgent._validate_generated_python(bad)


def test_validate_generated_python_allows_discover_urls_urls_field() -> None:
    ok = """
from workflowmvp.tools import ToolRegistry
tools = ToolRegistry()
d = tools.get_tool("discover_urls")
result = d.function(start_url="https://example.org", keywords="dresser", max_results=3)
candidates = result.get("urls", [])
for entry in candidates:
    page_url = entry.get("url")
    if not page_url:
        continue
    print(page_url)
""".strip()
    WorkflowAgent._validate_generated_python(ok)


def test_validate_generated_python_rejects_scrape_text_as_materials_dict() -> None:
    bad = """
from workflowmvp.tools import ToolRegistry
tools = ToolRegistry()
scrape = tools.get_tool("scrape_webpage")
scrape_result = scrape.function(url="https://example.org/page")
materials = scrape_result.get("result")
for material, quantity in materials.items():
    print(material, quantity)
""".strip()
    with pytest.raises(ValueError, match="scrape_webpage handling"):
        WorkflowAgent._validate_generated_python(bad)


def test_validate_generated_python_rejects_requests_import() -> None:
    bad = """
import requests
from workflowmvp.tools import ToolRegistry
tools = ToolRegistry()
""".strip()
    with pytest.raises(ValueError, match="import requests"):
        WorkflowAgent._validate_generated_python(bad)


def test_validate_generated_python_rejects_from_requests_import() -> None:
    bad = """
from requests import get
from workflowmvp.tools import ToolRegistry
tools = ToolRegistry()
""".strip()
    with pytest.raises(ValueError, match="import requests"):
        WorkflowAgent._validate_generated_python(bad)


def test_validate_generated_python_rejects_bs4_import() -> None:
    bad = """
from bs4 import BeautifulSoup
from workflowmvp.tools import ToolRegistry
tools = ToolRegistry()
""".strip()
    with pytest.raises(ValueError, match="import bs4"):
        WorkflowAgent._validate_generated_python(bad)


def test_validate_generated_python_rejects_ungrounded_long_generate_text_report() -> None:
    bad = """
from workflowmvp.tools import ToolRegistry
tools = ToolRegistry()
gen = tools.get_tool("generate_text")
gen.function(
    prompt=(
        "You are an expert. Write a comprehensive dresser_report.md with BOM, prices, "
        "and retailer links. Use professional tone. Include tables."
    ),
    max_tokens=2048,
)
""".strip()
    with pytest.raises(ValueError, match="generate_text report prompts"):
        WorkflowAgent._validate_generated_python(bad)


def test_validate_generated_python_allows_grounded_generate_text_report_prompt() -> None:
    ok = """
from workflowmvp.tools import ToolRegistry
tools = ToolRegistry()
gen = tools.get_tool("generate_text")
body = "x" * 100
gen.function(
    prompt=(
        "Write dresser_report.md using only the following text from our tools. "
        "Do not invent prices.\\n\\n"
        + body
    ),
    max_tokens=2048,
)
""".strip()
    WorkflowAgent._validate_generated_python(ok)


def test_validate_generated_python_allows_generate_text_fstring_with_source() -> None:
    ok = """
from workflowmvp.tools import ToolRegistry
tools = ToolRegistry()
gen = tools.get_tool("generate_text")
page = "wood oak pine"
gen.function(prompt=f"Summarize for report.md.\\n\\nScraped page:\\n{page[:8000]}", max_tokens=1024)
""".strip()
    WorkflowAgent._validate_generated_python(ok)


def test_validate_generated_python_rejects_illustrative_placeholder_research() -> None:
    bad = '''
from workflowmvp.tools import ToolRegistry
tools = ToolRegistry()
logger = __import__("logging").getLogger(__name__)
research_data = [
    {"source_name": "Illustrative Source 1 (No actual scraping)", "materials": []},
]
wj = tools.get_tool("write_json")
wj.function(file_path="dresser_research.json", data=research_data, indent=2)
'''.strip()
    with pytest.raises(ValueError, match="Illustrative/placeholder research"):
        WorkflowAgent._validate_generated_python(bad)


def test_validate_generated_python_allows_real_scrape_then_write_json() -> None:
    ok = """
import logging
from workflowmvp.tools import ToolRegistry
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def main() -> None:
    tools = ToolRegistry()
    scrape = tools.get_tool("scrape_webpage")
    r = scrape.function(url="https://example.org/plans")
    if not r.get("success"):
        logger.error(r.get("error"))
        return
    text = r.get("result") or ""
    wj = tools.get_tool("write_json")
    wj.function(file_path="dresser_research.json", data=[{"source_name": "example.org", "excerpt": text[:2000]}], indent=2)

if __name__ == "__main__":
    main()
""".strip()
    WorkflowAgent._validate_generated_python(ok)


def test_validate_generated_python_rejects_research_refusal_without_web_tools() -> None:
    bad = '''
from workflowmvp.tools import ToolRegistry
tools = ToolRegistry()
research_data = {
    "status": "failed",
    "message": "Automated research and structured data extraction could not be completed.",
    "materials_by_source": [],
}
tools.get_tool("write_json").function(file_path="dresser_research.json", data=research_data, indent=2)
'''.strip()
    with pytest.raises(ValueError, match="discover_urls|Illustrative/placeholder research"):
        WorkflowAgent._validate_generated_python(bad)


def test_validate_generated_python_allows_failed_research_after_scrape_attempt() -> None:
    ok = """
from workflowmvp.tools import ToolRegistry
tools = ToolRegistry()
scrape = tools.get_tool("scrape_webpage")
r = scrape.function(url="https://example.org/x")
research_data = {"status": "failed", "message": "empty page", "materials_by_source": []}
if r.get("success") and (r.get("result") or ""):
    research_data = {"status": "ok", "materials_by_source": []}
tools.get_tool("write_json").function(file_path="dresser_research.json", data=research_data, indent=2)
""".strip()
    WorkflowAgent._validate_generated_python(ok)


def test_validate_generated_python_rejects_schedule_placeholder_email() -> None:
    bad = """
from workflowmvp.tools import ToolRegistry
tools = ToolRegistry()
send_email_tool = tools.get_tool('send_email')
schedule_details = "Ani-marathon schedule not found in scraped content."
send_email_tool.function(
    recipient="person@example.com",
    subject="Ani-Marathon Reminder",
    body=schedule_details,
)
""".strip()
    with pytest.raises(ValueError, match="missing-schedule placeholder"):
        WorkflowAgent._validate_generated_python(bad)
