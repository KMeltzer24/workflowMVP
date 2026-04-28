"""Built-in example workflows + per-action credential requirements."""

from __future__ import annotations

import os
from collections.abc import Iterable
from typing import Any, Callable, Dict, List

# Mapping of workflow actions -> env var keys they require. Used by
# /api/check-requirements to tell the UI which creds are missing before a run.
#
# Values can be either:
#   - a static list of env var names, or
#   - a callable ``(effective_env: Mapping[str, str]) -> List[str]`` for
#     contextual resolution when needed later.
ActionRequirement = List[str] | Callable[[Dict[str, str]], List[str]]


def _generate_text_requirements(_effective: Dict[str, str]) -> List[str]:
    """``generate_text`` uses :class:`~workflowmvp.llm.LLMClient` (Gemini only)."""
    return ["GEMINI_API_KEY"]


ACTION_REQUIREMENTS: Dict[str, ActionRequirement] = {
    "send_email": [
        "EMAIL_USER",
        "EMAIL_PASSWORD",
        "EMAIL_FROM",
    ],
    "generate_text": _generate_text_requirements,
    "generate_haiku": _generate_text_requirements,
    "generate_poem": _generate_text_requirements,
}


def resolve_requirement(
    requirement: ActionRequirement, effective: Dict[str, str]
) -> List[str]:
    if callable(requirement):
        return list(requirement(effective))
    return list(requirement)


def missing_requirements(
    steps: Iterable[Dict[str, Any]], creds: Dict[str, str]
) -> List[str]:
    """Return env var keys the run will need but which aren't yet set."""
    effective: Dict[str, str] = {**os.environ, **creds}
    needed: set[str] = set()
    for step in steps:
        action = step.get("action") if isinstance(step, dict) else None
        requirement = ACTION_REQUIREMENTS.get(action or "")
        if requirement is None:
            continue
        for key in resolve_requirement(requirement, effective):
            needed.add(key)
    return sorted(key for key in needed if not effective.get(key))


