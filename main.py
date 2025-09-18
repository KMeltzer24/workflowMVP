#!/usr/bin/env python3
"""
WorkflowMVP - A Python project for automated workflow generation
"""

import os
import sys
import argparse
from pathlib import Path
from workflowmvp.parser import WorkflowParser
from workflowmvp.agent import WorkflowAgent
from workflowmvp.video_to_workflow import video_to_workflow_txt


def main():
    """Main entry point for the application"""
    parser = argparse.ArgumentParser(description='WorkflowMVP - Generate executable workflows from text descriptions')
    parser.add_argument('workflow_file', help='Path to the workflow description file (.txt). If --from-video is used, this will be the output .txt path.')
    parser.add_argument('--from-video', help='Path to a screen capture video to infer workflow from')
    parser.add_argument('-o', '--output', default='generated_workflow.py', 
                       help='Output file for generated Python code (default: generated_workflow.py)')
    parser.add_argument('--run', action='store_true', 
                       help='Run the generated workflow immediately')
    parser.add_argument('--api-key', help='Gemini API key (or set GEMINI_API_KEY env var)')
    parser.add_argument('--model', default='gemini-1.5-flash', 
                       help='Gemini model to use (default: gemini-1.5-flash)')
    
    args = parser.parse_args()
    
    # Check if workflow file exists
    if not os.path.exists(args.workflow_file):
        print(f"Error: Workflow file '{args.workflow_file}' not found")
        sys.exit(1)
    
    print("🚀 WorkflowMVP - Automated Workflow Generator")
    print("=" * 50)
    
    try:
        # Optional: Infer workflow from video first
        if args.from_video:
            print(f"🎬 Inferring workflow from video: {args.from_video}")
            api_key = args.api_key or os.getenv('GEMINI_API_KEY')
            if not api_key:
                print("Error: GEMINI_API_KEY is required to infer from video")
                sys.exit(1)
            inferred_path = video_to_workflow_txt(args.from_video, args.workflow_file, api_key=api_key, model=args.model)
            print(f"✅ Inferred workflow saved to: {inferred_path}")
        
        # Step 1: Read workflow description
        print(f"📖 Reading workflow from: {args.workflow_file}")
        with open(args.workflow_file, 'r', encoding='utf-8') as f:
            workflow_text = f.read()
        
        # Step 2: Parse workflow steps
        print("🔍 Parsing workflow steps...")
        parser = WorkflowParser()
        steps = parser.parse_workflow(workflow_text)
        
        if not steps:
            print("❌ No workflow steps found in the file")
            sys.exit(1)
        
        print(f"✅ Found {len(steps)} workflow steps:")
        for i, step in enumerate(steps, 1):
            print(f"   {i}. {step.description}")
        
        # Step 3: Generate executable code
        print("🤖 Generating executable code...")
        agent = WorkflowAgent(api_key=args.api_key, model=args.model)
        generated_code = agent.generate_workflow_code(steps, args.output)
        
        print(f"✅ Generated workflow code: {args.output}")
        
        # Step 4: Optionally run the workflow
        if args.run:
            print("🏃 Running generated workflow...")
            print("-" * 30)
            
            # Import and run the generated module
            import importlib.util
            spec = importlib.util.spec_from_file_location("generated_workflow", args.output)
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
            print(f"\n💡 To run the workflow: python {args.output}")
            print("   Or use: python main.py <workflow_file> --run")
    
    except KeyboardInterrupt:
        print("\n⏹️  Workflow generation cancelled by user")
        sys.exit(1)
    except Exception as e:
        print(f"❌ Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
