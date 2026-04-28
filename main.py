"""
WorkflowMVP - Flask web interface for AI-powered workflow creation.

Routes are intentionally thin — runtime concerns (subprocess sandboxing,
credential handling, examples, cleanup, AST-based validation) live in
``workflowmvp/services/`` so each piece can be tested in isolation.

This module owns:
    - The Flask ``app`` instance + 100 MB upload cap + 413 handler.
    - Signal/exit hooks that wipe generated artifacts.
    - The CLI entry point (``python main.py``).
"""

from __future__ import annotations

import argparse
import logging
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import uuid
import warnings
from queue import Empty, Queue
from threading import Thread
from typing import Any, Dict, Optional
from urllib.parse import urlparse

# Suppress noisy gRPC / ALTS warnings emitted by some Google client stacks
# when ``google_genai`` is imported transitively.
os.environ.setdefault("GRPC_VERBOSITY", "ERROR")
os.environ.setdefault("GRPC_TRACE", "")
os.environ.setdefault("GLOG_minloglevel", "2")

# Silence the FutureWarnings emitted by ``google-*`` libraries when running
# on older interpreters. Re-enable with ``python3 -W default main.py``.
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
from workflowmvp.cli import default_host, default_port, run_server  # noqa: E402
from workflowmvp.parser import WorkflowParser, WorkflowStep  # noqa: E402
from workflowmvp.services.cleanup import cleanup_files as _services_cleanup_files  # noqa: E402
from workflowmvp.services.credentials import (  # noqa: E402
    creds_from_form_or_json,
    missing_gemini_api_key_hint,
    resolve_gemini_api_key,
    resolve_gemini_model,
    sanitize_credentials,
)
from workflowmvp.services.examples import (  # noqa: E402
    list_examples,
    missing_requirements,
)
from workflowmvp.services.paths import (  # noqa: E402
    GENERATED_DIR,
    PROJECT_ROOT,
    TEMP_OUTPUTS_DIR,
)
from workflowmvp.services.runner import (  # noqa: E402
    build_run_env,
    encode_sse,
    ensure_run_dir,
    resolve_workflow_path,
    sse_error_response,
    workflow_popen_kwargs,
)
from workflowmvp.services.static_analysis import (  # noqa: E402
    extract_tools_from_source,
    extract_top_level_imports,
)
from workflowmvp.tools import ToolRegistry  # noqa: E402

load_dotenv()


# Re-export the cleanup function so existing call sites and tests keep
# working without having to follow the package split.
def cleanup_files(verbose: bool = True) -> int:
    return _services_cleanup_files(verbose=verbose)


app = Flask(__name__, template_folder="web/templates", static_folder="web/static")

# Cap upload size at 100 MB. Video parsing is the only large-payload
# endpoint and 100 MB comfortably fits a 30-second 1080p screen recording.
# Override with ``WORKFLOW_MAX_UPLOAD_MB`` for testing.
_MAX_UPLOAD_MB = max(1, int(os.getenv("WORKFLOW_MAX_UPLOAD_MB", "100")))
app.config["MAX_CONTENT_LENGTH"] = _MAX_UPLOAD_MB * 1024 * 1024

# Allowed video MIME prefixes / explicit types for ``/api/parse-video``.
# The upload UI restricts to ``video/*`` but a hostile client can claim
# anything, so we double-check on the server.
ALLOWED_VIDEO_MIME_PREFIXES = ("video/",)
ALLOWED_VIDEO_MIME_TYPES = {
    # Some browsers omit a precise type for ``.mp4`` uploads.
    "application/octet-stream",
}

# Keep the old blocking endpoint only for tests / legacy scripts.
# The UI uses SSE (`/api/run-workflow/stream`) exclusively.
ENABLE_BLOCKING_RUN_ENDPOINT = (
    os.getenv("WORKFLOW_ENABLE_BLOCKING_RUN_ENDPOINT", "0") == "1"
)


@app.errorhandler(413)
def _too_large(_err):  # pragma: no cover - exercised manually
    return (
        jsonify(
            {
                "success": False,
                "error": (
                    f"Upload exceeds the {_MAX_UPLOAD_MB} MB limit. "
                    "Trim the recording or raise WORKFLOW_MAX_UPLOAD_MB."
                ),
            }
        ),
        413,
    )