def list_examples() -> List[Dict[str, Any]]:
    """Self-contained example workflows that run end-to-end inside data/temp_outputs.

    Each example seeds any inputs it needs so it can run offline without
    prior state. Outputs land in the current working dir, which the runner
    sets to the per-run subdir of ``data/temp_outputs`` and keeps until
    server shutdown cleanup.
    """
    return [
        {
            "name": "Bitcoin Price Snapshot",
            "description": "Download the current Bitcoin price, save it to a file, and send a desktop notification.",
            "workflow": (
                "1. Download https://api.coinbase.com/v2/prices/BTC-USD/spot\n"
                "2. Write the Bitcoin USD price from the JSON response to file \"bitcoin_price.txt\"\n"
                "3. Send notification with title \"Bitcoin\" and message \"Price saved\""
            ),
            "requires_credentials": [],
        },
        {
            "name": "CSV Data Processing Pipeline",
            "description": "Seed a sample users.csv, read it, and write a report with the average age.",
            "workflow": (
                "1. Write the text \"name,age\\nAlice,30\\nBob,25\\nCarol,41\\nDan,29\" to file \"users.csv\"\n"
                "2. Read the CSV file \"users.csv\"\n"
                "3. Write a summary containing the average age of users to file \"report.txt\"\n"
                "4. Send notification with title \"Pipeline\" and message \"Report generated\""
            ),
            "requires_credentials": [],
        },
        {
            "name": "File Backup",
            "description": "Create a few sample files and compress them into a zip archive.",
            "workflow": (
                "1. Create a directory called \"sandbox\"\n"
                "2. Write the text \"hello\" to file \"sandbox/note.txt\"\n"
                "3. Write the text \"workflow\" to file \"sandbox/readme.txt\"\n"
                "4. List files in the \"sandbox\" directory\n"
                "5. Compress files \"sandbox/note.txt\" and \"sandbox/readme.txt\" to \"backup.zip\"\n"
                "6. Send notification with title \"Backup\" and message \"Archive created\""
            ),
            "requires_credentials": [],
        },
        {
            "name": "Bitcoin Price Email (requires SMTP)",
            "description": "Download the Bitcoin price and email it. Will prompt for SMTP credentials if not configured.",
            "workflow": (
                "1. Download https://api.coinbase.com/v2/prices/BTC-USD/spot\n"
                "2. Process the JSON response to extract the USD price\n"
                "3. Send email to admin@example.com with subject \"Bitcoin Price\" and body including the price"
            ),
            "requires_credentials": ACTION_REQUIREMENTS["send_email"],
        },
        {
            "name": "S&P 500 Haiku",
            "description": (
                "Fetch the current S&P 500 price, write a haiku with AI, save it to a file, "
                "and email that file's contents."
            ),
            "workflow": (
                "1. Fetch the current price of the S&P 500 (ticker ^GSPC)\n"
                "2. Write a haiku about the S&P 500 price\n"
                "3. Write the haiku to file \"sp500_haiku.txt\"\n"
                "4. Send email to kevinmeltzer1@gmail.com with subject \"S&P 500 Haiku\" "
                "and body set to the full contents of file \"sp500_haiku.txt\""
            ),
            "requires_credentials": ACTION_REQUIREMENTS["send_email"],
        },
        {
            "name": "SPY 5-Day Change",
            "description": "Compare SPY's current price to 5 trading days ago and save the result.",
            "workflow": (
                "1. Fetch SPY price history for the past 5 days\n"
                "2. Calculate the dollar and percentage change over the 5 days\n"
                "3. Write a summary of the change to file \"spy_change.txt\"\n"
                "4. Send notification with title \"SPY\" and message \"Change report saved\""
            ),
            "requires_credentials": [],
        },
        {
            "name": "Webpage Summariser",
            "description": "Scrape any public webpage, summarise the content with AI, and save the summary.",
            "workflow": (
                "1. Scrape the webpage https://en.wikipedia.org/wiki/Python_(programming_language)\n"
                "2. Write a concise 3-sentence summary of the page content\n"
                "3. Write the summary to file \"summary.txt\"\n"
                "4. Send notification with title \"Summary\" and message \"Done\""
            ),
            "requires_credentials": [],
        },
        {
            "name": "SQLite mini database",
            "description": "Create a SQLite file, insert two rows, COUNT(*), save the tally.",
            "workflow": (
                "1. Create a directory \"sqlite_demo\"\n"
                "2. sqlite_query on database \"sqlite_demo/demo.db\" with query "
                "\"CREATE TABLE IF NOT EXISTS pets (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT)\"\n"
                "3. sqlite_insert into database \"sqlite_demo/demo.db\" table pets with data "
                "[{\"name\": \"Ada\"}, {\"name\": \"Grace\"}]\n"
                "4. sqlite_query database \"sqlite_demo/demo.db\" with query \"SELECT COUNT(*) AS n FROM pets\"\n"
                "5. Write a one-line summary of the query result to \"sqlite_demo/pet_count.txt\"\n"
                "6. Send notification with title \"SQLite\" and message \"Pet tally saved\""
            ),
            "requires_credentials": [],
        },
        {
            "name": "HTTP HEAD probe",
            "description": "HEAD a small public endpoint and append status + ISO time to a log file.",
            "workflow": (
                "1. get_current_time in timezone UTC and note the ISO timestamp\n"
                "2. http_request URL \"https://httpbin.org/status/200\" with method HEAD\n"
                "3. Append a line containing the ISO timestamp and HTTP status_code to \"http_probe.log\"\n"
                "4. Send notification with title \"Probe\" and message \"HTTP probe logged\""
            ),
            "requires_credentials": [],
        },
        {
            "name": "Discover + scrape (python.org)",
            "description": "Rank URLs on python.org then scrape the homepage into a snippet file.",
            "workflow": (
                "1. discover_urls with start_url \"https://www.python.org/\", max_results 12, "
                "keywords docs download\n"
                "2. Write the top URLs (url + score lines) to \"python_org_discovery.txt\"\n"
                "3. scrape_webpage URL \"https://www.python.org/\" and save the scraped text excerpt "
                "(first chunk) to \"python_org_home.txt\"\n"
                "4. Send notification with title \"Discover\" and message \"Discovery scratch files saved\""
            ),
            "requires_credentials": [],
        },
    ]
