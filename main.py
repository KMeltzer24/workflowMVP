"""
WorkflowMVP - Flask web interface for AI-powered workflow creation.

Handles:
    - Parsing workflow text (and optionally screen-capture video) into structured steps.
    - Generating executable Python scripts via Gemini.
    - Running those scripts in a sandboxed per-run output directory with credentials
      injected via environment variables (never written to disk).
    - Streaming live stdout/stderr back to the browser over Server-Sent Events.
    - Cleaning up generated files and outputs on server shutdown.
"""

from __future__ import annotations

import argparse
import ast
import json
import logging
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import uuid
import warnings
from collections.abc import Iterable
from typing import Any, Callable, Dict, List, Optional

# Suppress noisy gRPC / ALTS warnings emitted by some Google client stacks on import.
os.environ.setdefault("GRPC_VERBOSITY", "ERROR")
os.environ.setdefault("GRPC_TRACE", "")
os.environ.setdefault("GLOG_minloglevel", "2")

# Silence the verbose FutureWarnings from google-* libraries on Python 3.9.
# Re-enable with `python3 -W default main.py` if you want to see them.
warnings.filterwarnings("ignore", category=FutureWarning)
warnings.filterwarnings("ignore", category=DeprecationWarning)
warnings.filterwarnings(
    "ignore",
    message=r"urllib3 v2 only supports OpenSSL 1\.1\.1\+.*LibreSSL.*",
)

from dotenv import load_dotenv  # noqa: E402
from flask import (  # noqa: E402
    Flask,
    Response,
    jsonify,
    render_template,
    request,
    stream_with_context,
)

from workflowmvp.agent import WorkflowAgent  # noqa: E402
from workflowmvp.parser import WorkflowParser, WorkflowStep  # noqa: E402
from workflowmvp.tools import ToolRegistry  # noqa: E402

load_dotenv()

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
GENERATED_DIR = os.path.join(PROJECT_ROOT, "data", "generated_workflows")
TEMP_OUTPUTS_DIR = os.path.join(PROJECT_ROOT, "data", "temp_outputs")


def cleanup_files(verbose: bool = True) -> int:
    """Wipe generated workflow scripts and everything under data/temp_outputs/."""
    import glob

    count = 0
    for file_path in glob.glob(os.path.join(GENERATED_DIR, "*.py")):
        try:
            os.unlink(file_path)
            count += 1
            if verbose:
                print(f"  deleted: {file_path}")
        except OSError as exc:
            if verbose:
                print(f"  could not delete {file_path}: {exc}")

    if os.path.isdir(TEMP_OUTPUTS_DIR):
        for entry in os.listdir(TEMP_OUTPUTS_DIR):
            path = os.path.join(TEMP_OUTPUTS_DIR, entry)
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

# Mapping of workflow actions -> env var keys they require. Used by
# /api/check-requirements to tell the UI which creds are missing before a run.
#
# Values can be either:
#   - a static list of env var names, or
#   - a callable `(effective_env: Mapping[str, str]) -> List[str]` for
#     provider-aware resolution (e.g. generate_text picks its key based on
#     LLM_PROVIDER).
ActionRequirement = List[str] | Callable[[Dict[str, str]], List[str]]


def _generate_text_requirements(effective: Dict[str, str]) -> List[str]:
    """Which key `generate_text` needs depends on the configured LLM_PROVIDER."""
    provider = (effective.get("LLM_PROVIDER") or "gemini").strip().lower()
    if provider == "groq":
        return ["GROQ_API_KEY"]
    if provider == "openrouter":
        return ["OPENROUTER_API_KEY"]
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

# Allow-list of credential keys the web layer will inject into subprocess env.
ALLOWED_CRED_KEYS = {
    "LLM_PROVIDER",
    "LLM_MODEL",
    "GEMINI_API_KEY",
    "GROQ_API_KEY",
    "OPENROUTER_API_KEY",
    "GROQ_MODEL",
    "OPENROUTER_MODEL",
    "EMAIL_USER",
    "EMAIL_PASSWORD",
    "EMAIL_FROM",
    "SMTP_SERVER",
    "SMTP_PORT",
}

app = Flask(__name__, template_folder="web/templates", static_folder="web/static")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _is_debug() -> bool:
    return "--debug" in sys.argv