def _same_origin(url: str) -> bool:
    """True when `url` matches this request's scheme + host."""
    parsed = urlparse(url)
    host = request.host
    return parsed.scheme in {"http", "https"} and parsed.netloc == host


@app.before_request
def _enforce_same_origin_posts():
    """Best-effort CSRF mitigation for cookie-authenticated browser POSTs.

    We allow requests without Origin/Referer (CLI/tests), but if either header
    is present it must match this host.
    """
    if request.method != "POST":
        return None

    origin = (request.headers.get("Origin") or "").strip()
    referer = (request.headers.get("Referer") or "").strip()
    if origin and not _same_origin(origin):
        return (
            jsonify(
                {
                    "success": False,
                    "error": "Cross-origin POST blocked. Use same-origin requests.",
                }
            ),
            403,
        )
    if not origin and referer and not _same_origin(referer):
        return (
            jsonify(
                {
                    "success": False,
                    "error": "Cross-origin Referer blocked. Use same-origin requests.",
                }
            ),
            403,
        )
    return None


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------


def _is_debug() -> bool:
    return "--debug" in sys.argv


def _step_to_dict(step: WorkflowStep) -> Dict[str, Any]:
    return {
        "step_id": step.step_id,
        "description": step.description,
        "action": step.action,
        "parameters": step.parameters,
        "dependencies": step.dependencies,
    }


def _safe_name(name: str) -> str:
    import re

    cleaned = re.sub(r"[^A-Za-z0-9_\-]", "_", name).strip("_")
    return cleaned or "generated_workflow"


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
    return jsonify(list_examples())


