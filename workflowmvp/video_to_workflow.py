"""
Video to workflow — sample frames from a recording and infer outcome-oriented prose
steps using Gemini multimodal ``generate_content`` (JPEG frames → text workflow).
"""

from __future__ import annotations

import logging
import os
import shutil
import tempfile
from typing import Any, List, Optional, Tuple

import cv2
import numpy as np
from google import genai
from google.genai import types

from .llm import DEFAULT_GEMINI_MODEL, gemini_response_to_text
from .prompts import load_prompt_template

logger = logging.getLogger(__name__)

# JPEG quality for frame files sent to Gemini (lower = smaller files, faster upload).
_FRAME_JPEG_QUALITY = 82
# Minimum visual distance (0..1) vs last kept frame to count as a new scene.
_SCENE_CHANGE_MIN = 0.18
# Compare downscaled frames so 4K recordings stay fast.
_COMPARE_MAX_SIDE = 480

_GEMINI_VIDEO_TEMPERATURE = 0.1
_GEMINI_VIDEO_MAX_OUTPUT_TOKENS = 2048


def _resolve_gemini_model(model: Optional[str]) -> str:
    explicit = (model or "").strip()
    if explicit:
        return explicit
    env_model = (os.getenv("GEMINI_MODEL") or "").strip()
    return env_model or DEFAULT_GEMINI_MODEL


def _video_workflow_prompt(frame_count: int) -> str:
    """Instructions for Gemini vision: outcome-oriented workflow text from key frames."""
    template = load_prompt_template("video_workflow_v1.txt")
    return template.format(frame_count=frame_count).strip()


def _resize_for_compare(frame: np.ndarray) -> np.ndarray:
    """Downscale BGR frame for cheaper difference metrics."""
    h, w = frame.shape[:2]
    m = max(h, w)
    if m <= _COMPARE_MAX_SIDE:
        return frame
    scale = _COMPARE_MAX_SIDE / m
    new_w = max(1, int(w * scale))
    new_h = max(1, int(h * scale))
    return cv2.resize(frame, (new_w, new_h), interpolation=cv2.INTER_AREA)


def calculate_frame_difference(frame1: np.ndarray, frame2: np.ndarray) -> float:
    """Return a 0..1 score where higher means more visual change (cheap path: histogram + MSE)."""
    try:
        a = _resize_for_compare(frame1)
        b = _resize_for_compare(frame2)
        if a.shape != b.shape:
            b = cv2.resize(b, (a.shape[1], a.shape[0]), interpolation=cv2.INTER_AREA)

        gray1 = cv2.cvtColor(a, cv2.COLOR_BGR2GRAY)
        gray2 = cv2.cvtColor(b, cv2.COLOR_BGR2GRAY)

        hist1 = cv2.calcHist([gray1], [0], None, [256], [0, 256])
        hist2 = cv2.calcHist([gray2], [0], None, [256], [0, 256])
        hist_diff = 1.0 - cv2.compareHist(hist1, hist2, cv2.HISTCMP_CORREL)
        hist_diff = float(np.clip(hist_diff, 0.0, 1.0))

        g1 = gray1.astype(np.float32) / 255.0
        g2 = gray2.astype(np.float32) / 255.0
        mse = float(np.mean((g1 - g2) ** 2))

        combined = 0.45 * hist_diff + 0.55 * min(mse * 4.0, 1.0)
        return float(min(combined, 1.0))
    except Exception:
        return 0.5


def sample_frames_intelligent(video_path: str, max_frames: int = 15) -> Tuple[List[str], str]:
    """
    Sample frames from a video: always first and last, plus middle frames on scene change.
    Returns: (frame_paths, temp_directory)
    """
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise ValueError(f"Could not open video file: {video_path}")

    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    fps = cap.get(cv2.CAP_PROP_FPS) or 30
    duration = total_frames / fps if total_frames > 0 else 0.0

    logger.info("Video: %s frames, %.1fs duration", total_frames, duration)

    tmpdir = tempfile.mkdtemp(prefix="wf_frames_")
    selected_frames: List[str] = []
    encode_params = [int(cv2.IMWRITE_JPEG_QUALITY), _FRAME_JPEG_QUALITY]

    cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
    ret, first_frame = cap.read()
    if not ret or first_frame is None or first_frame.size == 0:
        cap.release()
        shutil.rmtree(tmpdir, ignore_errors=True)
        raise ValueError(f"No frames could be read from video: {video_path}")

    first_path = os.path.join(tmpdir, "frame_000_start.jpg")
    cv2.imwrite(first_path, first_frame, encode_params)
    selected_frames.append(first_path)

    key_positions: List[int] = []
    if duration > 10:
        for pct in (0.1, 0.25, 0.4, 0.6, 0.75, 0.9):
            key_positions.append(int(total_frames * pct))
    else:
        interval = max(1, int(fps * 2))
        key_positions = list(range(interval, max(total_frames - interval, 1), interval))

    last_kept = first_frame
    max_middle = max(0, max_frames - 2)

    for pos in key_positions:
        if len(selected_frames) >= max_frames - 1:
            break
        if max_middle <= 0:
            break
        cap.set(cv2.CAP_PROP_POS_FRAMES, pos)
        ret, frame = cap.read()
        if not ret or frame is None or frame.size == 0:
            continue

        diff = calculate_frame_difference(last_kept, frame)
        if diff >= _SCENE_CHANGE_MIN:
            frame_path = os.path.join(tmpdir, f"frame_{pos:05d}_scene.jpg")
            cv2.imwrite(frame_path, frame, encode_params)
            selected_frames.append(frame_path)
            last_kept = frame
            max_middle -= 1

    if len(selected_frames) < max_frames and total_frames > 1:
        cap.set(cv2.CAP_PROP_POS_FRAMES, total_frames - 1)
        ret, last_frame = cap.read()
        if ret and last_frame is not None and last_frame.size != 0:
            last_path = os.path.join(tmpdir, f"frame_{total_frames - 1:05d}_end.jpg")
            cv2.imwrite(last_path, last_frame, encode_params)
            selected_frames.append(last_path)

    cap.release()

    logger.info("Extracted %s key frame(s)", len(selected_frames))
    return selected_frames, tmpdir


def infer_workflow_from_frames(frame_paths: List[str], api_key: str, model: Optional[str] = None) -> str:
    """Analyze JPEG frames with Gemini and return outcome-oriented numbered steps, or ``""`` on failure."""
    resolved = _resolve_gemini_model(model)
    client = genai.Client(api_key=api_key)
    prompt = _video_workflow_prompt(len(frame_paths))

    contents: List[Any] = [prompt]

    try:
        for frame_path in frame_paths:
            with open(frame_path, "rb") as f:
                frame_data = f.read()
            contents.append(types.Part.from_bytes(data=frame_data, mime_type="image/jpeg"))

        logger.info("Analyzing %s frame(s) with Gemini (%s)...", len(frame_paths), resolved)
        resp = client.models.generate_content(
            model=resolved,
            contents=contents,
            config=types.GenerateContentConfig(
                temperature=_GEMINI_VIDEO_TEMPERATURE,
                max_output_tokens=_GEMINI_VIDEO_MAX_OUTPUT_TOKENS,
            ),
        )

        result = gemini_response_to_text(resp).strip()
        if not result:
            logger.warning("Gemini returned empty workflow text for video frames")
            return ""

        logger.info("Video workflow text generated (%s chars)", len(result))
        return result

    except Exception:
        logger.exception("Gemini workflow inference failed for video frames")
        return ""