def _sanitize_credentials(raw: Optional[Dict[str, Any]]) -> Dict[str, str]:
    """Keep only allow-listed credential keys with non-empty string values."""
    if not raw or not isinstance(raw, dict):
        return {}
    out: Dict[str, str] = {}
    for key, value in raw.items():
        if key not in ALLOWED_CRED_KEYS:
            continue
        if value is None:
            continue
        text = str(value).strip()
        if text:
            out[key] = text
    return out


def _resolve_llm_provider(creds: Dict[str, str]) -> str:
    provider = (creds.get("LLM_PROVIDER") or os.getenv("LLM_PROVIDER") or "gemini").strip().lower()
    return provider if provider in {"gemini", "groq", "openrouter"} else "gemini"


def _resolve_llm_model(provider: str, creds: Dict[str, str]) -> Optional[str]:
    if creds.get("LLM_MODEL"):
        return creds["LLM_MODEL"]
    if provider == "gemini":
        return creds.get("GEMINI_MODEL") or os.getenv("GEMINI_MODEL")
    if provider == "groq":
        return creds.get("GROQ_MODEL") or os.getenv("GROQ_MODEL")
    return creds.get("OPENROUTER_MODEL") or os.getenv("OPENROUTER_MODEL")


def _resolve_api_key(provider: str, creds: Dict[str, str]) -> Optional[str]:
    """Resolve provider-specific API key (request creds take precedence)."""
    if provider == "groq":
        return creds.get("GROQ_API_KEY") or os.getenv("GROQ_API_KEY")
    if provider == "openrouter":
        return creds.get("OPENROUTER_API_KEY") or os.getenv("OPENROUTER_API_KEY")
    return creds.get("GEMINI_API_KEY") or os.getenv("GEMINI_API_KEY")


def _missing_llm_key(provider: str) -> str:
    return {
        "gemini": "GEMINI_API_KEY",
        "groq": "GROQ_API_KEY",
        "openrouter": "OPENROUTER_API_KEY",
    }.get(provider, "GEMINI_API_KEY")


def _build_run_env(creds: Dict[str, str]) -> Dict[str, str]:
    """Build a subprocess env: parent env + PYTHONPATH + request creds."""
    env = os.environ.copy()
    existing_path = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = (
        PROJECT_ROOT + (os.pathsep + existing_path if existing_path else "")
    )
    env.update(creds)
    # Hide httpx / Gemini SDK INFO lines from streamed workflow logs (set to 0 to debug).
    env.setdefault("WORKFLOW_QUIET_LOGGERS", "1")
    return env


def _ensure_run_dir(run_id: str) -> str:
    run_dir = os.path.join(TEMP_OUTPUTS_DIR, run_id)
    os.makedirs(run_dir, exist_ok=True)
    return run_dir


# POSIX resource caps applied to generated workflow subprocesses. Prevents a
# runaway script from exhausting host CPU/memory/disk. Bypass by setting
# WORKFLOW_DISABLE_RLIMIT=1 in the env (useful for long-running LLM calls).
_RLIMIT_CPU_SECONDS = int(os.getenv("WORKFLOW_RLIMIT_CPU", "120"))
_RLIMIT_AS_BYTES = int(os.getenv("WORKFLOW_RLIMIT_AS_MB", "1024")) * 1024 * 1024
_RLIMIT_FSIZE_BYTES = int(os.getenv("WORKFLOW_RLIMIT_FSIZE_MB", "100")) * 1024 * 1024


def _apply_workflow_rlimits() -> None:
    """preexec_fn for workflow subprocesses: cap CPU, address space, file size.

    POSIX only. On Windows (or when WORKFLOW_DISABLE_RLIMIT=1) this is a no-op.
    """
    if os.getenv("WORKFLOW_DISABLE_RLIMIT") == "1":
        return
    try:
        import resource  # POSIX-only
    except ImportError:
        return
    try:
        resource.setrlimit(resource.RLIMIT_CPU, (_RLIMIT_CPU_SECONDS, _RLIMIT_CPU_SECONDS))
    except (ValueError, OSError):
        pass
    try:
        resource.setrlimit(resource.RLIMIT_AS, (_RLIMIT_AS_BYTES, _RLIMIT_AS_BYTES))
    except (ValueError, OSError):
        pass
    try:
        resource.setrlimit(resource.RLIMIT_FSIZE, (_RLIMIT_FSIZE_BYTES, _RLIMIT_FSIZE_BYTES))
    except (ValueError, OSError):
        pass
    try:
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    except (ValueError, OSError):
        pass


