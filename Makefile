.PHONY: help install dev run debug test lint format clean

PORT ?= 5050
LLM_PROVIDER ?= gemini
LLM_MODEL ?=
# Simple shorthand:
#   PROVIDER=   -> gemini (default)
#   PROVIDER=2  -> groq
#   PROVIDER=3  -> openrouter
PROVIDER ?=

ifeq ($(PROVIDER),2)
LLM_PROVIDER := groq
endif
ifeq ($(PROVIDER),3)
LLM_PROVIDER := openrouter
endif

help:
	@echo "WorkflowMVP make targets"
	@echo "  make install   - install runtime dependencies"
	@echo "  make dev       - install dev dependencies (pytest, ruff)"
	@echo "  make run       - start web UI (PORT=$(PORT), LLM_PROVIDER=$(LLM_PROVIDER))"
	@echo "  make debug     - start web UI debug (PORT=$(PORT), LLM_PROVIDER=$(LLM_PROVIDER))"
	@echo "  make test      - run the test suite"
	@echo "  make lint      - run ruff lint"
	@echo "  make format    - run ruff format"
	@echo "  make clean     - remove generated workflows, temp outputs, caches"
	@echo ""
	@echo "Simple provider shorthand:"
	@echo "  make run                 # Gemini (default)"
	@echo "  make run PROVIDER=2      # Groq"
	@echo "  make run PROVIDER=3      # OpenRouter"
	@echo ""
	@echo "Override port/provider: make run PORT=5001 LLM_PROVIDER=groq"
	@echo "Optional model override: make run LLM_PROVIDER=openrouter LLM_MODEL=meta-llama/llama-3.1-70b-instruct"

install:
	python3 -m pip install -r requirements.txt

dev:
	python3 -m pip install -r requirements-dev.txt

run:
	LLM_PROVIDER=$(LLM_PROVIDER) LLM_MODEL="$(LLM_MODEL)" python3 main.py --port $(PORT)

debug:
	LLM_PROVIDER=$(LLM_PROVIDER) LLM_MODEL="$(LLM_MODEL)" python3 main.py --debug --port $(PORT)

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
