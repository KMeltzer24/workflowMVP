from __future__ import annotations

import logging
import os
import shutil
import tempfile
import time
from typing import Any, Dict, Optional

from flask import Blueprint, jsonify, request

from workflowmvp.agent import WorkflowAgent
from workflowmvp.http import (
    ALLOWED_VIDEO_MIME_PREFIXES,
    ALLOWED_VIDEO_MIME_TYPES,
    is_debug,
    json_error,
    json_internal_error,
    step_to_dict,
)
from workflowmvp.parser import WorkflowParser
from workflowmvp.services.credentials import (
    creds_from_form_or_json,
    resolve_gemini_api_key,
    resolve_gemini_model,
    sanitize_credentials,
)
from workflowmvp.services.workflow_planning import parse_rough_workflow

bp = Blueprint("planning", __name__)
logger = logging.getLogger(__name__)


@bp.route("/api/parse-workflow", methods=["POST"])
def parse_workflow():
    try:
        parse_started = time.monotonic()
        payload = request.get_json(silent=True) or {}
        workflow_text = payload.get("workflow_text", "")
        creds = sanitize_credentials(payload.get("credentials"))
        api_key = resolve_gemini_api_key(creds)
        model = resolve_gemini_model(creds)
        parser = WorkflowParser()
        planning = parse_rough_workflow(workflow_text, parser)
        steps = planning.steps
        confidence = planning.parse_confidence

        ai_assisted = False
        ai_cleanup_attempted = False
        ai_cleanup_error: Optional[str] = None
        if planning.should_ai_repair:
            if api_key:
                ai_cleanup_attempted = True
                try:
                    ai_agent = WorkflowAgent(api_key=api_key, model=model)
                    improved = ai_agent.improve_parsed_steps(workflow_text, steps)
                    if improved:
                        steps = improved
                        ai_assisted = True
                        confidence = parser.assess_parse_confidence(steps)
                except Exception as exc:
                    ai_cleanup_error = str(exc)
            else:
                ai_cleanup_error = "Missing GEMINI_API_KEY; AI cleanup was skipped."

        response: Dict[str, Any] = {
            "success": True,
            "steps": [step_to_dict(s) for s in steps],
            "parse_confidence": confidence,
            "ai_assisted": ai_assisted,
            "ai_repair": {
                "needed": planning.should_ai_repair,
                "attempted": ai_cleanup_attempted,
                "error": ai_cleanup_error,
            },
            "parse_seconds": round(time.monotonic() - parse_started, 3),
        }
        return jsonify(response)
    except Exception as exc:
        return json_internal_error(exc)


@bp.route("/api/parse-single-step", methods=["POST"])
def parse_single_step():
    try:
        payload = request.get_json(silent=True) or {}
        description = (payload.get("description") or "").strip()
        if not description:
            return json_error("No description provided", 400)

        parser = WorkflowParser()
        action, parameters = parser.extract_action_and_params(description)
        return jsonify(
            {
                "success": True,
                "action": action,
                "parameters": parameters,
            }
        )
    except Exception as exc:
        return json_internal_error(exc)


@bp.route("/api/parse-video", methods=["POST"])
def parse_video():
    debug_mode = is_debug()
    video_path: Optional[str] = None
    temp_dir: Optional[str] = None
    try:
        parse_started = time.monotonic()
        if "video" not in request.files:
            return json_error("No video file provided", 400)
        video_file = request.files["video"]
        if not video_file.filename:
            return json_error("No video file selected", 400)

        mime = (video_file.mimetype or "").lower()
        if mime and not (
            mime.startswith(ALLOWED_VIDEO_MIME_PREFIXES)
            or mime in ALLOWED_VIDEO_MIME_TYPES
        ):
            return json_error(
                f"Unsupported file type: {mime!r}. Upload a video file.",
                400,
            )

        creds = sanitize_credentials(
            creds_from_form_or_json(request.form.get("credentials"))
        )
        api_key = resolve_gemini_api_key(creds)
        if not api_key:
            return json_error(
                "Missing GEMINI_API_KEY. Add it in Settings or .env.",
                400,
                missing_requirements=["GEMINI_API_KEY"],
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
            return json_error("No frames could be extracted from the video", 400)
        model = resolve_gemini_model(creds)
        workflow_text = infer_workflow_from_frames(frames, api_key, model=model)
        if not workflow_text or len(workflow_text.strip()) < 10:
            return json_error("AI analysis produced no meaningful workflow", 502)

        parser = WorkflowParser()
        planning = parse_rough_workflow(workflow_text, parser)
        steps = planning.steps
        confidence = planning.parse_confidence
        ai_assisted = False
        ai_cleanup_attempted = False
        ai_cleanup_error: Optional[str] = None
        if planning.should_ai_repair:
            ai_cleanup_attempted = True
            try:
                ai_agent = WorkflowAgent(api_key=api_key, model=model)
                improved = ai_agent.improve_parsed_steps(workflow_text, steps)
                if improved:
                    steps = improved
                    ai_assisted = True
                    confidence = parser.assess_parse_confidence(steps)
            except Exception as exc:
                ai_cleanup_error = str(exc)

        response: Dict[str, Any] = {
            "success": True,
            "steps": [step_to_dict(s) for s in steps],
            "workflow_text": workflow_text,
            "parse_confidence": confidence,
            "ai_assisted": ai_assisted,
            "ai_repair": {
                "needed": planning.should_ai_repair,
                "attempted": ai_cleanup_attempted,
                "error": ai_cleanup_error,
            },
            "parse_seconds": round(time.monotonic() - parse_started, 3),
        }
        return jsonify(response)
    except Exception as exc:
        if debug_mode:
            logger.exception("parse_video failed")
        return json_internal_error(exc)
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
