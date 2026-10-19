.PHONY: help install dev run debug test lint format clean

# Prefer project venv when present (Python 3.11+).
PYTHON := $(if $(wildcard .venv/bin/python),.venv/bin/python,python3)

PORT ?= 5050

help:
	@echo "WorkflowMVP make targets"
	@echo "  make install   - install runtime dependencies"
	@echo "  make dev       - install dev dependencies (pytest, ruff, mypy)"
	@echo "  make run       - start web UI (PORT=$(PORT))"
	@echo "  make debug     - start web UI with debug logs (PORT=$(PORT))"
	@echo "  make test      - pytest with coverage floor on workflowmvp"
	@echo "  make lint      - ruff check + mypy workflowmvp"
	@echo "  make format    - run ruff format"
	@echo "  make clean     - remove generated workflows, temp outputs, pytest/ruff caches"
	@echo ""
	@echo "Codegen uses Google Gemini (default gemini-3.5-flash-lite). Set GEMINI_API_KEY in .env."
	@echo "Override port: make run PORT=5001"

install:
	$(PYTHON) -m pip install .

dev:
	$(PYTHON) -m pip install ".[dev]"

run:
	GEMINI_MODEL="$(GEMINI_MODEL)" $(PYTHON) main.py --port $(PORT)

debug:
	GEMINI_MODEL="$(GEMINI_MODEL)" $(PYTHON) main.py --debug --port $(PORT)

test:
	$(PYTHON) -m pytest --cov=workflowmvp --cov-fail-under=70

lint:
	$(PYTHON) -m ruff check .
	$(PYTHON) -m mypy workflowmvp

format:
	$(PYTHON) -m ruff format .

clean:
	$(PYTHON) -c "from main import cleanup_files; cleanup_files()"
	rm -rf .pytest_cache .ruff_cache
	find . -type d -name "__pycache__" -prune -exec rm -rf {} +