@app.route("/api/parse-workflow", methods=["POST"])
def parse_workflow():
    try:
        payload = request.get_json(silent=True) or {}
        workflow_text = payload.get("workflow_text", "")
        creds = sanitize_credentials(payload.get("credentials"))
        api_key = resolve_gemini_api_key(creds)
        model = resolve_gemini_model(creds)
        parser = WorkflowParser()
        steps = parser.parse_workflow(workflow_text)
        confidence = parser.assess_parse_confidence(steps)

        ai_assisted = False
        ai_assist_error: Optional[str] = None
        if api_key and confidence.get("needs_ai_assist"):
            try:
                ai_agent = WorkflowAgent(api_key=api_key, model=model)
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

        mime = (video_file.mimetype or "").lower()
        if mime and not (
            mime.startswith(ALLOWED_VIDEO_MIME_PREFIXES)
            or mime in ALLOWED_VIDEO_MIME_TYPES
        ):
            return jsonify(
                {
                    "success": False,
                    "error": f"Unsupported file type: {mime!r}. Upload a video file.",
                }
            )

        creds = sanitize_credentials(
            creds_from_form_or_json(request.form.get("credentials"))
        )
        api_key = resolve_gemini_api_key(creds)
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
        creds = sanitize_credentials(payload.get("credentials"))
        api_key = resolve_gemini_api_key(creds)
        if not api_key:
            missing_key = missing_gemini_api_key_hint()
            return jsonify(
                {
                    "success": False,
                    "error": f"Missing {missing_key}. Add it in Settings or .env.",
                    "missing_requirements": [missing_key],
                }
            )

        model = resolve_gemini_model(creds)

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
        t_gen0 = time.monotonic()
        agent = WorkflowAgent(api_key=api_key, model=model)
        agent.generate_workflow_code(steps, output_path)
        generation_seconds = round(time.monotonic() - t_gen0, 3)

        return jsonify(
            {
                "success": True,
                "output_path": os.path.relpath(output_path, PROJECT_ROOT),
                "message": "Workflow generated successfully",
                "generation_seconds": generation_seconds,
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
        creds = sanitize_credentials(payload.get("credentials"))
        missing = missing_requirements(steps, creds)
        return jsonify({"success": True, "missing": missing})
    except Exception as exc:
        return jsonify({"success": False, "error": str(exc)})


@app.route("/api/run-workflow", methods=["POST"])
def run_workflow():
    """Run a generated workflow (blocking) and return stdout/stderr."""
    if not ENABLE_BLOCKING_RUN_ENDPOINT:
        return (
            jsonify(
                {
                    "success": False,
                    "error": "Blocking run endpoint is disabled. Use /api/run-workflow/stream.",
                }
            ),
            404,
        )

    payload = request.get_json(silent=True) or {}
    workflow_path = payload.get("workflow_path", "")
    creds = sanitize_credentials(payload.get("credentials"))

    abs_path = resolve_workflow_path(workflow_path)
    if not abs_path:
        return jsonify({"success": False, "error": "Workflow file not found"})

    run_id = uuid.uuid4().hex[:12]
    run_dir = ensure_run_dir(run_id)
    env = build_run_env(creds)
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
            **workflow_popen_kwargs(),
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
    creds = sanitize_credentials(payload.get("credentials"))

    abs_path = resolve_workflow_path(workflow_path)
    if not abs_path:
        return sse_error_response("Workflow file not found")

    run_id = uuid.uuid4().hex[:12]
    run_dir = ensure_run_dir(run_id)
    env = build_run_env(creds)
    env["WORKFLOW_RUN_ID"] = run_id
    env["WORKFLOW_OUTPUT_DIR"] = run_dir
    env["PYTHONUNBUFFERED"] = "1"

    def generate():
        yield encode_sse("status", {"message": "starting", "run_id": run_id})
        proc = subprocess.Popen(  # noqa: S603
            [sys.executable, "-u", abs_path],
            cwd=run_dir,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            **workflow_popen_kwargs(),
        )
        try:
            assert proc.stdout is not None
            line_queue: Queue[Optional[str]] = Queue()
            start = time.monotonic()
            timeout_seconds = 120.0

            def _read_stdout() -> None:
                try:
                    for line in proc.stdout:
                        line_queue.put(line)
                finally:
                    line_queue.put(None)

            reader = Thread(target=_read_stdout, daemon=True)
            reader.start()

            timed_out = False
            while True:
                if time.monotonic() - start > timeout_seconds:
                    timed_out = True
                    proc.kill()
                    yield encode_sse("error", {"message": "Workflow timed out"})
                    break
                try:
                    line = line_queue.get(timeout=0.25)
                except Empty:
                    continue
                if line is None:
                    break
                yield encode_sse("log", {"line": line.rstrip("\n")})

            if timed_out:
                return

            proc.wait(timeout=5)
            yield encode_sse(
                "done",
                {
                    "returncode": proc.returncode,
                    "success": proc.returncode == 0,
                    "run_id": run_id,
                },
            )
        except subprocess.TimeoutExpired:
            proc.kill()
            yield encode_sse("error", {"message": "Workflow timed out"})
        except Exception as exc:  # pragma: no cover - defensive
            yield encode_sse("error", {"message": str(exc)})

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@app.route("/api/validate-workflow", methods=["POST"])
def validate_workflow():
    """Compile a generated workflow script and report tools/imports WITHOUT running it.

    Used by the UI's "Preview" affordance to show what would run (which
    tools, which imports, whether the script even parses) before the user
    commits to spending API credits / executing side effects.
    """
    payload = request.get_json(silent=True) or {}
    workflow_path = payload.get("workflow_path", "")
    abs_path = resolve_workflow_path(workflow_path)
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

    tools_used = extract_tools_from_source(source)
    registry_tools = {tool.name for tool in ToolRegistry().list_tools()}
    unknown_tools = [name for name in tools_used if name not in registry_tools]

    return jsonify(
        {
            "success": syntax_ok and not unknown_tools,
            "syntax_ok": syntax_ok,
            "syntax_error": syntax_error,
            "tools_used": tools_used,
            "unknown_tools": unknown_tools,
            "imports": extract_top_level_imports(source),
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
        default=default_port(),
        help="Port to bind (default: env PORT or 5050)",
    )
    parser.add_argument(
        "--host",
        default=default_host(),
        help=(
            "Host interface to bind (default: env HOST or 127.0.0.1). "
            "Use 0.0.0.0 to expose on the LAN; the app runs LLM-generated "
            "Python so only do this on networks you trust."
        ),
    )
    args = parser.parse_args()

    os.makedirs(GENERATED_DIR, exist_ok=True)
    os.makedirs(TEMP_OUTPUTS_DIR, exist_ok=True)

    run_server(app, host=args.host, port=args.port, debug=args.debug)


if __name__ == "__main__":
    main()
