import subprocess
import os
import sys
import signal
import time
from pathlib import Path
import logging

logger = logging.getLogger(__name__)

# Set project root as environment variable
PROJECT_ROOT = str(Path(__file__).parent.absolute())
os.environ["PROJECT_ROOT"] = PROJECT_ROOT

# Add app directory to Python path
app_dir = Path(__file__).parent / "app"
sys.path.insert(0, str(app_dir))
sys.path.append(str(app_dir))

logger.info("Python path:", sys.path)  # Debug print

def run_apps():
    """Run all applications and handle their lifecycle"""
    print("Starting all components...")

    # Create shared directories
    logs_dir = Path(PROJECT_ROOT) / "logs"
    logs_dir.mkdir(exist_ok=True)
    cache_dir = Path(PROJECT_ROOT) / "cache"
    cache_dir.mkdir(exist_ok=True)

    # Start processes
    processes = []
    try:
        # Legacy app
        app_dir = Path(__file__).parent / "app"
        env = os.environ.copy()
        env["PYTHONPATH"] = str(app_dir)
        legacy_process = subprocess.Popen(
            [sys.executable, "main.py"], cwd=app_dir, env=env
        )
        processes.append(("Legacy app (port 5001)", legacy_process))
        print("Legacy app started on port 5001")

        # Schedule Explorer frontend
        frontend_dir = Path(__file__).parent / "app" / "schedule_explorer" / "frontend"
        frontend_process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "schedule_explorer.frontend.static:app",
                "--host",
                "0.0.0.0",
                "--port",
                "8080",
                "--workers",
                "1",
                "--timeout-keep-alive",
                "30",
            ],
            cwd=app_dir,
            env=env,
        )
        processes.append(("Schedule Explorer frontend (port 8080)", frontend_process))
        print("Schedule Explorer frontend started on port 8080")

        # Schedule Explorer backend
        backend_dir = Path(__file__).parent / "app" / "schedule_explorer"
        env = os.environ.copy()
        env["PYTHONPATH"] = str(app_dir)
        backend_process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "backend.main:app",
                "--host",
                "0.0.0.0",
                "--port",
                "8000",
                "--workers",
                "2",
                "--timeout-keep-alive",
                "30",
                "--lifespan",
                "on",
            ],
            cwd=backend_dir,
            env=env,
        )
        processes.append(("Schedule Explorer backend (port 8000)", backend_process))
        print(
            "Schedule Explorer backend started on port 8000 (accessible from outside)"
        )

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
