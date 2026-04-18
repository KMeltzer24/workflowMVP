"""Tests for the video-to-workflow pipeline.

Covers:
  - /api/parse-video error paths (missing file, wrong provider, no key).
  - calculate_frame_difference edge cases (identical vs different frames).
  - sample_frames_intelligent on a tiny synthetic video (first + last).
  - infer_workflow_from_frames with Gemini fully mocked — no network.
"""

from __future__ import annotations

import io
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

import main
from workflowmvp import video_to_workflow as vtw


@pytest.fixture()
def client():
    main.app.config["TESTING"] = True
    with main.app.test_client() as test_client:
        yield test_client


# ---------------------------------------------------------------------------
# API error paths
# ---------------------------------------------------------------------------


def test_parse_video_requires_file(client) -> None:
    response = client.post("/api/parse-video", data={})
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["success"] is False
    assert "no video" in payload["error"].lower()


def test_parse_video_rejects_non_gemini_provider(
    client, monkeypatch: pytest.MonkeyPatch
) -> None:
    for key in ("GEMINI_API_KEY", "GROQ_API_KEY"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("LLM_PROVIDER", "groq")
    monkeypatch.setenv("GROQ_API_KEY", "test-key")

    data = {
        "video": (io.BytesIO(b"fake-video-bytes"), "demo.mp4"),
    }
    response = client.post(
        "/api/parse-video", data=data, content_type="multipart/form-data"
    )
    payload = response.get_json()
    assert payload["success"] is False
    assert "gemini" in payload["error"].lower()
    assert payload["missing_requirements"] == ["GEMINI_API_KEY"]


def test_parse_video_requires_gemini_api_key(
    client, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "gemini")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    data = {
        "video": (io.BytesIO(b"fake-video-bytes"), "demo.mp4"),
    }
    response = client.post(
        "/api/parse-video", data=data, content_type="multipart/form-data"
    )
    payload = response.get_json()
    assert payload["success"] is False
    assert "GEMINI_API_KEY" in payload["error"]


# ---------------------------------------------------------------------------
# Frame diff scoring
# ---------------------------------------------------------------------------


def _solid_frame(color: int, shape=(48, 64, 3)) -> np.ndarray:
    return np.full(shape, color, dtype=np.uint8)


def test_frame_difference_near_zero_for_identical() -> None:
    frame = _solid_frame(128)
    assert vtw.calculate_frame_difference(frame, frame) < 0.05


def test_frame_difference_high_for_opposite_colors() -> None:
    a = _solid_frame(0)
    b = _solid_frame(255)
    score = vtw.calculate_frame_difference(a, b)
    assert score > 0.5


# ---------------------------------------------------------------------------
# Synthetic video sampling
# ---------------------------------------------------------------------------


def _write_synthetic_video(path: Path, frames: int = 10) -> None:
    """Write a small MP4 with alternating colors so scene changes are real."""
    import cv2

    writer = cv2.VideoWriter(
        str(path),
        cv2.VideoWriter_fourcc(*"mp4v"),
        5,  # fps
        (64, 48),
    )
    assert writer.isOpened(), "cv2 could not open VideoWriter (missing codec?)"
    try:
        for i in range(frames):
            color = 0 if (i // 3) % 2 == 0 else 255
            writer.write(_solid_frame(color, shape=(48, 64, 3)))
    finally:
        writer.release()


def test_sample_frames_intelligent_returns_first_and_last(tmp_path: Path) -> None:
    video = tmp_path / "demo.mp4"
    _write_synthetic_video(video, frames=20)

    frames, tmpdir = vtw.sample_frames_intelligent(str(video), max_frames=6)
    try:
        assert frames, "expected at least one frame"
        assert Path(frames[0]).name.startswith("frame_000_start")
        assert any(Path(f).name.endswith("_end.jpg") for f in frames)
        assert len(frames) <= 6
    finally:
        import shutil

        shutil.rmtree(tmpdir, ignore_errors=True)


def test_sample_frames_intelligent_raises_on_bad_video(tmp_path: Path) -> None:
    bogus = tmp_path / "not_a_video.mp4"
    bogus.write_bytes(b"not a real video")
    with pytest.raises(ValueError):
        vtw.sample_frames_intelligent(str(bogus))


# ---------------------------------------------------------------------------
# infer_workflow_from_frames with mocked Gemini client
# ---------------------------------------------------------------------------


def test_infer_workflow_from_frames_with_mocked_gemini(tmp_path: Path) -> None:
    frame_path = tmp_path / "frame.jpg"
    frame_path.write_bytes(b"\xff\xd8\xff\xe0fake-jpeg")

    fake_response = MagicMock()
    fake_response.text = "1. Do the thing\n2. Send email"

    fake_client = MagicMock()
    fake_client.models.generate_content.return_value = fake_response

    with patch("workflowmvp.video_to_workflow.genai.Client", return_value=fake_client):
        result = vtw.infer_workflow_from_frames([str(frame_path)], api_key="fake")

    assert "Do the thing" in result
    fake_client.models.generate_content.assert_called_once()
