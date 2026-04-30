"""Cleanup helpers that wipe generated scripts and per-run output dirs.

Used by the Flask shutdown hook and the ``/api/cleanup`` endpoint.
"""

from __future__ import annotations

import glob
import os
import shutil
from typing import Optional

from .paths import GENERATED_DIR, TEMP_OUTPUTS_DIR


def cleanup_files(verbose: bool = True, *, generated_dir: Optional[str] = None,
                  temp_outputs_dir: Optional[str] = None) -> int:
    """Wipe generated workflow scripts and everything under ``temp_outputs_dir``.

    Defaults match the production layout (``data/generated_workflows`` and
    ``data/temp_outputs``) but can be overridden for tests. Returns the
    total number of files / directories removed.
    """
    gen_dir = generated_dir or GENERATED_DIR
    temp_dir = temp_outputs_dir or TEMP_OUTPUTS_DIR

    count = 0
    for file_path in glob.glob(os.path.join(gen_dir, "*.py")):
        try:
            os.unlink(file_path)
            count += 1
            if verbose:
                print(f"  deleted: {file_path}")
        except OSError as exc:
            if verbose:
                print(f"  could not delete {file_path}: {exc}")

    if os.path.isdir(temp_dir):
        for entry in os.listdir(temp_dir):
            path = os.path.join(temp_dir, entry)
            try:
                if os.path.isfile(path) or os.path.islink(path):
                    os.unlink(path)
                elif os.path.isdir(path):
                    shutil.rmtree(path)
                count += 1
                if verbose:
                    print(f"  deleted: {path}")
            except OSError as exc:
                if verbose:
                    print(f"  could not delete {path}: {exc}")

    if verbose:
        print(f"Cleanup complete. Removed {count} items.")
    return count
