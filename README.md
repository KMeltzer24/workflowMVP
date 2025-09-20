# WorkflowMVP

🚀 **Advanced Workflow Automation Platform** - Turn screen‑capture videos or text descriptions into executable Python workflows using Google's Gemini AI.

## Description

WorkflowMVP is a comprehensive automation platform that can:
- **Convert screen-capture videos** into executable Python workflows using AI vision
- **Process text-based workflow descriptions** into runnable code
- **Generate complete Python scripts** that automate complex multi-step tasks
- **Execute workflows immediately** with comprehensive logging
- **Provide a modern web interface** for non-technical users
- **Handle advanced data processing** including databases, APIs, and file operations

Perfect for automating repetitive tasks like data pipelines, file management, web scraping, email workflows, database operations, and much more.

### Use Cases

- **Data Pipeline Automation**: Download, process, and distribute data reports
- **Database Operations**: Query, insert, and manage data in SQLite databases
- **File Organization**: Automate file sorting, renaming, and organization tasks
- **Web Scraping**: Extract data from websites and APIs with automated workflows
- **Email Automation**: Send personalized emails, newsletters, and notifications
- **Report Generation**: Create and distribute automated reports and summaries
- **Backup & Archival**: Automate file backups and archival processes
- **API Integration**: Connect different services and automate data flow
- **Content Management**: Automate content creation, processing, and distribution
- **Data Analysis**: Process CSV/JSON data, calculate statistics, and generate insights
- **System Administration**: Run commands, manage files, and send notifications

### Key Features

- 🎬 **Video → Workflow**: Extract workflow steps from screen-capture videos using Gemini AI vision
- 🌐 **Web Interface**: Modern, user-friendly web UI for creating and running workflows
- 🛠️ **Rich Tool Library**: 20+ tools including databases, file operations, data processing, web scraping, and more
- 🤖 **AI Code Generation**: Produces complete, runnable Python scripts with proper error handling
- 📈 **Auto-Execution**: Generates and runs workflows immediately with detailed logging
- 📁 **Organized Outputs**: All artifacts saved under `data/` directory structure
- 🔧 **Extensible**: Easy to add custom tools and workflow patterns
- 📊 **Advanced Data Processing**: CSV/JSON manipulation, database operations, data analysis
- 🎯 **Smart Parsing**: Intelligent workflow step recognition and parameter extraction

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

**Web Interface:**
```bash
# Production mode (no auto-reload)
python3 main.py

# Debug mode (auto-reload on file changes)
python3 main.py --debug

# Open browser to http://localhost:5000
```

For detailed web interface documentation, see [WEB_UI_README.md](WEB_UI_README.md).


### Debug Flag Explanation

The `--debug` flag controls Flask's debug mode:

**Production Mode** (`python3 main.py`):
- ✅ **Stable** - No auto-restarts
- ✅ **Clean output** - No duplicate messages
- ✅ **Performance** - Optimized for production use
- ✅ **Reliable** - Consistent behavior

**Debug Mode** (`python3 main.py --debug`):
- 🔄 **Auto-reload** - Automatically restarts when you change code
- 🐛 **Development** - Perfect for making changes to the web interface
- ⚠️ **Duplicate messages** - Normal Flask behavior (expected)
- 🔧 **Debugging** - Enhanced error messages and debugging info

**When to use each:**
- **Production mode**: For normal usage, demos, or when you don't need code changes
- **Debug mode**: When developing, modifying the web interface, or debugging issues




## Available Tools

The system includes 20+ built-in tools for comprehensive automation:

### File Operations
- **`read_file`**: Read content from files with custom encoding
- **`write_file`**: Write content to files (creates directories automatically)
- **`list_files`**: List files in directories with optional pattern filtering
- **`create_directory`**: Create directories and subdirectories
- **`copy_file`**: Copy files from source to destination
- **`move_file`**: Move files from source to destination
- **`delete_file`**: Delete files safely

### Data Processing
- **`read_csv`**: Read and parse CSV files with custom delimiters
- **`write_csv`**: Write data to CSV files with proper formatting
- **`process_json`**: Extract, filter, and transform JSON data
- **`analyze_data`**: Perform basic data analysis (sum, average, count, min, max)

### Database Operations
- **`sqlite_query`**: Execute SQL queries on SQLite databases
- **`sqlite_insert`**: Insert data into SQLite database tables

### Web & Network
- **`download`**: Download content from URLs with timeout handling
- **`http_request`**: Make HTTP requests (GET, POST, PUT, etc.) with headers and data
- **`scrape_webpage`**: Scrape content from web pages

### Communication
- **`send_email`**: Send emails via SMTP with interactive setup prompts
- **`send_notification`**: Send desktop notifications

### System Operations
- **`run_command`**: Execute system commands with timeout handling

### File Compression
- **`compress_files`**: Create ZIP archives from multiple files
- **`extract_archive`**: Extract files from ZIP archives

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

