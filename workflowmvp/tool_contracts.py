"""Tool response contracts used by codegen prompt and validators.

This keeps tool-specific response-shape rules out of ``agent.py``. Adding a
new contract should be local to this file: guidance for the model, retry
instruction text, and an optional validator that rejects known misuse patterns
before generated code is written.
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass
from typing import Callable, Iterable, Optional

Validator = Callable[[str], Optional[str]]


@dataclass(frozen=True)
class ToolContract:
    tool_name: str
    prompt_guidance: str
    retry_guidance: str
    validator: Validator | None = None
    always_include: bool = False


def _uses_tool(code: str, tool_name: str) -> bool:
    return bool(re.search(rf"get_tool\(\s*['\"]{re.escape(tool_name)}['\"]\s*\)", code))


def _validate_http_request(code: str) -> Optional[str]:
    if not _uses_tool(code, "http_request"):
        return None
    unsafe_json_loads = bool(
        re.search(
            r"json\.loads\(\s*[A-Za-z_]\w*\.get\(\s*['\"]result['\"]",
            code,
        )
    )
    has_type_guard = "isinstance(" in code and "dict" in code
    if unsafe_json_loads and not has_type_guard:
        return (
            "Invalid http_request result handling: `result` may be dict/list. "
            "Add a type guard before json.loads."
        )
    return None


def _validate_discover_urls(code: str) -> Optional[str]:
    if not _uses_tool(code, "discover_urls"):
        return None
    bad_result_iteration = bool(
        re.search(
            r"\w+\s*=\s*\w+\.get\(\s*['\"]result['\"]\s*,\s*\[\s*\]\s*\)",
            code,
        )
    )
    if bad_result_iteration:
        return (
            "Invalid discover_urls result handling: iterate over `response['urls']` "
            "(entries with `url`), not `response['result']`."
        )
    # ``result`` on discover_urls is a JSON *string* for logging — not a URL list. Using
    # ``.get('result', [])`` then extend/for/len is a common bug (iterates characters).
    if bool(
        re.search(
            r"(?i)\b(?:discover_result|discover_response|discover_out|"
            r"discovery_result|discovery_response)\.get\(\s*['\"]result['\"]",
            code,
        )
    ):
        return (
            "Invalid discover_urls handling: `response['result']` is a debug JSON string, "
            "not URL strings. Use `response.get('urls') or []` (each entry has `url` and "
            "`score`) or `response.get('urls_only') or []`."
        )
    if re.search(
        r"start_url\s*=\s*['\"]https?://(?:www\.)?(?:google|bing|duckduckgo)\.",
        code,
        re.I,
    ):
        return (
            "Invalid discover_urls `start_url`: do not use general search homepages (google.com, bing.com, …). "
            "Use a real publisher, plans site, or retailer from the step text, or an explicit article URL."
        )
    return None


def _validate_scrape_webpage(code: str) -> Optional[str]:
    # scrape_webpage returns text content, not a structured dict of materials.
    # Catch a frequent bad pattern: assigning scraped `result` to `materials`
    # then calling `materials.items()`.
    scrape_to_materials = bool(
        re.search(
            r"materials\s*=\s*[A-Za-z_]\w*\.get\(\s*['\"]result['\"]\s*\)",
            code,
        )
    )
    iter_materials_items = bool(
        re.search(r"for\s+\w+\s*,\s*\w+\s+in\s+materials\.items\(\)", code)
    )
    if scrape_to_materials and iter_materials_items:
        return (
            "Invalid scrape_webpage handling: scraped `result` is text. "
            "Do not call `materials.items()` without first parsing/structuring it."
        )
    return None


TOOL_CONTRACTS: dict[str, ToolContract] = {
    "http_request": ToolContract(
        tool_name="http_request",
        always_include=True,
        prompt_guidance=(
            "### http_request response contract\n"
            "`http_request` may return parsed JSON directly in `result` when the "
            "response content-type is JSON; otherwise `result` is text.\n"
            "Correct pattern:\n"
            "   raw = response.get('result')\n"
            "   data = raw if isinstance(raw, (dict, list)) else json.loads(raw or '{}')"
        ),
        retry_guidance=(
            "If you use `http_request`, do not call `json.loads(...)` directly "
            "on `response.get('result')` without first handling that `result` "
            "may already be a parsed dict/list."
        ),
        validator=_validate_http_request,
    ),
    "discover_urls": ToolContract(
        tool_name="discover_urls",
        prompt_guidance=(
            "### discover_urls response contract\n"
            "`discover_urls` success responses use:\n"
            "- `urls`: list of objects like `{'url': 'https://...', 'score': 3}` "
            "(use this for iteration). The normalized **`start_url` is always present** "
            "(score may be 0); scrape it when it is the only useful page or ranks highest.\n"
            "- `urls_only`: same URLs as plain strings (convenience).\n"
            "- `result`: JSON summary string for logging only — **do not** treat as a list of URLs.\n"
            "Correct pattern:\n"
            "   d = tools.get_tool('discover_urls').function(start_url='https://example.org', keywords='dresser plans')\n"
            "   if not d.get('success'):\n"
            "       logger.error(d.get('error')); return\n"
            "   candidates = d.get('urls') or []\n"
            "   for entry in candidates[:3]:\n"
            "       page_url = entry.get('url')\n"
            "       if not page_url:\n"
            "           continue"
        ),
        retry_guidance=(
            "If you use `discover_urls`, use `response.get('urls') or []` or `response.get('urls_only') or []` — "
            "never `response.get('result')` for URL lists (`result` is a JSON debug string)."
        ),
        validator=_validate_discover_urls,
    ),
    "scrape_webpage": ToolContract(
        tool_name="scrape_webpage",
        prompt_guidance=(
            "### scrape_webpage response contract\n"
            "`scrape_webpage` returns text (`content`/`result` string), not a structured dict.\n"
            "The `url` argument may be a string or a `discover_urls` row dict (`{'url': '...', 'score': n}`); "
            "prefer `entry.get('url')` or iterate `urls_only` for clarity.\n"
            "Incorrect:\n"
            "   materials = scrape_result.get('result')\n"
            "   for material, qty in materials.items(): ...\n"
            "Correct:\n"
            "   page_text = scrape_result.get('result') or ''\n"
            "   # Parse/extract structured data from text first, then iterate dict/list structures."
        ),
        retry_guidance=(
            "If you use `scrape_webpage`, treat the output as text "
            "(`content`/`result` string). Do not call `.items()` on scraped text; "
            "first parse/structure it."
        ),
        validator=_validate_scrape_webpage,
    ),
}


def relevant_contract_keys(actions: Iterable[str]) -> list[str]:
    selected: list[str] = []
    seen: set[str] = set()
    for name, contract in TOOL_CONTRACTS.items():
        if contract.always_include or name in actions:
            if name not in seen:
                selected.append(name)
                seen.add(name)
    return selected


def build_contract_prompt_guidance(actions: Iterable[str]) -> str:
    keys = relevant_contract_keys(actions)
    if not keys:
        return ""
    snippets = [TOOL_CONTRACTS[key].prompt_guidance for key in keys]
    return "## TOOL RESPONSE CONTRACTS\n\n" + "\n\n".join(snippets)


def build_retry_contract_guidance() -> str:
    lines = [f"- {contract.retry_guidance}" for contract in TOOL_CONTRACTS.values()]
    lines.append(
        "- Do not `import requests` or `bs4` — use `http_request` / `scrape_webpage` / `discover_urls`."
    )
    lines.append(
        "- For report-style `generate_text`, the prompt must include pasted excerpts "
        "(f-string with retrieved text), not a meta-only \"write a report\" instruction."
    )
    lines.append(
        "- Never substitute illustrative/placeholder research, fake \"sources\", or invented "
        "price tables for web research steps — use `discover_urls` + `scrape_webpage` "
        "(or `http_request`) and fail fast if retrieval fails."
    )
    lines.append(
        "- Do not \"refuse\" web-research steps by writing stub JSON / status:failed payloads "
        "without calling `discover_urls` / `scrape_webpage` — try tools first, then fail fast "
        "without email if nothing was retrieved."
    )
    return "\n".join(lines)


def _validate_no_placeholder_research_copout(code: str) -> Optional[str]:
    """Reject scripts that skip real retrieval with fake illustrative data or excuses."""
    lowered = code.lower()
    high_signal = (
        "illustrative source",
        "no actual scraping",
        "no actual web scraping",
        "generating placeholder",
        "not performed due to the absence of specific url",
        "as actual web scraping was not performed",
        "not provided for live scraping",
        "without live scraping",
        "placeholder indicating missing",
        "placeholder content indicating",
        "extraction could not be completed",
        "without explicit urls or detailed scraping",
        "detailed parsing instructions were not provided",
        "advanced parsing capabilities not directly available",
    )
    if any(needle in lowered for needle in high_signal):
        return (
            "Illustrative/placeholder research is not allowed: do not invent sources, "
            "materials lists, or retail prices to stand in for `discover_urls` / "
            "`scrape_webpage` / `http_request`. Retrieve real pages or stop with a clear error."
        )
    if "skipping consolidation" in lowered and "placeholder" in lowered:
        return (
            "Do not skip consolidation with placeholder research — use real `scrape_webpage` "
            "output or stop before downstream steps."
        )
    if "skipping cost estimation" in lowered and "placeholder" in lowered:
        return (
            "Do not skip cost steps citing placeholder research — retrieve real data or exit "
            "before reports/email."
        )
    return None


def _validate_research_refusal_without_web_tools(code: str) -> Optional[str]:
    """Reject scripts that claim research cannot be done but never call web tools."""
    lowered = code.lower()
    refusal_hint = (
        "could not be completed" in lowered
        or "cannot be performed" in lowered
        or '"status": "failed"' in lowered
        or "'status': 'failed'" in lowered
        or '"status": \'failed\'' in lowered
    )
    research_hint = (
        "research" in lowered
        and (
            "dresser_research" in lowered
            or "_research.json" in lowered
            or "materials_by_source" in lowered
            or "structured data extraction" in lowered
        )
    )
    if not (refusal_hint and research_hint):
        return None
    tried_web = (
        "discover_urls" in lowered
        or "scrape_webpage" in lowered
        or "get_tool('http_request')" in code
        or 'get_tool("http_request")' in code
    )
    if tried_web:
        return None
    return (
        "Web research steps must call `discover_urls` and/or `scrape_webpage` (or `http_request`) "
        "before writing a failed/empty research payload. Do not claim URLs are \"unspecified\" "
        "if the workflow implies web research — attempt discovery + scrape, then fail fast without "
        "placeholder JSON, reports, or email."
    )


def _validate_no_phony_materials_after_scrape(code: str) -> Optional[str]:
    """Reject loops that ignore scraped text and append toy material dicts (wood/screws stubs)."""
    if not _uses_tool(code, "scrape_webpage"):
        return None
    if re.search(
        r"materials\.extend\(\[\s*\{\s*['\"]material['\"]\s*:\s*['\"]|"
        r"materials\.append\(\{\s*['\"]material['\"]\s*:\s*['\"]",
        code,
    ):
        return (
            "Do not append hardcoded `{'material': '...'}` dicts while "
            "ignoring scraped page text. Derive materials from excerpts via `generate_text` or parsing."
        )
    return None


def _validate_no_example_unit_pricing_in_research_workflow(code: str) -> Optional[str]:
    """Reject 'example' unit prices in dresser/research BOM-style workflows."""
    lowered = code.lower()
    if "dresser_research" not in lowered and "_research.json" not in lowered:
        return None
    if re.search(r"unit_price\s*=\s*[\d.]+\s*#\s*[Ee]xample", code) or re.search(
        r"#\s*[Ee]xample\s+unit\s+price", code
    ):
        return (
            "Do not use example/placeholder `unit_price` values in research workflows. "
            "Use prices from scraped text or mark line items as unknown / verify in store."
        )
    return None


def _validate_no_banned_http_scrape_imports(code: str) -> Optional[str]:
    """Generated workflows must use ToolRegistry (scrape_webpage, http_request,
    discover_urls), not ad-hoc ``requests`` / BeautifulSoup — those bypass the
    intended tool surface and often produce ungrounded reports.
    """
    if re.search(r"^\s*import\s+requests\b", code, re.MULTILINE) or re.search(
        r"^\s*from\s+requests\b", code, re.MULTILINE
    ):
        return (
            "Do not `import requests` in generated workflows. Use "
            "`tools.get_tool('http_request')` or `tools.get_tool('scrape_webpage')`."
        )
    if re.search(r"^\s*import\s+bs4\b", code, re.MULTILINE) or re.search(
        r"^\s*from\s+bs4\b", code, re.MULTILINE
    ):
        return (
            "Do not `import bs4` / BeautifulSoup in generated workflows. Use "
            "`tools.get_tool('scrape_webpage')` for HTML → text."
        )
    return None


def _get_tool_name_from_call(call: ast.Call) -> Optional[str]:
    """If ``call`` is ``*.get_tool('name')``, return ``name``."""
    func = call.func
    if not isinstance(func, ast.Attribute) or func.attr != "get_tool":
        return None
    if not call.args:
        return None
    arg0 = call.args[0]
    if isinstance(arg0, ast.Constant) and isinstance(arg0.value, str):
        return arg0.value
    return None


def _collect_generate_text_locals(tree: ast.AST) -> set[str]:
    """Names bound to ``get_tool('generate_text')`` (handles ``gen = tools.get_tool(...)``)."""
    names: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        tool_name = _get_tool_name_from_call(node.value) if isinstance(node.value, ast.Call) else None
        if tool_name != "generate_text":
            continue
        for target in node.targets:
            if isinstance(target, ast.Name):
                names.add(target.id)
    return names


def _validate_generate_text_report_grounding(code: str) -> Optional[str]:
    """Reject meta-only ``generate_text`` prompts that ask for a report without
    pasting source material (common cause of fabricated BOM/prices).
    """
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return None

    gen_locals = _collect_generate_text_locals(tree)

    class Visitor(ast.NodeVisitor):
        def __init__(self, generate_text_vars: set[str]) -> None:
            self._generate_text_vars = generate_text_vars
            self.error: Optional[str] = None

        def visit_Call(self, node: ast.Call) -> None:
            if self.error is not None:
                return
            func = node.func
            if not isinstance(func, ast.Attribute) or func.attr != "function":
                self.generic_visit(node)
                return
            inner = func.value
            is_generate_text = False
            if isinstance(inner, ast.Call):
                is_generate_text = _get_tool_name_from_call(inner) == "generate_text"
            elif isinstance(inner, ast.Name) and inner.id in self._generate_text_vars:
                is_generate_text = True
            if not is_generate_text:
                self.generic_visit(node)
                return
            prompt_kw = next((k for k in node.keywords if k.arg == "prompt"), None)
            if prompt_kw is None:
                self.generic_visit(node)
                return
            err = _prompt_value_grounding_error(prompt_kw.value)
            if err:
                self.error = err
            self.generic_visit(node)

    visitor = Visitor(gen_locals)
    visitor.visit(tree)
    return visitor.error


def _prompt_value_grounding_error(node: ast.expr) -> Optional[str]:
    """Return error message if prompt AST node is an ungrounded report request."""
    if isinstance(node, ast.JoinedStr):
        if any(isinstance(p, ast.FormattedValue) for p in node.values):
            return None
        parts: list[str] = []
        for p in node.values:
            if isinstance(p, ast.Constant) and isinstance(p.value, str):
                parts.append(p.value)
        text = "".join(parts)
        return _meta_report_prompt_error(text)

    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return _meta_report_prompt_error(node.value)

    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        return None

    if isinstance(node, ast.Name):
        return None

    return None


def _meta_report_prompt_error(text: str) -> Optional[str]:
    if len(text) < 80:
        return None
    lowered = text.lower()
    reportish = (
        "write a report" in lowered
        or "write report" in lowered
        or "dresser_report" in lowered
        or "report.md" in lowered
    )
    if not reportish:
        return None
    grounded_markers = (
        "source material",
        "verbatim",
        "excerpt",
        "scraped",
        "below is",
        "following text",
        "tool output",
        "---",
    )
    if any(m in lowered for m in grounded_markers):
        return None
    return (
        "generate_text report prompts must include pasted source excerpts or tool "
        "outputs (e.g. f-string with {combined_text[:12000]}). Do not use a meta-only "
        "instruction that invents BOM/prices."
    )


def validate_tool_contracts(code: str) -> None:
    for contract in TOOL_CONTRACTS.values():
        if not contract.validator:
            continue
        error = contract.validator(code)
        if error:
            raise ValueError(error)

    extra = _validate_no_banned_http_scrape_imports(code)
    if extra:
        raise ValueError(extra)

    gt_err = _validate_generate_text_report_grounding(code)
    if gt_err:
        raise ValueError(gt_err)

    ph_err = _validate_no_placeholder_research_copout(code)
    if ph_err:
        raise ValueError(ph_err)

    rw_err = _validate_research_refusal_without_web_tools(code)
    if rw_err:
        raise ValueError(rw_err)

    toy_m = _validate_no_phony_materials_after_scrape(code)
    if toy_m:
        raise ValueError(toy_m)

    toy_p = _validate_no_example_unit_pricing_in_research_workflow(code)
    if toy_p:
        raise ValueError(toy_p)
