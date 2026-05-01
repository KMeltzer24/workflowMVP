"""Shared planning helpers for text and video workflow inputs.

Input-specific routes can produce rough workflow text in different ways, but
they should converge on the same parse/cleanup decision before code generation.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, List

from workflowmvp.parser import WorkflowParser, WorkflowStep


@dataclass(frozen=True)
class WorkflowPlanningResult:
    """Rule-parser output plus metadata used by optional AI cleanup."""

    steps: List[WorkflowStep]
    parse_confidence: dict[str, Any]
    should_ai_repair: bool


def should_repair_with_ai(parse_confidence: dict[str, Any]) -> bool:
    """Return True when rule-parser output should be normalized by the LLM.

    Missing required params block code generation, so they always merit repair.
    Custom steps are common in valid workflows, though; they should trigger AI
    cleanup only when the overall confidence score is low enough to suggest the
    rule-first parse is not useful on its own.
    """
    return (
        bool(parse_confidence.get("needs_ai_assist"))
        or int(parse_confidence.get("missing_param_steps") or 0) > 0
    )


def parse_rough_workflow(
    workflow_text: str, parser: WorkflowParser | None = None
) -> WorkflowPlanningResult:
    """Run the deterministic parser and decide whether AI cleanup is useful."""
    parser = parser or WorkflowParser()
    steps = parser.parse_workflow(workflow_text)
    confidence = parser.assess_parse_confidence(steps)
    return WorkflowPlanningResult(
        steps=steps,
        parse_confidence=confidence,
        should_ai_repair=should_repair_with_ai(confidence),
    )