### Database Operations
```
1. Query users from database table "customers"
2. Calculate total number of customers
3. Insert new customer data into database
4. Generate customer report
5. Send notification "Database updated successfully"
```

### Advanced File Management
```
1. List all files in documents folder
2. Compress important files to backup.zip
3. Move backup.zip to backup folder
4. Delete old temporary files
5. Send notification "Backup completed"
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

### Web Interface
1. **Interactive Creation**: Use the web UI to write workflows in natural language
2. **Real-time Parsing**: See your workflow steps parsed and validated instantly
3. **Tool Browser**: Explore available tools and their capabilities
4. **One-click Generation**: Convert text to Python code with a single click
5. **Live Execution**: Run workflows and see results in real-time

### Video Processing Pipeline
1. **Intelligent Frame Sampling**: Uses advanced algorithms to detect scene changes and important moments
2. **Enhanced AI Analysis**: Uses Gemini AI vision with UI element detection and OCR capabilities
3. **Smart Text Generation**: Converts visual analysis into structured text workflow
4. **Advanced Code Generation**: Transforms workflow steps into executable Python code
5. **Execution**: Runs the generated script with comprehensive logging

### Text Processing Pipeline
1. **Smart Text Parsing**: Analyzes your workflow description with enhanced pattern matching
2. **Intelligent Action Mapping**: Maps natural language to specific tool functions with parameter extraction
3. **Advanced Code Generation**: Creates executable Python code using the expanded tool registry
4. **Execution**: Runs the generated script with error handling and logging


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

**Web interface not loading**
- Make sure Flask is installed: `pip install flask`
- Check that port 5000 is available
- Try accessing `http://localhost:5000` directly
- Use `python3 main.py` to launch the web interface

**Debug mode issues**
- Use `python3 main.py --debug` for development (auto-reload)
- Use `python3 main.py` for production (no auto-reload)
- Debug mode may show duplicate startup messages (this is normal)

**Database operations fail**
- Ensure SQLite database files exist and are writable
- Check file permissions for database operations
- Verify table names and column structures

### Getting Help

- Check the generated workflow text in `data/workflow_texts/` to see what the AI inferred
- Review the generated Python code in `data/generated_workflows/` for debugging
- Use the web interface for real-time error feedback
- Enable verbose logging by modifying the logging level in the generated code

## Development

This project uses Python 3.8+ and follows standard Python packaging conventions.

### Project Structure

```
data/
├── workflow_videos/       # Demo video files (input)
├── generated_workflows/   # Temporary generated Python scripts (auto-cleaned)
└── temp_outputs/          # Workflow execution outputs (auto-cleaned)
workflowmvp/
├── __init__.py            # Package metadata
├── video_to_workflow.py   # Enhanced frame sampling + AI inference with OCR
├── parser.py              # Smart text parsing with 15+ action types
├── agent.py               # Generate Python code (Gemini); enforce main()
└── tools.py               # Expanded tool registry (20+ tools)
web/
├── templates/
│   └── index.html         # Web UI template
└── static/                # Static assets (CSS, JS, images)
    ├── css/
    │   └── style.css      # Web interface styles
    ├── js/
    │   └── app.js         # Web interface JavaScript
    └── images/            # Images and icons
main.py                    # Web interface with Flask server
cleanup.py                 # Cleanup script for temporary files
requirements.txt           # Dependencies including Flask
setup.py                   # Packaging metadata (optional)
WEB_UI_README.md           # Web interface documentation
```

### File Explanations

- **`main.py`**: Complete web interface with Flask server, API endpoints, and debug flag support.
- **`cleanup.py`**: Standalone cleanup script for temporary files. Can be run manually or scheduled.

### File Management

**Temporary Files:**
- Generated workflow files are kept during runtime for re-execution
- Workflow outputs are stored in `data/temp_outputs/` and cleaned up automatically
- All temporary files are cleaned up when the web server shuts down

**Manual Cleanup:**
```bash
# Clean up old files manually
python3 cleanup.py

# Or use the web API
curl -X POST http://localhost:5000/api/cleanup
```
- **`web/templates/index.html`**: Web UI template with interactive workflow creation.
- **`web/static/css/style.css`**: Web interface styles and layout.
- **`web/static/js/app.js`**: Web interface JavaScript functionality.
- **`workflowmvp/video_to_workflow.py`**: Enhanced frame sampling with scene detection, UI element recognition, and OCR capabilities.
- **`workflowmvp/parser.py`**: Smart text parsing with 15+ action types and intelligent parameter extraction.
- **`workflowmvp/agent.py`**: Generates the final Python script using the expanded tool registry and enforces a `main()` entrypoint.
- **`workflowmvp/tools.py`**: Comprehensive tool catalog with 20+ tools including databases, data processing, and system operations.
- **`data/`**: Your inputs (videos), inferred texts, generated scripts, and outputs.
- **`requirements.txt` / `setup.py`**: Dependencies including Flask for web interface.

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

