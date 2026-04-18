# WorkflowMVP

[![ci](https://github.com/KMeltzer24/workflowMVP/actions/workflows/ci.yml/badge.svg)](https://github.com/KMeltzer24/workflowMVP/actions/workflows/ci.yml)
[![python](https://img.shields.io/badge/python-3.11%2B-blue)](#install)
[![license](https://img.shields.io/badge/license-MIT-green)](#license)

Turn natural-language descriptions — or screen-capture videos — into runnable Python workflows.

WorkflowMVP uses an online LLM (Gemini, Groq, or OpenRouter) to parse descriptions and generate executable Python, backed by a built-in tool registry covering HTTP requests, AI text generation, stock prices, file I/O, email, CSV/JSON, SQLite, compression, and more. Everything runs in a sandboxed directory with live output streamed to the browser.

---

## Quick start

```bash
git clone https://github.com/KMeltzer24/workflowMVP.git
cd workflowMVP
python3.11 -m venv .venv   # optional; use any Python 3.11+
source .venv/bin/activate  # optional
pip install -r requirements.txt
cp .env.example .env       # add your API key
make run                   # open http://localhost:5050
```

On macOS, `/usr/bin/python3` is often 3.9; use Homebrew `python3.11` (or similar) to create the venv so it matches the **3.11+** requirement.

---

## Highlights

- Text descriptions or screen-recording videos → executable Python.
- 30 built-in tools including `http_request`, `scrape_webpage`, **`discover_urls`** (sitemap + same-origin links, keyword-ranked), `generate_text`, `read_json` / `write_json`, `append_file`, `hash_file`, `get_current_time`, `read_pdf`, `render_template`, and `fetch_stock_price`.
- Browser UI with tabs, live streaming output, save/load workflows, and inline credential prompts.
- **Create** flow: edit parsed steps before *Generate Python code*; saving a step re-parses that line so action/parameters stay aligned.
- Code generation checks **Python syntax** before writing a script, retries once with a stricter completion instruction if needed, and the system prompt stresses **no fabricated facts** (fetch real pages/feeds/prices first; `generate_text` summarizes supplied content).
- Credentials stay in your browser's `sessionStorage` or `.env` — never written to disk server-side.
- Hybrid parsing: rule-based first, AI assist only when confidence is low.
- Tool safety profile: sandboxed file paths and blocked dangerous shell commands by default.
- Pytest suite + GitHub Actions CI (ruff + pytest on Python 3.11).

## Install

Requires Python 3.11+.

```bash
git clone https://github.com/KMeltzer24/workflowMVP.git
cd workflowMVP
python3.11 -m venv .venv && source .venv/bin/activate   # recommended
pip install -r requirements.txt
cp .env.example .env
```

Set your LLM provider credentials in `.env`:

```
LLM_PROVIDER=gemini          # or groq, openrouter
GEMINI_API_KEY=your_key_here
```

Video parsing always requires `GEMINI_API_KEY` even if another provider is used for code generation.

## Run

```bash
make run                  # Gemini (default), port 5050
make run PROVIDER=2       # Groq
make run PROVIDER=3       # OpenRouter
make debug                # debug mode with auto-reload
```

Or directly:

```bash
python3 main.py
python3 main.py --port 5001
python3 main.py --debug
LLM_PROVIDER=groq python3 main.py
```

Open <http://localhost:5050>.


## Using the web UI

1. **Create** tab — write a numbered workflow or upload a screen-capture video, then click *Parse workflow*. Use *Edit* on any step to fix wording, URLs, emails, or tickers; *Save* re-runs the rule parser on that step.
2. **Generate Python code** — sends the current steps to the configured LLM, validates the returned script, and writes it under `data/generated_workflows/`. Each run is independent (no memory of prior generated files).
3. **Run** tab — executes the script in a sandboxed `data/temp_outputs/<run_id>/` directory. Output streams live. Artifacts persist until server shutdown or `/api/cleanup`.
4. **Examples** tab — seven ready-to-run workflows, including SMTP and notification demos.
5. **Tools** tab — browse every tool available to generated code.
6. **Settings** — enter Gemini/SMTP credentials for the browser session. Provider keys (Groq/OpenRouter) are set via `.env`.

For **event or schedule** steps on a public site, prefer a **direct program URL** in the step text when you have one. Otherwise generated code can use **`discover_urls`** (homepage + sitemap + on-page links) to pick a candidate page before **`scrape_webpage`** — it does not crawl arbitrary deep sites.

## Example workflow

```
1. Fetch the current S&P 500 price
2. Write a short poem about the price
3. Email the poem to me@example.com
```

Paste into the Create tab → *Parse workflow* → *Generate Python code* → *Run*.

## HTTP API

Routes are implemented in `main.py`; the web UI calls them from `web/static/js/app.js`. POST bodies may include a `credentials` object — those values are merged into the workflow subprocess environment and are not written to disk.

## Development

```bash
pip install -r requirements-dev.txt
pytest          # run all tests (use `python -m pytest` if `pytest` is not on PATH)
ruff check .    # lint (`python -m ruff check .` if needed)
make clean      # wipe generated scripts, temp outputs, and pytest/ruff caches
```

### Project layout

```
workflowMVP/
├── main.py                  # Flask app, subprocess runner, SSE streaming, cleanup
├── workflowmvp/
│   ├── parser.py            # rule-based text → structured steps
│   ├── agent.py             # LLM-backed code generator (multi-provider)
│   ├── tools.py             # ToolRegistry: 30 tools
│   └── video_to_workflow.py # frame sampling + Gemini vision analysis
├── web/
│   ├── templates/index.html
│   └── static/
│       ├── css/style.css
│       └── js/app.js
├── tests/
├── .github/workflows/ci.yml
├── pyproject.toml
├── Makefile
└── .env.example
```

### Adding a tool

```python
from workflowmvp.tools import Tool, ToolRegistry

def my_tool(param: str) -> dict:
    return {"success": True, "result": param.upper()}

registry = ToolRegistry()
registry.register_tool(Tool(
    name="shout",
    description="Uppercase a string.",
    function=my_tool,
    parameters={"param": "String to uppercase"},
))
```

## Troubleshooting

- **"Missing provider API key"** — set `LLM_PROVIDER` and the matching key in `.env` (`GEMINI_API_KEY`, `GROQ_API_KEY`, or `OPENROUTER_API_KEY`).
- **Email fails with "Missing SMTP credentials"** — open *Settings* and fill in `EMAIL_USER`, `EMAIL_PASSWORD`, and `EMAIL_FROM`. Works with any SMTP provider: Gmail (needs an [App Password](https://myaccount.google.com/apppasswords)), Outlook (`smtp-mail.outlook.com:587`), Yahoo (`smtp.mail.yahoo.com:587`), or any custom SMTP server — set `SMTP_SERVER` and `SMTP_PORT` in `.env` accordingly.
- **Video parse returns no steps** — re-record with slower, clearer interactions or increase `max_frames` in `workflowmvp/video_to_workflow.py`.
- **"Workflow file not found"** — the file was likely removed by a previous cleanup. Regenerate the workflow and run again.

## License

MIT

## Acknowledgements

- [Google Gemini](https://ai.google.dev/) for text and vision generation.
- [Groq](https://groq.com/) and [OpenRouter](https://openrouter.ai/) for alternative LLM providers.
- [yfinance](https://github.com/ranaroussi/yfinance) for stock and index price data.
- [Flask](https://flask.palletsprojects.com/) for the web server.
- [OpenCV](https://opencv.org/) for video frame sampling.
