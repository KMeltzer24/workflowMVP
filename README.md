# WorkflowMVP

🚀 **Automated Workflow Generator** - Turn screen‑capture videos into executable Python workflows using Google's Gemini AI.

## Description

WorkflowMVP takes a screen‑capture video of a task (e.g., sending an email) and generates a runnable Python script that performs the same workflow using built‑in tools (file I/O, HTTP, email, etc.). You can also pass a text workflow if you prefer.

### Key Features

- 🎬 **Video → Workflow**: Infer steps from screen‑capture videos with Gemini
- 🧾 **Optional Text Input**: You can also run a saved `.txt` workflow with `--from-text`
- 🛠️ **Built‑in Tools**: File I/O, HTTP requests, email (SMTP with prompts), wait/delays
- 🤖 **Code Generation**: Produces a complete Python script with a `main()` function
- 📈 **Auto Run + Logs**: Generates, runs immediately, and logs each step
- 📁 **Organized Outputs**: All artifacts live under `data/` (texts, scripts, outputs)

## Installation

1. Clone the repository:
```bash
git clone https://github.com/KMeltzer24/workflowmvp.git
```

2. Install dependencies:
```bash
pip install -r requirements.txt
```

## Usage

**Usage:**

1. **Set your Gemini API key:**
```bash
export GEMINI_API_KEY="your-api-key-here"
```

2a. **Run directly from a video (auto‑generates .txt and .py):**
```bash
python3 main.py data/workflow_videos/YOUR_VIDEO.mp4
```

This infers steps from the video, saves a workflow text at `data/workflow_texts/YOUR_VIDEO.txt`, generates `data/generated_workflows/YOUR_VIDEO.py`, and runs it immediately.

2b. **Run from a text workflow instead:**
```bash
python3 main.py data/workflow_texts/YOUR_WORKFLOW_FILE.txt --from-text
```

Note: Replace `YOUR_VIDEO.mp4` or `YOUR_WORKFLOW_FILE.txt` with your actual files.



## Available Tools

The system includes a comprehensive set of built-in tools:

- **download**: Download content from URLs
- **read_file**: Read content from files
- **write_file**: Write content to files
- **send_email**: Send email notifications
- **process_data**: Transform and process data
- **wait**: Add delays between steps
- **http_request**: Make HTTP requests
- **list_files**: List files in directories
- **create_directory**: Create directories

## Example Input

Workflows are typically inferred from videos and saved under `data/workflow_texts/`. A simple example of a text format (if you write one manually):

```
1. Create a directory called "sandbox"
2. Write the text "sample content" to file "sandbox/sample.txt"
3. Read the file "sandbox/sample.txt"
4. List files in the "sandbox" directory
5. Wait for 2 seconds
```

## Notes

- Email sending uses the built-in `send_email` tool. If `EMAIL_USER`, `EMAIL_PASSWORD`, and `EMAIL_FROM` are not set, the program will prompt you.
- Gmail defaults are shown during the prompt:
  - SMTP server: `smtp.gmail.com`
  - Port `587` (STARTTLS, recommended) or `465` (SSL)
  - Username: full email (e.g., `name@gmail.com`)
  - Password: Gmail App Password (generate under Google Account → Security → App passwords)

## How It Works

1. **Infer**: Extracts representative frames from your screen‑capture video and asks Gemini to infer high‑level steps.
2. **Parse**: Converts the inferred steps into structured actions (e.g., send_email, write_file, wait).
3. **Generate**: Builds a complete, runnable Python script that uses the built‑in tool registry.
4. **Execute**: Runs the generated script immediately and logs results; artifacts are saved under `data/`.

## Development

This project uses Python 3.8+ and follows standard Python packaging conventions.

### Project Structure

```
data/
├── workflow_videos/       # Your screen‑capture videos (input)
├── workflow_texts/        # Inferred (or manual) workflow text files
├── generated_workflows/   # Generated Python scripts
└── outputs/               # Other output files/artifacts
workflowmvp/
├── __init__.py            # Package metadata
├── video_to_workflow.py   # Frame sampling + Gemini inference
├── parser.py              # Convert inferred text → structured steps/actions
├── agent.py               # Generate Python code (Gemini); enforce main()
└── tools.py               # Tool registry (download, read/write, email, wait, http, etc.)
main.py                    # CLI (video by default; --from-text for text input)
requirements.txt           # Dependencies
setup.py                   # Packaging metadata (optional)
```

### File Explanations

- **`main.py`**: One‑command interface. Pass a video; it infers, generates, and runs. Use `--from-text` to run a saved text workflow instead.
- **`workflowmvp/video_to_workflow.py`**: Samples frames and asks Gemini to infer the step list.
- **`workflowmvp/parser.py`**: Converts inferred text into structured steps/actions with parameters.
- **`workflowmvp/agent.py`**: Generates the final Python script using the tool registry and enforces a `main()` entrypoint.
- **`workflowmvp/tools.py`**: Central tool catalog (email, file I/O, HTTP, wait, etc.).
- **`data/`**: Your inputs (videos), inferred texts, generated scripts, and outputs.
- **`requirements.txt` / `setup.py`**: Dependencies and optional packaging.

### Adding Custom Tools

You can extend the system by adding custom tools to the `ToolRegistry`:

```python
from workflowmvp.tools import Tool, ToolRegistry

def my_custom_tool(param1, param2):
    # Your custom logic here
    return {"success": True, "result": "custom result"}

registry = ToolRegistry()
registry.register_tool(Tool(
    name="my_custom_tool",
    description="My custom workflow tool",
    function=my_custom_tool,
    parameters={"param1": "First parameter", "param2": "Second parameter"}
))
```

