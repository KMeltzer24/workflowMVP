"""
WorkflowMVP - A Python project with a Web interface that uses an AI-powered workflow creation process
"""

import os
import sys
import json
import subprocess
import tempfile
import signal
import argparse

# Suppress gRPC and ALTS warnings
os.environ['GRPC_VERBOSITY'] = 'ERROR'
os.environ['GRPC_TRACE'] = ''
os.environ['GLOG_minloglevel'] = '2'
from flask import Flask, render_template, request, jsonify  
from workflowmvp.tools import ToolRegistry
from workflowmvp.parser import WorkflowParser
from workflowmvp.agent import WorkflowAgent
from dotenv import load_dotenv  

# Load environment variables from .env file
load_dotenv()

# Create Flask app
app = Flask(__name__, template_folder='web/templates', static_folder='web/static')

def cleanup_on_exit():
    """Clean up temporary files when server shuts down"""
    # Check if we're in debug mode
    debug_mode = '--debug' in sys.argv
    
    if debug_mode:
        print("\n🧹 Cleaning up temporary files...")
    
    # Import and call the cleanup function from cleanup.py
    from cleanup import cleanup_files
    cleanup_files(verbose=debug_mode)


def signal_handler(signum, frame):
    """Handle shutdown signals"""
    # Check if we're in debug mode
    debug_mode = '--debug' in sys.argv
    
    if debug_mode:
        print(f"\n🛑 Received signal {signum}, shutting down...")
    else:
        print()  # Just add a newline for clean exit
    
    cleanup_on_exit()
    exit(0)

# Register signal handlers
signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)

# Flask routes
@app.route('/')
def index():
    """Main page with workflow creation interface"""
    return render_template('index.html')

@app.route('/api/tools')
def get_tools():
    """Get list of available tools"""
    registry = ToolRegistry()
    tools = []
    for tool in registry.list_tools():
        tools.append({
            'name': tool.name,
            'description': tool.description,
            'parameters': tool.parameters
        })
    return jsonify(tools)

@app.route('/api/parse-workflow', methods=['POST'])
def parse_workflow():
    """Parse workflow text and return structured steps"""
    try:
        workflow_text = request.json.get('workflow_text', '')
        parser = WorkflowParser()
        steps = parser.parse_workflow(workflow_text)
        
        result = []
        for step in steps:
            result.append({
                'step_id': step.step_id,
                'description': step.description,
                'action': step.action,
                'parameters': step.parameters,
                'dependencies': step.dependencies
            })
        
        return jsonify({'success': True, 'steps': result})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/parse-video', methods=['POST'])
