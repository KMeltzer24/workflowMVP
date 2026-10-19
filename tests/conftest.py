"""Shared pytest fixtures.

Adds the project root to sys.path so `import main` and `import workflowmvp`
work without needing an editable install.
"""

from __future__ import annotations

import os
import sys

import pytest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# Keep legacy blocking endpoint enabled for tests that still exercise it.
os.environ.setdefault("WORKFLOW_ENABLE_BLOCKING_RUN_ENDPOINT", "1")

import main  # noqa: E402  # import after sys.path so `main` resolves


@pytest.fixture()
def client():
    main.app.config["TESTING"] = True
    with main.app.test_client() as test_client:
        # Browser POSTs always send Origin; require it in production, so tests do too.
        test_client.environ_base["HTTP_ORIGIN"] = "http://localhost"
        yield test_client
