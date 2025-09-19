# WorkflowMVP

🚀 **Automated Workflow Generator** - Turn screen‑capture videos into executable Python workflows using Google's Gemini AI.

## Description

WorkflowMVP is a powerful automation tool that can:
- **Convert screen-capture videos** into executable Python workflows using AI vision
- **Process text-based workflow descriptions** into runnable code
- **Generate complete Python scripts** that automate complex multi-step tasks
- **Execute workflows immediately** with comprehensive logging

Perfect for automating repetitive tasks like file management, web scraping, data processing, email workflows, and more.

### Use Cases

- **Data Pipeline Automation**: Download, process, and distribute data reports
- **File Organization**: Automate file sorting, renaming, and organization tasks
- **Web Scraping**: Extract data from websites and APIs with automated workflows
- **Email Automation**: Send personalized emails, newsletters, and notifications
- **Report Generation**: Create and distribute automated reports and summaries
- **Backup & Archival**: Automate file backups and archival processes
- **API Integration**: Connect different services and automate data flow
- **Content Management**: Automate content creation, processing, and distribution

### Key Features

- 🎬 **Video → Workflow**: Extract workflow steps from screen-capture videos using Gemini AI vision
- 🧾 **Text → Workflow**: Process text-based workflow descriptions with `--from-text`
- 🛠️ **Rich Tool Library**: File I/O, HTTP requests, email, data processing, web scraping, and more
- 🤖 **AI Code Generation**: Produces complete, runnable Python scripts with proper error handling
- 📈 **Auto-Execution**: Generates and runs workflows immediately with detailed logging
- 📁 **Organized Outputs**: All artifacts saved under `data/` directory structure
- 🔧 **Extensible**: Easy to add custom tools and workflow patterns

## Installation

