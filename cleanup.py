#!/usr/bin/env python3
"""
WorkflowMVP Cleanup Script
Cleans up old generated workflow files and temporary outputs
"""

import os
import glob
import time
import shutil

def cleanup_files(verbose=True):
    """Clean up old generated workflow files and temp outputs"""
    current_time = time.time()
    cleanup_count = 0
    
    if verbose:
        print("🧹 Starting cleanup...")
    
    # Clean generated_workflows directory (all files)
    if verbose:
        print("📁 Cleaning generated_workflows directory...")
    for file_path in glob.glob('data/generated_workflows/*.py'):
        try:
            os.unlink(file_path)
            if verbose:
                print(f"  ✅ Deleted: {file_path}")
            cleanup_count += 1
        except Exception as e:
            if verbose:
                print(f"  ❌ Could not delete {file_path}: {e}")
    
    # Clean data/temp_outputs directory
    if verbose:
        print("📁 Cleaning data/temp_outputs directory...")
    for file_path in glob.glob('data/temp_outputs/*'):
        try:
            if os.path.isfile(file_path):
                os.unlink(file_path)
                if verbose:
                    print(f"  ✅ Deleted file: {file_path}")
            elif os.path.isdir(file_path):
                shutil.rmtree(file_path)
                if verbose:
                    print(f"  ✅ Deleted directory: {file_path}")
            cleanup_count += 1
        except Exception as e:
            if verbose:
                print(f"  ❌ Could not delete {file_path}: {e}")
    
    # Clean __pycache__ directories in data folder
    if verbose:
        print("📁 Cleaning __pycache__ directories in data folder...")
    for pycache_dir in glob.glob('data/**/__pycache__', recursive=True):
        try:
            shutil.rmtree(pycache_dir)
            if verbose:
                print(f"  ✅ Deleted __pycache__: {pycache_dir}")
            cleanup_count += 1
        except Exception as e:
            if verbose:
                print(f"  ❌ Could not delete {pycache_dir}: {e}")
    
    if verbose:
        print(f"🎉 Cleanup complete! Removed {cleanup_count} files/directories")
    
    return cleanup_count

if __name__ == "__main__":
    cleanup_files()
