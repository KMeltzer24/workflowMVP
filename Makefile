.PHONY: help install dev run debug test lint format clean

# Prefer project venv when present (Python 3.11+).
PYTHON := $(if $(wildcard .venv/bin/python),.venv/bin/python,python3)

PORT ?= 5050

help:
	@echo "WorkflowMVP make targets"
	@echo "  make install   - install runtime dependencies"
	@echo "  make dev       - install dev dependencies (pytest, ruff)"
	@echo "  make run       - start web UI (PORT=$(PORT))"
	@echo "  make debug     - start web UI with debug logs (PORT=$(PORT))"
	@echo "  make test      - run the test suite"
	@echo "  make lint      - run ruff lint"
	@echo "  make format    - run ruff format"
	@echo "  make clean     - remove generated workflows, temp outputs, pytest/ruff caches"
	@echo ""
	@echo "Codegen uses Google Gemini. Set GEMINI_API_KEY (and optionally GEMINI_MODEL) in .env."
	@echo "Override port: make run PORT=5001"

install:
	$(PYTHON) -m pip install -r requirements.txt

dev:
	$(PYTHON) -m pip install -r requirements-dev.txt

run:
	GEMINI_MODEL="$(GEMINI_MODEL)" $(PYTHON) main.py --port $(PORT)

debug:
	GEMINI_MODEL="$(GEMINI_MODEL)" $(PYTHON) main.py --debug --port $(PORT)

test:
	$(PYTHON) -m pytest

lint:
	$(PYTHON) -m ruff check .

format:
	$(PYTHON) -m ruff format .

clean:
	$(PYTHON) -c "from main import cleanup_files; cleanup_files()"
	rm -rf .pytest_cache .ruff_cache
	find . -type d -name "__pycache__" -prune -exec rm -rf {} +
