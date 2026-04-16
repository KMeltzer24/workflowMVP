"""
Video to Workflow - Extract frames from a video and infer a text workflow using Gemini
"""

import os
import shutil
import tempfile
from typing import Any, Dict, List, Optional, Tuple

import cv2
import google.generativeai as genai
import numpy as np


def calculate_frame_difference(frame1: np.ndarray, frame2: np.ndarray) -> float:
    """Calculate the difference between two frames using multiple methods"""
    try:
        # Convert to grayscale for comparison
        gray1 = cv2.cvtColor(frame1, cv2.COLOR_BGR2GRAY)
        gray2 = cv2.cvtColor(frame2, cv2.COLOR_BGR2GRAY)

        # Method 1: Histogram comparison
        hist1 = cv2.calcHist([gray1], [0], None, [256], [0, 256])
        hist2 = cv2.calcHist([gray2], [0], None, [256], [0, 256])
        hist_diff = 1.0 - cv2.compareHist(hist1, hist2, cv2.HISTCMP_CORREL)

        # Method 2: Structural similarity
        ssim_score = calculate_ssim(gray1, gray2)
        ssim_diff = 1.0 - ssim_score

        # Method 3: Edge detection difference
        edges1 = cv2.Canny(gray1, 50, 150)
        edges2 = cv2.Canny(gray2, 50, 150)
        edge_diff = np.sum(np.abs(edges1.astype(float) - edges2.astype(float))) / (edges1.shape[0] * edges1.shape[1])
        edge_diff = min(edge_diff / 255.0, 1.0)  # Normalize

        # Combine methods with weights
        combined_diff = (hist_diff * 0.4 + ssim_diff * 0.4 + edge_diff * 0.2)
        return min(combined_diff, 1.0)
    except Exception:
        return 0.5  # Default moderate difference

def calculate_ssim(img1: np.ndarray, img2: np.ndarray) -> float:
    """Calculate Structural Similarity Index (SSIM) between two images"""
    try:
        # Ensure images are the same size
        if img1.shape != img2.shape:
            img2 = cv2.resize(img2, (img1.shape[1], img1.shape[0]))

        # Calculate SSIM components
        mu1 = cv2.GaussianBlur(img1.astype(np.float64), (11, 11), 1.5)
        mu2 = cv2.GaussianBlur(img2.astype(np.float64), (11, 11), 1.5)

        mu1_sq = mu1 * mu1
        mu2_sq = mu2 * mu2
        mu1_mu2 = mu1 * mu2

        sigma1_sq = cv2.GaussianBlur(img1.astype(np.float64) * img1.astype(np.float64), (11, 11), 1.5) - mu1_sq
        sigma2_sq = cv2.GaussianBlur(img2.astype(np.float64) * img2.astype(np.float64), (11, 11), 1.5) - mu2_sq
        sigma12 = cv2.GaussianBlur(img1.astype(np.float64) * img2.astype(np.float64), (11, 11), 1.5) - mu1_mu2

        c1 = (0.01 * 255) ** 2
        c2 = (0.03 * 255) ** 2

        ssim_map = ((2 * mu1_mu2 + c1) * (2 * sigma12 + c2)) / ((mu1_sq + mu2_sq + c1) * (sigma1_sq + sigma2_sq + c2))
        return np.mean(ssim_map)
    except Exception:
        return 0.5  # Default moderate similarity

def detect_ui_elements(frame: np.ndarray) -> Dict[str, Any]:
    """Detect UI elements in a frame using computer vision"""
    try:
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

        # Detect buttons (rectangular shapes)
        edges = cv2.Canny(gray, 50, 150)
        contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        buttons = []
        for contour in contours:
            area = cv2.contourArea(contour)
            if area > 100:  # Filter small contours
                x, y, w, h = cv2.boundingRect(contour)
                aspect_ratio = w / h
                if 0.5 < aspect_ratio < 3.0:  # Button-like aspect ratio
                    buttons.append({
                        'type': 'button',
                        'x': x, 'y': y, 'w': w, 'h': h,
                        'area': area
                    })

        # Detect text regions using MSER
        mser = cv2.MSER_create()
        regions, _ = mser.detectRegions(gray)
        text_regions = []
        for region in regions:
            if len(region) > 10:  # Filter small regions
                x, y, w, h = cv2.boundingRect(region.reshape(-1, 1, 2))
                text_regions.append({
                    'type': 'text',
                    'x': x, 'y': y, 'w': w, 'h': h
                })

        return {
            'buttons': buttons,
            'text_regions': text_regions,
            'total_elements': len(buttons) + len(text_regions)
        }
    except Exception:
        return {'buttons': [], 'text_regions': [], 'total_elements': 0}

