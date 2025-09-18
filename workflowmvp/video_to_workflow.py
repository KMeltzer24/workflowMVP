"""
Video to Workflow - Extract frames from a video and infer a text workflow using Gemini
"""

import os
import cv2
import tempfile
from typing import List
import google.generativeai as genai


def sample_frames(video_path: str, max_frames: int = 12) -> List[str]:
    cap = cv2.VideoCapture(video_path)
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) or 1
    step = max(1, total // max_frames)
    frames = []
    idx = 0
    tmpdir = tempfile.mkdtemp(prefix="wf_frames_")
    while True:
        ret, frame = cap.read()
        if not ret:
            break
        if idx % step == 0:
            path = os.path.join(tmpdir, f"frame_{idx}.jpg")
            cv2.imwrite(path, frame)
            frames.append(path)
        idx += 1
        if len(frames) >= max_frames:
            break
    cap.release()
    return frames


def infer_workflow_from_frames(frame_paths: List[str], api_key: str, model: str = "gemini-1.5-flash") -> str:
    genai.configure(api_key=api_key)
    model_client = genai.GenerativeModel(model)
    prompt = (
        "You will be given a sequence of UI screenshots (browser). "
        "Infer a high-level workflow as numbered steps in plain text. "
        "Be concise and action-oriented. If an email is sent, include recipient, subject, and body if visible."
    )
    inputs = [prompt]
    for p in frame_paths:
        inputs.append({"mime_type": "image/jpeg", "data": open(p, "rb").read()})
    resp = model_client.generate_content(inputs)
    return resp.text or ""


def video_to_workflow_txt(video_path: str, output_txt: str, api_key: str, model: str = "gemini-1.5-flash") -> str:
    frames = sample_frames(video_path)
    steps_text = infer_workflow_from_frames(frames, api_key, model=model)
    with open(output_txt, "w", encoding="utf-8") as f:
        f.write(steps_text.strip() + "\n")
    return output_txt


