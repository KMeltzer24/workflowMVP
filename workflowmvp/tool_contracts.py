"""Tool response contracts used by codegen prompt and validators.

This keeps tool-specific response-shape rules out of ``agent.py``. Adding a
new contract should be local to this file: guidance for the model, retry
instruction text, and an optional validator that rejects known misuse patterns
before generated code is written.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from typing import Callable, Iterable, Optional

Validator = Callable[[str], Optional[str]]
_SEARCH_HOMEPAGE_MARKERS = ("google.com", "bing.com", "duckduckgo.com")


@dataclass(frozen=True)
class ToolContract:
    tool_name: str
    prompt_guidance: str
    retry_guidance: str
    validator: Validator | None = None
    always_include: bool = False


def _parse_module(code: str) -> ast.AST | None:
    try:
        return ast.parse(code)
    except SyntaxError:
        return None


def _uses_tool(tree: ast.AST, tool_name: str) -> bool:
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not isinstance(func, ast.Attribute) or func.attr != "get_tool":
            continue
        if not node.args:
            continue
        arg0 = node.args[0]
        if isinstance(arg0, ast.Constant) and arg0.value == tool_name:
            return True
    return False


def _is_get_key(call: ast.AST, key: str) -> bool:
    if not isinstance(call, ast.Call):
        return False
    if not isinstance(call.func, ast.Attribute) or call.func.attr != "get":
        return False
    if not call.args:
        return False
    arg0 = call.args[0]
    return isinstance(arg0, ast.Constant) and arg0.value == key


def _expr_contains_get_result(node: ast.AST) -> bool:
    if _is_get_key(node, "result"):
        return True
    for child in ast.iter_child_nodes(node):
        if _expr_contains_get_result(child):
            return True
    return False


def _is_json_loads_call(call: ast.Call) -> bool:
    func = call.func
    if isinstance(func, ast.Attribute) and func.attr == "loads":
        return isinstance(func.value, ast.Name) and func.value.id == "json"
    return isinstance(func, ast.Name) and func.id == "loads"


def _has_isinstance_guard(tree: ast.AST) -> bool:
    return any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "isinstance"
        for node in ast.walk(tree)
    )


def _get_result_default_empty_list(call: ast.Call) -> bool:
    if not _is_get_key(call, "result"):
        return False
    if len(call.args) >= 2 and isinstance(call.args[1], ast.List) and not call.args[1].elts:
        return True
    return False


def _name_looks_like_discover(node: ast.AST) -> bool:
    return isinstance(node, ast.Name) and "discover" in node.id.lower()


def _kwarg_str(call: ast.Call, name: str) -> Optional[str]:
    for kw in call.keywords:
        if kw.arg == name and isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, str):
            return kw.value.value
    return None


def _validate_http_request(code: str) -> Optional[str]:
    tree = _parse_module(code)
    if tree is None or not _uses_tool(tree, "http_request"):
        return None
    unsafe_json_loads = False
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and _is_json_loads_call(node) and node.args:
            if _expr_contains_get_result(node.args[0]):
                unsafe_json_loads = True
                break
    if unsafe_json_loads and not _has_isinstance_guard(tree):
        return (
            "Invalid http_request result handling: `result` may be dict/list. "
            "Add a type guard before json.loads."
        )
    return None


def _validate_discover_urls(code: str) -> Optional[str]:
    tree = _parse_module(code)
    if tree is None or not _uses_tool(tree, "discover_urls"):
        return None
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and _get_result_default_empty_list(node):
            return (
                "Invalid discover_urls result handling: iterate over `response['urls']` "
                "(entries with `url`), not `response['result']`."
            )
        if (
            isinstance(node, ast.Call)
            and _is_get_key(node, "result")
            and isinstance(node.func, ast.Attribute)
            and _name_looks_like_discover(node.func.value)
        ):
            return (
                "Invalid discover_urls handling: `response['result']` is a debug JSON string, "
                "not URL strings. Use `response.get('urls') or []` (each entry has `url` and "
                "`score`) or `response.get('urls_only') or []`."
            )
        if isinstance(node, ast.Call):
            start_url = _kwarg_str(node, "start_url")
            if start_url and any(marker in start_url.lower() for marker in _SEARCH_HOMEPAGE_MARKERS):
                return (
                    "Invalid discover_urls `start_url`: do not use general search homepages "
                    "(google.com, bing.com, …). "
                    "Use a real publisher, plans site, or retailer from the step text, or an explicit article URL."
                )
    return None


def _validate_scrape_webpage(code: str) -> Optional[str]:
    tree = _parse_module(code)
    if tree is None:
        return None
    materials_from_result = False
    iter_materials_items = False
    materials_extend_result = False
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            if any(isinstance(t, ast.Name) and t.id == "materials" for t in node.targets):
                if _is_get_key(node.value, "result"):
                    materials_from_result = True
        if isinstance(node, ast.For) and isinstance(node.iter, ast.Call):
            func = node.iter.func
            if (
                isinstance(func, ast.Attribute)
                and func.attr == "items"
                and isinstance(func.value, ast.Name)
                and func.value.id == "materials"
            ):
                iter_materials_items = True
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if (
                node.func.attr == "extend"
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "materials"
                and node.args
                and _expr_contains_get_result(node.args[0])
            ):
                materials_extend_result = True
    if materials_from_result and iter_materials_items:
        return (
            "Invalid scrape_webpage handling: scraped `result` is text. "
            "Do not call `materials.items()` without first parsing/structuring it."
        )
    if _uses_tool(tree, "scrape_webpage") and materials_extend_result:
        return (
            "Invalid scrape_webpage handling: do not `materials.extend(resp.get('result'))` — "
            "scraped `result` is plain text; extend would iterate characters. "
            "Build structured rows (e.g. `generate_text` + "
            "`workflowmvp.json_llm.extract_first_json_value`, or parse fields) "
            "then `append` dicts, and use `write_json` when the step names a `.json` file."
        )
    return None


def _imports_json_llm_helper(tree: ast.AST) -> bool:
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and (node.module or "").endswith("json_llm"):
            return True
        if isinstance(node, ast.Name) and node.id == "extract_first_json_value":
            return True
        if isinstance(node, ast.Attribute) and node.attr == "extract_first_json_value":
            return True
    return False


def _validate_generate_text_json_via_helper_when_web(code: str) -> Optional[str]:
    """LLM outputs need strip/fence tolerant parsing — not naive ``json.loads`` on ``result``."""
    tree = _parse_module(code)
    if tree is None:
        return None
    if not _uses_tool(tree, "generate_text"):
        return None
    if not (_uses_tool(tree, "scrape_webpage") or _uses_tool(tree, "discover_urls")):
        return None
    has_json_loads = any(
        isinstance(node, ast.Call) and _is_json_loads_call(node) for node in ast.walk(tree)
    )
    if not has_json_loads:
        return None
    if _imports_json_llm_helper(tree):
        return None
    return (
        "When `generate_text` emits JSON after `scrape_webpage` / `discover_urls`, do not "
        "`json.loads(...)` raw `result` strings. Import "
        "`from workflowmvp.json_llm import extract_first_json_value` "
        "and parse with `extract_first_json_value(resp.get(\"result\") or \"\")`. "
        "Use a large `max_tokens` (e.g. 4096) so JSON arrays are not truncated mid-stream."
    )


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


def _step_descriptions_suggest_web_retrieval(descriptions: Iterable[str]) -> bool:
    """True when natural-language steps imply URL discovery / scraping.

    Rule-first parsing often leaves research steps as ``custom``; we still inject
    ``discover_urls`` / ``scrape_webpage`` contracts so codegen sees response shapes.
    """
    for raw in descriptions:
        d = (raw or "").lower()
        if any(x in d for x in ("scrape", "sitemap", "webpage", "http://", "https://", "www.")):
            return True
        if any(x in d for x in ("discover url", "discover urls", "crawl")):
            return True
        if ("research" in d or "sources" in d or "retailer" in d) and any(
            w in d
            for w in (
                "website",
                "web ",
                "web.",
                " online",
                "url",
                "article",
                "guide",
                "project",
                "woodworking",
            )
        ):
            return True
    return False


def relevant_contract_keys(
    actions: Iterable[str],
    step_descriptions: Optional[Iterable[str]] = None,
) -> list[str]:
    selected: list[str] = []
    seen: set[str] = set()
    actions_set = set(actions)
    for name, contract in TOOL_CONTRACTS.items():
        if contract.always_include or name in actions_set:
            if name not in seen:
                selected.append(name)
                seen.add(name)
    if step_descriptions is not None and _step_descriptions_suggest_web_retrieval(
        step_descriptions
    ):
        for name in ("discover_urls", "scrape_webpage"):
            if name not in seen:
                selected.append(name)
                seen.add(name)
    return selected


def build_contract_prompt_guidance(
    actions: Iterable[str],
    step_descriptions: Optional[Iterable[str]] = None,
) -> str:
    keys = relevant_contract_keys(actions, step_descriptions=step_descriptions)
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
        "- If `generate_text` must return JSON lists/objects, parse via "
        "`workflowmvp.json_llm.extract_first_json_value` (not bare `json.loads` on prose/fences)."
    )
    return "\n".join(lines)


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
        "instruction that invents facts or prices."
    )


def validate_tool_contracts(code: str) -> None:
    for contract in TOOL_CONTRACTS.values():
        if not contract.validator:
            continue
        error = contract.validator(code)
        if error:
            raise ValueError(error)

    json_loads_err = _validate_generate_text_json_via_helper_when_web(code)
    if json_loads_err:
        raise ValueError(json_loads_err)
