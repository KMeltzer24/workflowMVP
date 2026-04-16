.PHONY: help install dev run debug test lint format clean

PORT ?= 5050

help:
	@echo "WorkflowMVP make targets"
	@echo "  make install   - install runtime dependencies"
	@echo "  make dev       - install dev dependencies (pytest, ruff)"
	@echo "  make run       - start the web UI in production mode (PORT=$(PORT))"
	@echo "  make debug     - start the web UI with Flask debug mode (PORT=$(PORT))"
	@echo "  make test      - run the test suite"
	@echo "  make lint      - run ruff lint"
	@echo "  make format    - run ruff format"
	@echo "  make clean     - remove generated workflows, temp outputs, caches"
	@echo ""
	@echo "Override the port with: make run PORT=5001"

install:
	python3 -m pip install -r requirements.txt

dev:
	python3 -m pip install -r requirements-dev.txt

run:
	python3 main.py --port $(PORT)

debug:
	python3 main.py --debug --port $(PORT)

test:
	pytest

lint:
	ruff check .

format:
	ruff format .

clean:
	python3 cleanup.py
	rm -rf .pytest_cache .ruff_cache
	find . -type d -name "__pycache__" -prune -exec rm -rf {} +
