"""Filesystem locations shared across the Flask app and the services modules.

Centralising these constants prevents drift between ``main.py`` and the
service helpers (which all need to know where generated scripts and
per-run output directories live).
"""

from __future__ import annotations

import os

# Project root resolves to the repo root (one level above this package).
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))

# Where ``WorkflowAgent.generate_workflow_code`` writes scripts.
GENERATED_DIR = os.path.join(PROJECT_ROOT, "data", "generated_workflows")

# Per-run subprocess working directories live under here.
TEMP_OUTPUTS_DIR = os.path.join(PROJECT_ROOT, "data", "temp_outputs")

# Read-only sample inputs staged into each run directory for video demos.
EXAMPLE_INPUTS_DIR = os.path.join(PROJECT_ROOT, "examples", "inputs")