def _workflow_popen_kwargs() -> Dict[str, Any]:
    """Extra kwargs for Popen/run that apply POSIX resource caps where available."""
    if sys.platform == "win32":
        return {}
    return {"preexec_fn": _apply_workflow_rlimits}


def _resolve_requirement(
    requirement: ActionRequirement, effective: Dict[str, str]
) -> List[str]:
    if callable(requirement):
        return list(requirement(effective))
    return list(requirement)


def _missing_requirements(
    steps: Iterable[Dict[str, Any]], creds: Dict[str, str]
) -> List[str]:
    """Return env var keys that a run will need but which are not yet provided."""
    effective: Dict[str, str] = {**os.environ, **creds}
    needed: set[str] = set()
    for step in steps:
        action = step.get("action") if isinstance(step, dict) else None
        requirement = ACTION_REQUIREMENTS.get(action or "")
        if requirement is None:
            continue
        for key in _resolve_requirement(requirement, effective):
            needed.add(key)
    return sorted(key for key in needed if not effective.get(key))


def _examples() -> List[Dict[str, str]]:
    """Self-contained example workflows that run end-to-end inside data/temp_outputs.

    Each example seeds any inputs it needs so it can run offline without prior
    state. Outputs land in the current working dir, which main.py sets to the
    per-run subdir of data/temp_outputs and keeps until server shutdown cleanup.
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
    ]


# ---------------------------------------------------------------------------
# Shutdown hooks
# ---------------------------------------------------------------------------


def _cleanup_on_exit() -> None:
    debug_mode = _is_debug()
    if debug_mode:
        print("\nCleaning up temporary files...")
    cleanup_files(verbose=debug_mode)


def _signal_handler(signum, frame):  # type: ignore[no-untyped-def]
    if _is_debug():
        print(f"\nReceived signal {signum}, shutting down...")
    else:
        print()
    _cleanup_on_exit()
    sys.exit(0)


signal.signal(signal.SIGINT, _signal_handler)
signal.signal(signal.SIGTERM, _signal_handler)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/tools")
def get_tools():
    registry = ToolRegistry()
    return jsonify(
        [
            {
                "name": tool.name,
                "description": tool.description,
                "parameters": tool.parameters,
            }
            for tool in registry.list_tools()
        ]
    )


@app.route("/api/examples")
def get_examples():
    return jsonify(_examples())


@app.route("/api/parse-workflow", methods=["POST"])
def parse_workflow():
    try:
        payload = request.get_json(silent=True) or {}
        workflow_text = payload.get("workflow_text", "")
        creds = _sanitize_credentials(payload.get("credentials"))
        provider = _resolve_llm_provider(creds)
        model = _resolve_llm_model(provider, creds)
        api_key = _resolve_api_key(provider, creds)
        parser = WorkflowParser()
        steps = parser.parse_workflow(workflow_text)
        confidence = parser.assess_parse_confidence(steps)

        ai_assisted = False
        ai_assist_error: Optional[str] = None
        if api_key and confidence.get("needs_ai_assist"):
            try:
                ai_agent = WorkflowAgent(api_key=api_key, provider=provider, model=model)
                improved = ai_agent.improve_parsed_steps(workflow_text, steps)
                if improved:
                    steps = improved
                    ai_assisted = True
                    confidence = parser.assess_parse_confidence(steps)
            except Exception as exc:  # pragma: no cover - best effort enhancement
                ai_assist_error = str(exc)

        response: Dict[str, Any] = {
            "success": True,
            "steps": [_step_to_dict(s) for s in steps],
            "parse_confidence": confidence,
            "ai_assisted": ai_assisted,
        }
        if ai_assist_error and _is_debug():
            response["ai_assist_error"] = ai_assist_error
        return jsonify(response)
    except Exception as exc:  # pragma: no cover - defensive
        return jsonify({"success": False, "error": str(exc)})


@app.route("/api/parse-single-step", methods=["POST"])
def parse_single_step():
    """Parse a single edited step description into action/parameters."""
    try:
        payload = request.get_json(silent=True) or {}
        description = (payload.get("description") or "").strip()
        if not description:
            return jsonify({"success": False, "error": "No description provided"})

        parser = WorkflowParser()
        action, parameters = parser._extract_action_and_params(description)
        return jsonify(
            {
                "success": True,
                "action": action,
                "parameters": parameters,
            }
        )
    except Exception as exc:  # pragma: no cover - defensive
        return jsonify({"success": False, "error": str(exc)})


@app.route("/api/parse-video", methods=["POST"])
def parse_video():
    """Extract frames from an uploaded video and infer a workflow."""
    debug_mode = _is_debug()
    video_path: Optional[str] = None
    temp_dir: Optional[str] = None
    try:
        if "video" not in request.files:
            return jsonify({"success": False, "error": "No video file provided"})
        video_file = request.files["video"]
        if not video_file.filename:
            return jsonify({"success": False, "error": "No video file selected"})

        creds = _sanitize_credentials(
            _creds_from_form_or_json(request.form.get("credentials"))
        )
        provider = _resolve_llm_provider(creds)
        if provider != "gemini":
            return jsonify(
                {
                    "success": False,
                    "error": "Video parsing currently supports provider=gemini only.",
                    "missing_requirements": ["GEMINI_API_KEY"],
                }
            )
        api_key = _resolve_api_key("gemini", creds)
        if not api_key:
            return jsonify(
                {
                    "success": False,
                    "error": "Missing GEMINI_API_KEY. Add it in Settings or .env.",
                    "missing_requirements": ["GEMINI_API_KEY"],
                }
            )

        with tempfile.NamedTemporaryFile(delete=False, suffix=".mp4") as tmp_file:
            video_file.save(tmp_file.name)
            video_path = tmp_file.name

        from workflowmvp.video_to_workflow import (
            infer_workflow_from_frames,
            sample_frames_intelligent,
        )

        frames, temp_dir = sample_frames_intelligent(video_path, max_frames=15)
        if not frames:
            return jsonify(
                {"success": False, "error": "No frames could be extracted from the video"}
            )
        workflow_text = infer_workflow_from_frames(frames, api_key)
        if not workflow_text or len(workflow_text.strip()) < 10:
            return jsonify(
                {"success": False, "error": "AI analysis produced no meaningful workflow"}
            )

        parser = WorkflowParser()
        steps = parser.parse_workflow(workflow_text)
        confidence = parser.assess_parse_confidence(steps)
        return jsonify(
            {
                "success": True,
                "steps": [_step_to_dict(s) for s in steps],
                "workflow_text": workflow_text,
                "parse_confidence": confidence,
                "ai_assisted": False,
            }
        )
    except Exception as exc:
        if debug_mode:
            logging.exception("parse_video failed")
        return jsonify({"success": False, "error": str(exc)})
    finally:
        if video_path and os.path.exists(video_path):
            try:
                os.unlink(video_path)
            except OSError:
                pass
        if temp_dir and os.path.isdir(temp_dir):
            try:
                shutil.rmtree(temp_dir)
            except OSError:
                pass


@app.route("/api/generate-workflow", methods=["POST"])
def generate_workflow():
    try:
        payload = request.get_json(silent=True) or {}
        steps_data = payload.get("steps", [])
        workflow_name = _safe_name(payload.get("name", "generated_workflow"))
        creds = _sanitize_credentials(payload.get("credentials"))
        provider = _resolve_llm_provider(creds)
        model = _resolve_llm_model(provider, creds)

        api_key = _resolve_api_key(provider, creds)
        if not api_key:
            missing_key = _missing_llm_key(provider)
            return jsonify(
                {
                    "success": False,
                    "error": f"Missing {missing_key}. Add it in Settings or .env.",
                    "missing_requirements": [missing_key],
                }
            )

        steps = [
            WorkflowStep(
                step_id=step["step_id"],
                description=step["description"],
                action=step["action"],
                parameters=step["parameters"],
                dependencies=step["dependencies"],
            )
            for step in steps_data
        ]

        os.makedirs(GENERATED_DIR, exist_ok=True)
        timestamp = int(time.time())
        output_path = os.path.join(
            GENERATED_DIR, f"{workflow_name}_{timestamp}.py"
        )
        agent = WorkflowAgent(api_key=api_key, provider=provider, model=model)
        agent.generate_workflow_code(steps, output_path)

        # Return path relative to project root so the UI can treat it as opaque.
        return jsonify(
            {
                "success": True,
                "output_path": os.path.relpath(output_path, PROJECT_ROOT),
                "message": "Workflow generated successfully",
            }
        )
    except Exception as exc:
        return jsonify({"success": False, "error": str(exc)})


@app.route("/api/check-requirements", methods=["POST"])
def check_requirements():
    """Return which credential env vars a parsed workflow still needs."""
    try:
        payload = request.get_json(silent=True) or {}
        steps = payload.get("steps", [])
        creds = _sanitize_credentials(payload.get("credentials"))
        missing = _missing_requirements(steps, creds)
        return jsonify({"success": True, "missing": missing})
    except Exception as exc:
        return jsonify({"success": False, "error": str(exc)})


@app.route("/api/run-workflow", methods=["POST"])
def run_workflow():
    """Run a generated workflow (blocking) and return stdout/stderr."""
    payload = request.get_json(silent=True) or {}
    workflow_path = payload.get("workflow_path", "")
    creds = _sanitize_credentials(payload.get("credentials"))

    abs_path = _resolve_workflow_path(workflow_path)
    if not abs_path:
        return jsonify({"success": False, "error": "Workflow file not found"})

    run_id = uuid.uuid4().hex[:12]
    run_dir = _ensure_run_dir(run_id)
    env = _build_run_env(creds)
    env["WORKFLOW_RUN_ID"] = run_id
    env["WORKFLOW_OUTPUT_DIR"] = run_dir

    try:
        result = subprocess.run(
            [sys.executable, abs_path],
            cwd=run_dir,
            env=env,
            capture_output=True,
            text=True,
            timeout=120,
            **_workflow_popen_kwargs(),
        )
        return jsonify(
            {
                "success": result.returncode == 0,
                "stdout": result.stdout,
                "stderr": result.stderr,
                "returncode": result.returncode,
                "run_id": run_id,
            }
        )
    except subprocess.TimeoutExpired:
        return jsonify({"success": False, "error": "Workflow timed out"})
    except Exception as exc:
        return jsonify({"success": False, "error": str(exc)})


@app.route("/api/run-workflow/stream", methods=["POST"])
def run_workflow_stream():
    """Run a generated workflow and stream stdout/stderr via Server-Sent Events."""
    payload = request.get_json(silent=True) or {}
    workflow_path = payload.get("workflow_path", "")
    creds = _sanitize_credentials(payload.get("credentials"))

    abs_path = _resolve_workflow_path(workflow_path)
    if not abs_path:
        return _sse_error("Workflow file not found")

    run_id = uuid.uuid4().hex[:12]
    run_dir = _ensure_run_dir(run_id)
    env = _build_run_env(creds)
    env["WORKFLOW_RUN_ID"] = run_id
    env["WORKFLOW_OUTPUT_DIR"] = run_dir
    env["PYTHONUNBUFFERED"] = "1"

    def generate() -> Iterable[bytes]:
        yield _sse("status", {"message": "starting", "run_id": run_id})
        proc = subprocess.Popen(  # noqa: S603
            [sys.executable, "-u", abs_path],
            cwd=run_dir,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            **_workflow_popen_kwargs(),
        )
        try:
            assert proc.stdout is not None
            for line in proc.stdout:
                yield _sse("log", {"line": line.rstrip("\n")})
            proc.wait(timeout=120)
            yield _sse(
                "done",
                {
                    "returncode": proc.returncode,
                    "success": proc.returncode == 0,
                    "run_id": run_id,
                },
            )
        except subprocess.TimeoutExpired:
            proc.kill()
            yield _sse("error", {"message": "Workflow timed out"})
        except Exception as exc:  # pragma: no cover - defensive
            yield _sse("error", {"message": str(exc)})

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


def _extract_tools_from_source(source: str) -> List[str]:
    """Walk the AST of `source` and return sorted unique get_tool('name') args.

    Picks up both `tools.get_tool("x")` and bare `get_tool("x")`. Only string
    literals are collected; dynamic names like `get_tool(var)` are ignored.
    """
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []
    names: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        is_get_tool = (
            isinstance(func, ast.Attribute) and func.attr == "get_tool"
        ) or (isinstance(func, ast.Name) and func.id == "get_tool")
        if not is_get_tool or not node.args:
            continue
        first = node.args[0]
        if isinstance(first, ast.Constant) and isinstance(first.value, str):
            names.add(first.value)
    return sorted(names)


def _extract_top_level_imports(source: str) -> List[str]:
    """Return sorted unique top-level imported module names from `source`."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []
    modules: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.Import):
            for alias in node.names:
                modules.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module.split(".")[0])
    return sorted(modules)