def extract_text_from_frame(frame: np.ndarray) -> str:
    """Extract text from frame using basic OCR techniques"""
    try:
        # Convert to grayscale
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

        # Apply threshold to get better text contrast
        _, thresh = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)

        # Find contours that might be text
        contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        text_candidates = []
        for contour in contours:
            x, y, w, h = cv2.boundingRect(contour)
            aspect_ratio = w / h
            area = w * h

            # Filter for text-like regions
            if 0.1 < aspect_ratio < 10 and area > 50:
                text_candidates.append((x, y, w, h))

        # Sort by y-coordinate (top to bottom)
        text_candidates.sort(key=lambda x: x[1])

        # Extract text regions (simplified - would need actual OCR library for real text)
        text_info = []
        for x, y, w, h in text_candidates:
            text_info.append(f"Text region at ({x},{y}) size {w}x{h}")

        return " | ".join(text_info)
    except Exception:
        return ""

def analyze_frame_content(frame: np.ndarray) -> Dict[str, Any]:
    """Analyze frame content for workflow inference"""
    try:
        # Basic color analysis
        mean_color = np.mean(frame, axis=(0, 1))
        dominant_color = np.argmax(mean_color)
        color_names = ['Blue', 'Green', 'Red']
        dominant_color_name = color_names[dominant_color] if dominant_color < 3 else 'Unknown'

        # Brightness analysis
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        brightness = np.mean(gray)

        # Edge density (indicates complexity)
        edges = cv2.Canny(gray, 50, 150)
        edge_density = np.sum(edges > 0) / (edges.shape[0] * edges.shape[1])

        # UI element detection
        ui_elements = detect_ui_elements(frame)

        # Text extraction
        text_content = extract_text_from_frame(frame)

        return {
            'dominant_color': dominant_color_name,
            'brightness': float(brightness),
            'edge_density': float(edge_density),
            'ui_elements': ui_elements,
            'text_content': text_content,
            'has_text': len(text_content) > 0,
            'complexity': 'high' if edge_density > 0.1 else 'medium' if edge_density > 0.05 else 'low'
        }
    except Exception:
        return {
            'dominant_color': 'Unknown',
            'brightness': 128.0,
            'edge_density': 0.0,
            'ui_elements': {'buttons': [], 'text_regions': [], 'total_elements': 0},
            'text_content': '',
            'has_text': False,
            'complexity': 'low'
        }

