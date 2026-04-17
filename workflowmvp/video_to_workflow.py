"""
Video to Workflow - Extract frames from a video and infer a text workflow using Gemini
"""

import os
import shutil
import tempfile
from typing import Any, List, Optional, Tuple

import cv2
import numpy as np
from google import genai
from google.genai import types

# JPEG quality for frame files sent to Gemini (lower = smaller files, faster upload).
_FRAME_JPEG_QUALITY = 82
# Minimum visual distance (0..1) vs last kept frame to count as a new scene.
_SCENE_CHANGE_MIN = 0.18
# Compare downscaled frames so 4K recordings stay fast.
_COMPARE_MAX_SIDE = 480


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

        # Combine: histogram shift + pixel MSE (capped to keep scale sane)
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

    print(f"📹 Video: {total_frames} frames, {duration:.1f}s duration")

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

    # Candidate timestamps (indices) — scan more positions than we will keep.
    key_positions: List[int] = []
    if duration > 10:
        for pct in (0.1, 0.25, 0.4, 0.6, 0.75, 0.9):
            key_positions.append(int(total_frames * pct))
    else:
        interval = max(1, int(fps * 2))
        key_positions = list(range(interval, max(total_frames - interval, 1), interval))

    last_kept = first_frame
    # Reserve one slot for the final frame.
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
        if ret and last_frame is not None and last_frame.size > 0:
            last_path = os.path.join(tmpdir, f"frame_{total_frames - 1:05d}_end.jpg")
            cv2.imwrite(last_path, last_frame, encode_params)
            selected_frames.append(last_path)

    cap.release()

    print(f"📸 Extracted {len(selected_frames)} key frames")
    return selected_frames, tmpdir


def sample_frames(video_path: str, max_frames: int = 12) -> List[str]:
    """Legacy function for backward compatibility"""
    frames, _ = sample_frames_intelligent(video_path, max_frames)
    return frames


def infer_workflow_from_frames(frame_paths: List[str], api_key: str, model: Optional[str] = None) -> str:
    """Analyze video frames and infer an outcome-oriented workflow (not UI replay)."""
    model = model or os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
    client = genai.Client(api_key=api_key)

    # Goal-oriented steps: recordings demonstrate intent; runnable code must use fresh data.
    prompt = f"""You are analyzing {len(frame_paths)} screenshots from a screen recording.

TASK: Infer what the user wants **accomplished** (the outcome), not a play-by-play of every click or keystroke.

CRITICAL — DO NOT FREEZE FACTS FROM THE VIDEO:
- Text visible in Google results, countdowns, "closes in N minutes", clocks, or snippets are **stale** the moment the recording ends.
- Never copy those numbers or times into the workflow as if they were permanent truth. Phrase steps as **what to compute or look up at run time** (e.g. current time in Seattle, minutes until today's US stock market close).
- Prefer **one concise email step** whose body should **summarize computed results**, not paste literal on-screen sentences from the recording.

ANALYSIS GUIDELINES:
1. Infer the end goal (e.g. "email myself how long until market close") vs. the UI path used to get there.
2. If the recording is mostly browser search + Gmail compose, collapse to: gather/compute the needed facts, then send email — avoid steps like "type into search bar" unless browser automation is truly required.
3. Preserve **stable** user choices: recipient email, subject *theme*, city/timezone names, ticker symbols, file names.
4. For APIs or downloads, prefer **explicit HTTPS URLs** when the user clearly used a public API; avoid long session-specific Google URLs with tracking parameters.

OUTPUT FORMAT:
- Number each step (1., 2., 3., …).
- Each step is outcome-oriented and implementable in Python (stdlib, HTTP APIs, file I/O, email).
- If email is involved: name recipient, subject line intent, and that the **body must reflect values computed in earlier steps** — do not embed literal countdown or search-result text from the video.

EXAMPLES:
✓ "Get current local time for America/Los_Angeles (Seattle)."
✓ "Determine the next regular-session US equity market close (NYSE, Eastern Time) and compute minutes from now until that close."
✓ "Send email to user@example.com with subject 'Market close' and body stating the computed time and minutes remaining (no placeholder numbers)."
✗ "Enter 'The stock market closes in 22 mins' in the email body" (that is a recording artifact — wrong for automation)
✗ Eight steps that only describe clicking and typing in Google and Gmail (too literal)

Now analyze these {len(frame_paths)} screenshots and generate the workflow:"""

    contents: List[Any] = [prompt]

    try:
        for frame_path in frame_paths:
            with open(frame_path, "rb") as f:
                frame_data = f.read()
            contents.append(types.Part.from_bytes(data=frame_data, mime_type="image/jpeg"))

        print("🤖 Analyzing frames with AI...")
        resp = client.models.generate_content(
            model=model,
            contents=contents,
            config=types.GenerateContentConfig(
                temperature=0.1,
                max_output_tokens=1500,
            ),
        )

        result = resp.text or ""
        print("✅ Workflow analysis complete")
        return result

    except Exception as e:
        print(f"❌ Error during AI analysis: {e}")
        # Return a basic fallback workflow
        return f"""Error analyzing video frames: {str(e)}

Fallback workflow:
1. Open application or website
2. Perform main task or operation
3. Save or submit results
4. Complete workflow

Please check your API key and try again with a clearer video."""


def video_to_workflow_txt(video_path: str, output_txt: str, api_key: str, model: Optional[str] = None) -> str:
    """
    Convert video to workflow text with improved error handling and cleanup
    """
    model = model or os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
    temp_dir: Optional[str] = None
    try:
        print(f"🎥 Processing video: {video_path}")

        # Validate video file
        if not os.path.exists(video_path):
            raise FileNotFoundError(f"Video file not found: {video_path}")

        # Check if video is readable
        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            cap.release()
            raise ValueError(f"Cannot open video file: {video_path}")
        cap.release()

        # Use intelligent frame sampling
        frames, temp_dir = sample_frames_intelligent(video_path, max_frames=15)

        if not frames:
            raise ValueError("No frames could be extracted from the video")

        steps_text = infer_workflow_from_frames(frames, api_key, model=model)

        if not steps_text or len(steps_text.strip()) < 10:
            raise ValueError("AI analysis produced no meaningful workflow")

        # Ensure output directory exists
        os.makedirs(os.path.dirname(output_txt), exist_ok=True)

        # Write the workflow text
        with open(output_txt, "w", encoding="utf-8") as f:
            f.write(steps_text.strip() + "\n")

        return output_txt

    except Exception as e:
        print(f"❌ Video processing failed: {e}")

        # Create a fallback workflow file
        fallback_content = f"""# Video processing failed: {str(e)}

# Fallback workflow - please edit manually:
1. Open the application or website shown in your video
2. Perform the main task or operation you demonstrated
3. Save or submit any results
4. Complete the workflow as shown

# To improve results:
# - Ensure your video shows clear UI interactions
# - Use a valid GEMINI_API_KEY
# - Record at a reasonable speed (not too fast)
# - Show each step clearly before moving to the next
"""

        try:
            os.makedirs(os.path.dirname(output_txt), exist_ok=True)
            with open(output_txt, "w", encoding="utf-8") as f:
                f.write(fallback_content)
        except Exception:
            pass

        raise  # Re-raise the original exception

    finally:
        # Clean up temporary files
        if temp_dir and os.path.exists(temp_dir):
            try:
                shutil.rmtree(temp_dir)
            except Exception:
                pass

