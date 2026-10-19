from __future__ import annotations

import subprocess
import sys
import time
import uuid
from queue import Empty, Queue
from threading import Thread
from typing import Optional

from flask import Blueprint, Response, jsonify, request, stream_with_context

from workflowmvp.http import blocking_run_enabled, is_debug, json_error, json_internal_error
from workflowmvp.services.cleanup import cleanup_files
from workflowmvp.services.credentials import sanitize_credentials
from workflowmvp.services.runner import (
    build_redactor,
    build_run_env,
    encode_sse,
    ensure_run_dir,
    resolve_workflow_path,
    sse_error_response,
    workflow_popen_kwargs,
)

bp = Blueprint("run", __name__)


@bp.route("/api/run-workflow", methods=["POST"])
def run_workflow():
    if not blocking_run_enabled():
        return json_error(
            "Blocking run endpoint is disabled. Use /api/run-workflow/stream.",
            404,
        )

    payload = request.get_json(silent=True) or {}
    workflow_path = payload.get("workflow_path", "")
    creds = sanitize_credentials(payload.get("credentials"))

    abs_path = resolve_workflow_path(workflow_path)
    if not abs_path:
        return json_error("Workflow file not found", 404)

    run_id = uuid.uuid4().hex[:12]
    run_dir = ensure_run_dir(run_id)
    env = build_run_env(creds)
    env["WORKFLOW_RUN_ID"] = run_id
    env["WORKFLOW_OUTPUT_DIR"] = run_dir
    redact = build_redactor(env)

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
                "stdout": redact(result.stdout),
                "stderr": redact(result.stderr),
                "returncode": result.returncode,
                "run_id": run_id,
            }
        )
    except subprocess.TimeoutExpired:
        return json_error(redact("Workflow timed out"), 504)
    except Exception as exc:
        return json_error(redact(str(exc)), 500)


@bp.route("/api/run-workflow/stream", methods=["POST"])
def run_workflow_stream():
    payload = request.get_json(silent=True) or {}
    workflow_path = payload.get("workflow_path", "")
    creds = sanitize_credentials(payload.get("credentials"))

    abs_path = resolve_workflow_path(workflow_path)
    if not abs_path:
        return sse_error_response("Workflow file not found"), 404

    run_id = uuid.uuid4().hex[:12]
    run_dir = ensure_run_dir(run_id)
    env = build_run_env(creds)
    env["WORKFLOW_RUN_ID"] = run_id
    env["WORKFLOW_OUTPUT_DIR"] = run_dir
    env["PYTHONUNBUFFERED"] = "1"
    redact = build_redactor(env)

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
                    yield encode_sse("error", {"message": redact("Workflow timed out")})
                    break
                try:
                    line = line_queue.get(timeout=0.25)
                except Empty:
                    continue
                if line is None:
                    break
                yield encode_sse("log", {"line": redact(line.rstrip("\n"))})

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
            yield encode_sse("error", {"message": redact("Workflow timed out")})
        except Exception as exc:
            yield encode_sse("error", {"message": redact(str(exc))})

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@bp.route("/api/cleanup", methods=["POST"])
def cleanup_files_api():
    try:
        count = cleanup_files(verbose=is_debug())
        return jsonify(
            {"success": True, "message": f"Cleaned up {count} files", "files_cleaned": count}
        )
    except Exception as exc:
        return json_internal_error(exc)