### Prerequisites
- Python 3.8 or higher
- Google Gemini API key (get one at [Google AI Studio](https://makersuite.google.com/app/apikey))

### Setup

1. **Clone the repository:**
```bash
git clone https://github.com/KMeltzer24/workflowmvp.git
```

2. **Install dependencies:**
```bash
pip install -r requirements.txt
```

3. **Set up your Gemini API key:**
```bash
export GEMINI_API_KEY="your-api-key-here"
```

Or create a `.env` file:
```bash
cat > .env << 'EOF'
GEMINI_API_KEY=your-gemini-api-key-here
EOF
```

## Usage

### Quick Start

**From a screen-capture video:**
```bash
python main.py data/workflow_videos/my_task.mp4
```

**From a text workflow:**
```bash
python main.py data/workflow_texts/my_workflow.txt --from-text
```

**Generate without running (--no-run flag):**
```bash
# Generate the Python code but don't execute it
python main.py data/workflow_texts/my_workflow.txt --from-text --no-run

# Then run it manually later
python data/generated_workflows/my_workflow.py
```

### How It Works

1. **Video Processing** (default mode):
   - Extracts representative frames from your video
   - Uses Gemini AI to analyze the UI and infer workflow steps
   - Saves the inferred workflow as text
   - Generates executable Python code
   - Runs the workflow immediately

2. **Text Processing** (`--from-text` mode):
   - Reads your text-based workflow description
   - Parses it into structured steps
   - Generates executable Python code
   - Runs the workflow immediately

### Example Workflows

**File Management:**
```bash
# Create a video of you organizing files, then:
python main.py data/workflow_videos/file_organization.mp4
```

**Web Scraping:**
```bash
# Create a text file describing your scraping workflow:
echo "1. Download data from https://example.com/api/data
2. Process the JSON response
3. Save results to data/results.json
4. Send email notification with summary" > data/workflow_texts/scrape_data.txt

python main.py data/workflow_texts/scrape_data.txt --from-text
```

**Data Processing:**
```bash
# Create a video of your data analysis process, then:
python main.py data/workflow_videos/data_analysis.mp4
```



## Available Tools

The system includes a comprehensive set of built-in tools for common automation tasks:

### File Operations
- **`read_file`**: Read content from files with custom encoding
- **`write_file`**: Write content to files (creates directories automatically)
- **`list_files`**: List files in directories with optional pattern filtering
- **`create_directory`**: Create directories and subdirectories

### Web & Network
- **`download`**: Download content from URLs with timeout handling
- **`http_request`**: Make HTTP requests (GET, POST, PUT, etc.) with headers and data

### Communication
- **`send_email`**: Send emails via SMTP with interactive setup prompts

### Data Processing
- **`process_data`**: Transform data (uppercase, lowercase, count, reverse, custom operations)

### Utilities
- **`wait`**: Add delays between workflow steps

### Tool Usage Example
```python
from workflowmvp.tools import ToolRegistry

tools = ToolRegistry()

# Download a file
result = tools.get_tool("download").function(
    url="https://example.com/data.csv",
    output_file="data.csv"
)

# Process the data
result = tools.get_tool("process_data").function(
    data="Hello World",
    operation="uppercase"
)

# Send notification
result = tools.get_tool("send_email").function(
    recipient="user@example.com",
    subject="Workflow Complete",
    body="Your data has been processed successfully!"
)
```

## Workflow Text Format

When writing text-based workflows, use simple numbered steps. The system will automatically parse and convert them to executable code:

### Basic File Operations
```
1. Create a directory called "sandbox"
2. Write the text "sample content" to file "sandbox/sample.txt"
3. Read the file "sandbox/sample.txt"
4. List files in the "sandbox" directory
5. Wait for 2 seconds
```

### Web Scraping Workflow
```
1. Download data from https://api.example.com/data
2. Process the JSON response to extract key metrics
3. Write the processed data to "results/analysis.json"
4. Send email to admin@company.com with subject "Data Analysis Complete"
5. Create directory "backups" and move old files there
```

### Email Automation
```
1. Read email addresses from "contacts/email_list.txt"
2. For each address, send personalized email with subject "Monthly Report"
3. Wait 5 seconds between each email
4. Log all sent emails to "logs/email_log.txt"
```

### Data Processing Pipeline
```
1. Download CSV file from https://data.gov/dataset.csv
2. Process the data to filter records from last month
3. Calculate summary statistics
4. Write results to "reports/monthly_summary.txt"
5. Send email notification with the summary
```

## Configuration

### Email Setup
The `send_email` tool supports interactive setup. If email credentials aren't set via environment variables, you'll be prompted:

**Environment Variables (recommended):**
```bash
export GEMINI_API_KEY="your-gemini-api-key-here"
export EMAIL_USER="your-email@gmail.com"
export EMAIL_PASSWORD="your-gmail-app-password"
export EMAIL_FROM="your-email@gmail.com"
export SMTP_SERVER="smtp.gmail.com"
export SMTP_PORT="587"
```

**Gmail Configuration:**
- SMTP server: `smtp.gmail.com`
- Port `587` (STARTTLS, recommended) or `465` (SSL)
- Username: full email address (e.g., `name@gmail.com`)
- Password: Gmail App Password (generate under Google Account → Security → App passwords)

### Required vs Optional
- **GEMINI_API_KEY**: Required for video analysis and code generation
- **Email credentials**: Optional (will prompt if not set)

## How It Works

### Video Processing Pipeline
1. **Frame Extraction**: Samples representative frames from your screen-capture video
2. **AI Analysis**: Uses Gemini AI vision to analyze UI elements and infer workflow steps
3. **Text Generation**: Converts visual analysis into structured text workflow
4. **Code Generation**: Transforms workflow steps into executable Python code
5. **Execution**: Runs the generated script with comprehensive logging

### Text Processing Pipeline
1. **Text Parsing**: Analyzes your workflow description and extracts structured steps
2. **Action Mapping**: Maps natural language to specific tool functions
3. **Code Generation**: Creates executable Python code using the tool registry
4. **Execution**: Runs the generated script with error handling and logging

### Generated Code Features
- Complete Python scripts with proper imports and setup
- Error handling with try-catch blocks
- Comprehensive logging for debugging
- Tool registry integration for all operations
- Main function entry point for easy execution

## Troubleshooting

### Common Issues

**"GEMINI_API_KEY is required"**
- Make sure you've set your Gemini API key as an environment variable
- Get your API key from [Google AI Studio](https://makersuite.google.com/app/apikey)

**"No workflow steps found"**
- For videos: Ensure the video shows clear UI interactions
- For text: Check that your workflow uses numbered steps (1., 2., etc.)

**Email sending fails**
- Use Gmail App Passwords, not your regular password
- Enable 2-factor authentication on your Google account first
- Check that your SMTP settings are correct

**Video processing errors**
- Ensure your video file is in a supported format (MP4, AVI, MOV)
- Check that OpenCV can read your video file

### Getting Help

- Check the generated workflow text in `data/workflow_texts/` to see what the AI inferred
- Review the generated Python code in `data/generated_workflows/` for debugging
- Enable verbose logging by modifying the logging level in the generated code

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

