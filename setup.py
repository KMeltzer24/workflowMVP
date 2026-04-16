"""Thin shim so `pip install -e .` keeps working on older pip versions.

The source of truth for packaging metadata is `pyproject.toml`.
"""

from setuptools import setup

setup()
