"""Prompt templates used by WorkflowMVP."""

from __future__ import annotations

from importlib.resources import files


def load_prompt_template(name: str) -> str:
    """Read a prompt template bundled with the package."""
    return files(__package__).joinpath(name).read_text(encoding="utf-8")