@app.route("/api/validate-workflow", methods=["POST"])
def validate_workflow():
    """Compile a generated workflow script and report tools/imports WITHOUT running it.

    Use-case: give the UI a 'Preview' option that shows what would run
    (which tools, which imports, whether the script even parses) before the
    user commits to spending API credits / executing side effects.
    """
    payload = request.get_json(silent=True) or {}
    workflow_path = payload.get("workflow_path", "")
    abs_path = _resolve_workflow_path(workflow_path)
    if not abs_path:
        return jsonify({"success": False, "error": "Workflow file not found"})
    try:
        with open(abs_path, encoding="utf-8") as f:
            source = f.read()
    except OSError as exc:
        return jsonify({"success": False, "error": f"Could not read file: {exc}"})

    syntax_ok = True
    syntax_error: Optional[str] = None
    try:
        compile(source, abs_path, "exec")
    except SyntaxError as exc:
        syntax_ok = False
        syntax_error = f"{exc.msg} (line {exc.lineno})"

    tools_used = _extract_tools_from_source(source)
    registry_tools = {tool.name for tool in ToolRegistry().list_tools()}
    unknown_tools = [name for name in tools_used if name not in registry_tools]

    return jsonify(
        {
            "success": syntax_ok and not unknown_tools,
            "syntax_ok": syntax_ok,
            "syntax_error": syntax_error,
            "tools_used": tools_used,
            "unknown_tools": unknown_tools,
            "imports": _extract_top_level_imports(source),
            "line_count": source.count("\n") + 1,
            "workflow_path": workflow_path,
        }
    )