def parse_video():
    """Process uploaded video and return workflow steps"""
    try:
        # Check if we're in debug mode
        debug_mode = '--debug' in sys.argv
        if 'video' not in request.files:
            return jsonify({'success': False, 'error': 'No video file provided'})
        
        video_file = request.files['video']
        if video_file.filename == '':
            return jsonify({'success': False, 'error': 'No video file selected'})
        
        # Save uploaded video to temporary file
        with tempfile.NamedTemporaryFile(delete=False, suffix='.mp4') as tmp_file:
            video_file.save(tmp_file.name)
            video_path = tmp_file.name
        
        # Process video to get workflow text directly
        api_key = os.getenv('GEMINI_API_KEY')
        if not api_key:
            return jsonify({'success': False, 'error': 'GEMINI_API_KEY not found in environment'})
        
        # Use the video processing function to get workflow text directly
        from workflowmvp.video_to_workflow import sample_frames_intelligent, infer_workflow_from_frames
        import contextlib
        import io
        
        try:
            # Suppress output in non-debug mode
            if not debug_mode:
                # Redirect stdout to suppress video processing output
                with contextlib.redirect_stdout(io.StringIO()):
                    # Extract frames from video
                    frames, temp_dir = sample_frames_intelligent(video_path, max_frames=15)
                    if not frames:
                        return jsonify({'success': False, 'error': 'No frames could be extracted from the video'})
                    
                    # Generate workflow text from frames
                    workflow_text = infer_workflow_from_frames(frames, api_key)
                    if not workflow_text or len(workflow_text.strip()) < 10:
                        return jsonify({'success': False, 'error': 'AI analysis produced no meaningful workflow'})
            else:
                # Debug mode - show all output
                # Extract frames from video
                frames, temp_dir = sample_frames_intelligent(video_path, max_frames=15)
                if not frames:
                    return jsonify({'success': False, 'error': 'No frames could be extracted from the video'})
                
                # Generate workflow text from frames
                workflow_text = infer_workflow_from_frames(frames, api_key)
                if not workflow_text or len(workflow_text.strip()) < 10:
                    return jsonify({'success': False, 'error': 'AI analysis produced no meaningful workflow'})
            
            # Parse the workflow text to get structured steps
            parser = WorkflowParser()
            steps = parser.parse_workflow(workflow_text)
            
            # Convert to JSON-serializable format
            result = []
            for step in steps:
                result.append({
                    'step_id': step.step_id,
                    'description': step.description,
                    'action': step.action,
                    'parameters': step.parameters,
                    'dependencies': step.dependencies
                })
            
            return jsonify({'success': True, 'steps': result, 'workflow_text': workflow_text})
            
        except Exception as e:
            return jsonify({'success': False, 'error': str(e)})
        finally:
            # Clean up temporary files
            if os.path.exists(video_path):
                os.unlink(video_path)
            if 'temp_dir' in locals() and temp_dir and os.path.exists(temp_dir):
                import shutil
                shutil.rmtree(temp_dir)
                
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/generate-workflow', methods=['POST'])
def generate_workflow():
    """Generate Python code from workflow steps"""
    try:
        steps_data = request.json.get('steps', [])
        workflow_name = request.json.get('name', 'generated_workflow')
        
        
        # Convert back to WorkflowStep objects
        from workflowmvp.parser import WorkflowStep
        steps = []
        for step_data in steps_data:
            step = WorkflowStep(
                step_id=step_data['step_id'],
                description=step_data['description'],
                action=step_data['action'],
                parameters=step_data['parameters'],
                dependencies=step_data['dependencies']
            )
            steps.append(step)
        
        # Generate code with timestamp for uniqueness
        import time
        timestamp = int(time.time())
        output_path = f"data/generated_workflows/{workflow_name}_{timestamp}.py"
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        
        
        agent = WorkflowAgent(api_key=os.getenv('GEMINI_API_KEY'), model='gemini-1.5-flash')
        generated_code = agent.generate_workflow_code(steps, output_path)
        
        return jsonify({
            'success': True, 
            'output_path': output_path,
            'message': 'Workflow generated successfully'
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/run-workflow', methods=['POST'])
def run_workflow():
    """Run a generated workflow"""
    try:
        workflow_path = request.json.get('workflow_path', '')
        
        if not os.path.exists(workflow_path):
            return jsonify({'success': False, 'error': 'Workflow file not found'})
        
        # Change to data/temp_outputs directory for workflow execution
        original_cwd = os.getcwd()
        temp_dir = os.path.join(original_cwd, 'data', 'temp_outputs')
        os.makedirs(temp_dir, exist_ok=True)
        os.chdir(temp_dir)
        
        try:
            # Run the workflow
            result = subprocess.run(
                ['python3', os.path.join(original_cwd, workflow_path)],
                capture_output=True,
                text=True,
                timeout=60
            )
            
            return jsonify({
                'success': result.returncode == 0,
                'stdout': result.stdout,
                'stderr': result.stderr,
                'returncode': result.returncode
            })
        finally:
            # Always change back to original directory
            os.chdir(original_cwd)
                
    except subprocess.TimeoutExpired:
        return jsonify({'success': False, 'error': 'Workflow timed out'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/cleanup', methods=['POST'])
def cleanup_files_api():
    """Clean up all generated workflow files and temp outputs"""
    try:
        # Check if we're in debug mode
        debug_mode = '--debug' in sys.argv
        
        # Import and call the cleanup function from cleanup.py
        from cleanup import cleanup_files
        cleanup_count = cleanup_files(verbose=debug_mode)
        
        return jsonify({
            'success': True,
            'message': f'Cleaned up {cleanup_count} files',
            'files_cleaned': cleanup_count
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/examples')
def get_examples():
    """Get example workflows"""
    examples = [
        {
            'name': 'Bitcoin Price Alert',
            'description': 'Download Bitcoin price and send email notification',
            'workflow': '''1. Download Bitcoin price from https://api.coinbase.com/v2/exchange-rates?currency=BTC
2. Extract the USD price from the JSON response
3. Send email to admin@company.com with subject "Bitcoin Price Alert"
4. Include the current price in the email body'''
        },
        {
            'name': 'Data Processing Pipeline',
            'description': 'Process CSV data and generate report',
            'workflow': '''1. Read data from users.csv file
2. Calculate total number of users
3. Calculate average age of users
4. Write results to report.txt file
5. Send notification "Data processing complete"'''
        },
        {
            'name': 'File Backup',
            'description': 'Backup important files to archive',
            'workflow': '''1. List all files in documents folder
2. Compress important files to backup.zip
3. Move backup.zip to backup folder
4. Send notification "Backup completed successfully"'''
        }
    ]
    return jsonify(examples)

def main():
    """Main entry point - launches the web interface"""
    parser = argparse.ArgumentParser(description='WorkflowMVP - Web Interface')
    parser.add_argument('--debug', action='store_true', help='Enable debug mode (auto-reload on file changes)')
    
    args = parser.parse_args()
    
    print("🚀 WorkflowMVP - Web Interface")
    print("🌐 Starting web server...")
    print("📱 Open your browser to: http://localhost:5000")
    print("🛑 Press Ctrl+C to stop")
    if args.debug:
        print("🐛 Debug mode: ON (auto-reload enabled)")
    else:
        print("ℹ️  Debug mode: OFF (use --debug to enable)")
    print()
    
    # Start the Flask app
    if args.debug:
        app.run(debug=True, host='0.0.0.0', port=5000)
    else:
        # Suppress development server warning and HTTP requests in production mode
        import warnings
        import logging
        log = logging.getLogger('werkzeug')
        log.setLevel(logging.ERROR)
        
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            app.run(debug=False, host='0.0.0.0', port=5000)

if __name__ == "__main__":
    main()