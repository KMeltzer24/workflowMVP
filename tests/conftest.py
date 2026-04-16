"""Shared pytest fixtures.

Adds the project root to sys.path so `import main` and `import workflowmvp`
work without needing an editable install.
"""

from __future__ import annotations

import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)
