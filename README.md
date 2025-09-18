# WorkflowMVP

🚀 **Automated Workflow Generator** - Transform text descriptions into executable Python programs using Google's Gemini AI.

## Description

WorkflowMVP is a powerful Python tool that takes natural language workflow descriptions and automatically generates executable Python programs. It uses Google's Gemini AI to understand your workflow requirements and creates code that calls the necessary tools to execute your tasks.

### Key Features

- 📝 **Natural Language Processing**: Describe workflows in plain English
- 🤖 **AI-Powered Code Generation**: Uses Google's Gemini AI to generate executable code
- 🛠️ **Rich Tool Library**: Built-in tools for common operations (HTTP requests, file I/O, email, etc.)
- 🔄 **Dependency Resolution**: Automatically handles step dependencies
- 📊 **Progress Tracking**: Built-in logging and error handling
- 🎯 **Flexible Output**: Generate standalone Python scripts

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

**One-liner:**
```bash
export GEMINI_API_KEY="your-api-key-here" && python main.py data/workflow_inputs/my_workflow.txt -o data/generated_workflows/run_workflow.py --run
```

## Workflow Description Format

Write your workflows in plain text using numbered steps or bullet points:

### Example 1: Simple Data Processing
```
Simple Data Processing Workflow

1. Download data from https://jsonplaceholder.typicode.com/posts/1
2. Read the downloaded data and process it to extract the title
3. Write the processed title to a file called "output.txt"
4. Wait for 2 seconds
5. Send an email notification that the workflow is complete
```

### Example 2: File Processing
```
File Processing Workflow

Step 1: Create a directory called "processed_files"
Step 2: Download a sample file from https://httpbin.org/json
Step 3: Read the downloaded file content
Step 4: Process the data to convert it to uppercase
Step 5: Write the processed data to a new file
Step 6: List all files in the processed_files directory
```

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

Place your workflow descriptions under `data/workflow_inputs/`. A simple example:

```
1. Create a directory called "sandbox"
2. Write the text "sample content" to file "sandbox/sample.txt"
3. Read the file "sandbox/sample.txt"
4. List files in the "sandbox" directory
5. Wait for 2 seconds
```

## How It Works

1. **Parse**: The system parses your text description into structured workflow steps
2. **Analyze**: Each step is analyzed to determine the appropriate action and parameters
3. **Generate**: An AI agent generates executable Python code using the available tools
4. **Execute**: The generated code can be run immediately or saved for later use

## Development

This project uses Python 3.8+ and follows standard Python packaging conventions.

### Project Structure

```
data/
├── workflow_inputs/     # Your workflow .txt inputs
├── generated_workflows/ # Generated workflow scripts
└── outputs/            # Other output files
workflowmvp/
├── __init__.py         # Package initialization (required for Python imports)
├── parser.py           # Workflow text parser
├── agent.py            # Gemini AI agent for code generation
├── tools.py            # Tool registry and implementations
main.py                 # CLI entry point
requirements.txt        # Dependencies
setup.py                # Package metadata (for pip install -e .)
```

### File Explanations

- **`workflowmvp/__init__.py`**: Required for Python to recognize `workflowmvp` as a package. Allows imports like `from workflowmvp.parser import WorkflowParser`
- **`setup.py`**: Package metadata for installation. Allows `pip install -e .` to install the package in development mode
- **`data/`**: Contains all user data (inputs, generated workflows, outputs)

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

