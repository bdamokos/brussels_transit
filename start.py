import subprocess
import os
import sys
import signal
import time
from pathlib import Path

def run_apps():
    """Run all applications and handle their lifecycle"""
    print("Starting all components...")
    
    # Start processes
    processes = []
    try:
        # Legacy app
        app_dir = Path(__file__).parent / "app"
        legacy_process = subprocess.Popen(
            [sys.executable, "main.py"],
            cwd=app_dir
        )
        processes.append(('Legacy app (port 5001)', legacy_process))
        print("Legacy app started on port 5001")

        # Schedule Explorer frontend
        frontend_dir = Path(__file__).parent / "app" / "schedule_explorer" / "frontend"
        frontend_process = subprocess.Popen(
            [sys.executable, "-m", "http.server", "8080", "--directory", "."],
            cwd=frontend_dir
        )
        processes.append(('Schedule Explorer frontend (port 8080)', frontend_process))
        print("Schedule Explorer frontend started on port 8080")

        # Schedule Explorer backend
        backend_dir = Path(__file__).parent / "app" / "schedule_explorer"
        backend_process = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "backend.main:app", "--port", "8000"],
            cwd=backend_dir
        )
        processes.append(('Schedule Explorer backend (port 8000)', backend_process))
        print("Schedule Explorer backend started on port 8000")

        # Wait for processes and handle their exit
        while True:
            time.sleep(1)
            for name, process in processes:
                if process.poll() is not None:
                    print(f"{name} exited with code {process.returncode}")
                    return  # Exit if any process dies

    except KeyboardInterrupt:
        print("\nShutting down all components...")
        
        # First try SIGTERM
        for name, process in processes:
            if process.poll() is None:  # If process is still running
                print(f"Stopping {name}...")
                process.terminate()
        
        # Give processes time to shut down gracefully
        time.sleep(2)
        
        # Force kill any remaining processes
        for name, process in processes:
            if process.poll() is None:  # If still running
                print(f"Force killing {name}...")
                process.kill()
                process.wait()  # Ensure process is dead
    
    finally:
        # Final cleanup - make absolutely sure all processes are dead
        for name, process in processes:
            try:
                if process.poll() is None:
                    process.kill()
                    process.wait()
            except:
                pass

if __name__ == "__main__":
    run_apps() 