def sample_frames_intelligent(video_path: str, max_frames: int = 15) -> Tuple[List[str], str]:
    """
    Intelligently sample frames from video by detecting scene changes and important moments
    Returns: (frame_paths, temp_directory)
    """
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise ValueError(f"Could not open video file: {video_path}")

    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    fps = cap.get(cv2.CAP_PROP_FPS) or 30
    duration = total_frames / fps

    print(f"📹 Video: {total_frames} frames, {duration:.1f}s duration")

    tmpdir = tempfile.mkdtemp(prefix="wf_frames_")
    selected_frames = []

    # Always include first frame
    cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
    ret, first_frame = cap.read()
    if ret:
        first_path = os.path.join(tmpdir, "frame_000_start.jpg")
        cv2.imwrite(first_path, first_frame)
        selected_frames.append(first_path)

    # Strategy 1: Sample key moments (beginning, middle sections, end)
    key_positions = []
    if duration > 10:  # For longer videos, sample more strategically
        # Sample at 10%, 25%, 40%, 60%, 75%, 90% of video
        for pct in [0.1, 0.25, 0.4, 0.6, 0.75, 0.9]:
            key_positions.append(int(total_frames * pct))
    else:  # For shorter videos, sample more frequently
        # Sample every 2-3 seconds
        interval = max(1, int(fps * 2))
        key_positions = list(range(interval, total_frames - interval, interval))

    # Strategy 2: Detect scene changes by comparing consecutive frames
    scene_change_threshold = 0.85  # Correlation threshold for scene change
    last_sampled_frame = first_frame.copy()

    for pos in key_positions[:max_frames-2]:  # Reserve space for start and end frames
        cap.set(cv2.CAP_PROP_POS_FRAMES, pos)
        ret, frame = cap.read()
        if not ret:
            continue

        # Check if this frame is significantly different from the last sampled frame
        correlation = calculate_frame_difference(last_sampled_frame, frame)

        if correlation < scene_change_threshold:  # Significant change detected
            frame_path = os.path.join(tmpdir, f"frame_{pos:03d}_scene.jpg")
            cv2.imwrite(frame_path, frame)
            selected_frames.append(frame_path)
            last_sampled_frame = frame.copy()

    # Always include last frame
    cap.set(cv2.CAP_PROP_POS_FRAMES, total_frames - 1)
    ret, last_frame = cap.read()
    if ret and len(selected_frames) < max_frames:
        last_path = os.path.join(tmpdir, f"frame_{total_frames-1:03d}_end.jpg")
        cv2.imwrite(last_path, last_frame)
        selected_frames.append(last_path)

    cap.release()

    print(f"📸 Extracted {len(selected_frames)} key frames")
    return selected_frames, tmpdir

# Backward compatibility wrapper
def sample_frames(video_path: str, max_frames: int = 12) -> List[str]:
    """Legacy function for backward compatibility"""
    frames, _ = sample_frames_intelligent(video_path, max_frames)
    return frames


def infer_workflow_from_frames(frame_paths: List[str], api_key: str, model: Optional[str] = None) -> str:
    model = model or os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
    """Analyze video frames and generate workflow steps using advanced AI prompting"""
    genai.configure(api_key=api_key)
    model_client = genai.GenerativeModel(model)

    # Create a comprehensive prompt for better workflow inference
    prompt = f"""You are analyzing {len(frame_paths)} screenshots from a screen recording to understand a workflow.

TASK: Generate a clear, actionable workflow as numbered steps.

ANALYSIS GUIDELINES:
1. Look for UI changes between frames that indicate user actions
2. Identify specific applications, websites, or tools being used
3. Note any data entry, clicks, navigation, or file operations
4. Pay attention to forms, buttons, menus, and dialog boxes
5. Capture exact details like URLs, email addresses, file names, text content

OUTPUT FORMAT:
- Number each step (1., 2., 3., etc.)
- Be specific and actionable (not vague like "navigate to website")
- Include exact URLs, email addresses, file names when visible
- Mention specific UI elements (buttons, fields, menus)
- If sending emails, include recipient, subject, and body content
- If downloading/uploading files, specify file names and locations
- If using APIs or web services, include the exact endpoints

EXAMPLES OF GOOD STEPS:
✓ "Navigate to https://api.coindesk.com/v1/bpi/currentprice.json in browser"
✓ "Download the JSON response and save as 'bitcoin_price.json'"
✓ "Open Gmail and compose new email to john@example.com"
✓ "Enter subject line: 'Bitcoin Price Update - $45,230'"
✗ "Go to a website" (too vague)
✗ "Send an email" (missing details)

Now analyze these {len(frame_paths)} screenshots and generate the workflow:"""

    # Prepare inputs with the enhanced prompt and all frames
    inputs = [prompt]

    try:
        for frame_path in frame_paths:
            with open(frame_path, "rb") as f:
                frame_data = f.read()
            inputs.append({
                "mime_type": "image/jpeg",
                "data": frame_data
            })

        print("🤖 Analyzing frames with AI...")
        resp = model_client.generate_content(
            inputs,
            generation_config=genai.types.GenerationConfig(
                temperature=0.1,  # Lower temperature for more consistent results
                max_output_tokens=1500,  # Allow longer responses for detailed workflows
            )
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
    model = model or os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
    """
    Convert video to workflow text with improved error handling and cleanup
    """
    temp_dir = None
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


