"""Tests for workflowmvp.json_llm — LLM output JSON extraction."""

from workflowmvp.json_llm import extract_first_json_value


def test_extract_plain_object() -> None:
    raw = '{"a": 1, "b": "x"}'
    assert extract_first_json_value(raw) == {"a": 1, "b": "x"}


def test_extract_after_preamble_and_fenced_block() -> None:
    raw = '''The schedule is unavailable.

```json
{"items": [{"name": "a", "qty": 2}], "notes": ""}
```
'''
    assert extract_first_json_value(raw) == {"items": [{"name": "a", "qty": 2}], "notes": ""}


def test_extract_array_single_object_normalized_to_first_value() -> None:
    raw = "```json\n[{\"x\": 1}, {\"x\": 2}]\n```"
    assert extract_first_json_value(raw) == [{"x": 1}, {"x": 2}]


def test_none_on_empty() -> None:
    assert extract_first_json_value("") is None
    assert extract_first_json_value("   ") is None
