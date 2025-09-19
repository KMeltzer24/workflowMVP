#!/usr/bin/env python3
"""
WorkflowMVP - A Python project for automated workflow generation
"""

import os
import sys
import argparse
from pathlib import Path
from dotenv import load_dotenv
from workflowmvp.parser import WorkflowParser
from workflowmvp.agent import WorkflowAgent
from workflowmvp.video_to_workflow import video_to_workflow_txt

# Load environment variables from .env file
load_dotenv()


def main():
    """Main entry point for the application"""
    parser = argparse.ArgumentParser(description='WorkflowMVP - Generate and run workflows (video by default, or text with --from-text)')
    parser.add_argument('input', help='Path to a screen-capture video (default). Use --from-text to pass a .txt workflow instead')
    parser.add_argument('--from-text', action='store_true', help='Treat the positional argument as a .txt workflow instead of a video')
    parser.add_argument('--no-run', action='store_true', help='Generate the Python workflow code but do not execute it')

    args = parser.parse_args()

    if args.from_text:
        # Validate text exists
        workflow_txt_path = args.input
        if not os.path.exists(workflow_txt_path):
            print(f"Error: Workflow file '{workflow_txt_path}' not found")
            sys.exit(1)
        base_name = Path(workflow_txt_path).stem
        output_path = os.path.join('data', 'generated_workflows', f'{base_name}.py')
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
    else:
        # Video mode (default)
        if not os.path.exists(args.input):
            print(f"Error: Video file '{args.input}' not found")
            sys.exit(1)
        base_name = Path(args.input).stem
        workflow_txt_path = os.path.join('data', 'workflow_texts', f'{base_name}.txt')
        output_path = os.path.join('data', 'generated_workflows', f'{base_name}.py')
        os.makedirs(os.path.dirname(workflow_txt_path), exist_ok=True)
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
    
    print("🚀 WorkflowMVP - Automated Workflow Generator")
    
    try:
        # Maybe infer from video (default path)
        if not args.from_text:
            print(f"🎬 Inferring workflow from video: {args.input}")
            api_key = os.getenv('GEMINI_API_KEY')
            if not api_key:
                print("Error: GEMINI_API_KEY is required to infer from video")
                sys.exit(1)
            inferred_path = video_to_workflow_txt(args.input, workflow_txt_path, api_key=api_key, model='gemini-1.5-flash')
            print(f"✅ Inferred workflow saved to: {inferred_path}")
        else:
            inferred_path = workflow_txt_path

        # Step 1: Read workflow description
        with open(inferred_path, 'r', encoding='utf-8') as f:
            workflow_text = f.read()
        
        # Step 2: Parse workflow steps
        print("🔍 Parsing workflow steps...")
        parser = WorkflowParser()
        steps = parser.parse_workflow(workflow_text)
        
        if not steps:
            print("❌ No workflow steps found in the file")
            sys.exit(1)
        
        print(f"✅ Found {len(steps)} workflow steps")
        
        # Step 3: Generate executable code
        print("🤖 Generating executable code...")
        agent = WorkflowAgent(api_key=os.getenv('GEMINI_API_KEY'), model='gemini-1.5-flash')
        generated_code = agent.generate_workflow_code(steps, output_path)
        
        print(f"✅ Generated workflow code: {output_path}")
        
        # Step 4: Optionally run the workflow
        if not args.no_run:
            print("🏃 Running generated workflow...")
            
            # Import and run the generated module
            import importlib.util
            spec = importlib.util.spec_from_file_location("generated_workflow", output_path)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            
            # Run the main function (check for main() or execute_workflow())
            if hasattr(module, 'main'):
                results = module.main()
                print("\n🎉 Workflow execution completed!")
                return results
            elif hasattr(module, 'execute_workflow'):
                results = module.execute_workflow()
                print("\n🎉 Workflow execution completed!")
                return results
            else:
                print("❌ Generated code doesn't have a main() or execute_workflow() function")
                sys.exit(1)
        else:
            print(f"\n💡 To run the workflow later: python3 {output_path}")
            print(f"📁 Generated files:")
            if not args.from_text:
                print(f"   - Workflow text: {workflow_txt_path}")
            print(f"   - Python script: {output_path}")
    
    except KeyboardInterrupt:
        print("\n⏹️  Workflow generation cancelled by user")
        sys.exit(1)
    except Exception as e:
        print(f"❌ Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