@app.route("/api/cleanup", methods=["POST"])
def cleanup_files_api():
    try:
        count = cleanup_files(verbose=_is_debug())
        return jsonify(
            {"success": True, "message": f"Cleaned up {count} files", "files_cleaned": count}
        )
    except Exception as exc:
        return jsonify({"success": False, "error": str(exc)})


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------


def _step_to_dict(step: WorkflowStep) -> Dict[str, Any]:
    return {
        "step_id": step.step_id,
        "description": step.description,
        "action": step.action,
        "parameters": step.parameters,
        "dependencies": step.dependencies,
    }


def _safe_name(name: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_\-]", "_", name).strip("_")
    return cleaned or "generated_workflow"


def _resolve_workflow_path(raw: str) -> Optional[str]:
    """Resolve a workflow path and ensure it stays under data/generated_workflows."""
    if not raw:
        return None
    candidate = raw if os.path.isabs(raw) else os.path.join(PROJECT_ROOT, raw)
    candidate = os.path.abspath(candidate)
    if not candidate.startswith(GENERATED_DIR + os.sep) and candidate != GENERATED_DIR:
        return None
    if not os.path.exists(candidate):
        return None
    return candidate


def _creds_from_form_or_json(raw: Any) -> Dict[str, Any]:
    """Parse a credentials blob from either a JSON body field or a multipart form field."""
    if not raw:
        return {}
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
            return parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            return {}
    return {}


