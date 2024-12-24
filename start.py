import threading
import subprocess
import os
import sys
from pathlib import Path

def run_legacy_app():
    """Run the legacy app on port 5001"""
    os.chdir(Path(__file__).parent / "app")
    subprocess.run([sys.executable, "main.py"], check=True)

def run_schedule_explorer_frontend():
    """Run the schedule explorer frontend on port 8080"""
    frontend_dir = Path(__file__).parent / "app" / "schedule_explorer" / "frontend"
    os.chdir(frontend_dir)
    subprocess.run([sys.executable, "-m", "http.server", "8080", "--directory", "."], check=True)

def run_schedule_explorer_backend():
    """Run the schedule explorer backend with uvicorn"""
    backend_dir = Path(__file__).parent / "app" / "schedule_explorer"
    os.chdir(backend_dir)
    subprocess.run([sys.executable, "-m", "uvicorn", "backend.main:app", "--reload", "--port", "8000"], check=True)

def main():
    # Create threads for each component
    legacy_thread = threading.Thread(target=run_legacy_app, name="legacy_app")
    frontend_thread = threading.Thread(target=run_schedule_explorer_frontend, name="schedule_explorer_frontend")
    backend_thread = threading.Thread(target=run_schedule_explorer_backend, name="schedule_explorer_backend")

    # Start all threads
    print("Starting all components...")
    legacy_thread.start()
    print("Legacy app started on port 5001")
    frontend_thread.start()
    print("Schedule Explorer frontend started on port 8080")
    backend_thread.start()
    print("Schedule Explorer backend started on port 8000")

    try:
        # Wait for all threads to complete (which they won't unless there's an error)
        legacy_thread.join()
        frontend_thread.join()
        backend_thread.join()
    except KeyboardInterrupt:
        print("\nShutting down all components...")
        sys.exit(0)

if __name__ == "__main__":
    main() 