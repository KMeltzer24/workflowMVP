#!/usr/bin/env python3
"""WorkflowMVP cleanup helpers.

`cleanup_files` wipes generated workflow scripts and everything under
`data/temp_outputs/`.
"""

from __future__ import annotations

import glob
import os
import shutil

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
GENERATED_DIR = os.path.join(PROJECT_ROOT, "data", "generated_workflows")
TEMP_OUTPUTS_DIR = os.path.join(PROJECT_ROOT, "data", "temp_outputs")


def cleanup_files(verbose: bool = True) -> int:
    """Clean up all generated workflow files and temp outputs."""
    cleanup_count = 0

    if verbose:
        print("Starting cleanup...")

    if verbose:
        print("Cleaning generated_workflows directory...")
    for file_path in glob.glob(os.path.join(GENERATED_DIR, "*.py")):
        try:
            os.unlink(file_path)
            if verbose:
                print(f"  deleted: {file_path}")
            cleanup_count += 1
        except OSError as exc:
            if verbose:
                print(f"  could not delete {file_path}: {exc}")

    if verbose:
        print("Cleaning data/temp_outputs directory...")
    if os.path.isdir(TEMP_OUTPUTS_DIR):
        for entry in os.listdir(TEMP_OUTPUTS_DIR):
            path = os.path.join(TEMP_OUTPUTS_DIR, entry)
            try:
                if os.path.isfile(path) or os.path.islink(path):
                    os.unlink(path)
                elif os.path.isdir(path):
                    shutil.rmtree(path)
                if verbose:
                    print(f"  deleted: {path}")
                cleanup_count += 1
            except OSError as exc:
                if verbose:
                    print(f"  could not delete {path}: {exc}")

    if verbose:
        print("Cleaning __pycache__ directories under data/...")
    for pycache_dir in glob.glob(
        os.path.join(PROJECT_ROOT, "data", "**", "__pycache__"), recursive=True
    ):
        try:
            shutil.rmtree(pycache_dir)
            if verbose:
                print(f"  deleted __pycache__: {pycache_dir}")
            cleanup_count += 1
        except OSError as exc:
            if verbose:
                print(f"  could not delete {pycache_dir}: {exc}")

    if verbose:
        print(f"Cleanup complete. Removed {cleanup_count} files/directories.")

    return cleanup_count

if __name__ == "__main__":
    cleanup_files()