def _sse(event: str, data: Dict[str, Any]) -> bytes:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n".encode()


def _sse_error(message: str) -> Response:
    def gen() -> Iterable[bytes]:
        yield _sse("error", {"message": message})

    return Response(stream_with_context(gen()), mimetype="text/event-stream")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(description="WorkflowMVP - Web Interface")
    parser.add_argument(
        "--debug", action="store_true", help="Enable Flask debug mode (auto-reload)"
    )
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.getenv("PORT", "5050")),
        help="Port to bind (default: env PORT or 5050)",
    )
    parser.add_argument(
        "--host",
        default=os.getenv("HOST", "0.0.0.0"),
        help="Host interface to bind (default: env HOST or 0.0.0.0)",
    )
    args = parser.parse_args()

    os.makedirs(GENERATED_DIR, exist_ok=True)
    os.makedirs(TEMP_OUTPUTS_DIR, exist_ok=True)

    print("WorkflowMVP - Web Interface")
    print("Starting web server...")
    print(f"Open your browser to: http://localhost:{args.port}")
    print("Press Ctrl+C to stop.")
    if args.debug:
        print("Debug mode: ON (auto-reload enabled)")

    try:
        if args.debug:
            app.run(debug=True, host=args.host, port=args.port)
            return

        logging.getLogger("werkzeug").setLevel(logging.ERROR)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            app.run(debug=False, host=args.host, port=args.port)
    except OSError as exc:
        # Most commonly: port in use.
        print(f"Could not bind to {args.host}:{args.port}: {exc}.")
        sys.exit(1)


if __name__ == "__main__":
    main()
