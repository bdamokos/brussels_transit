import logging
import os
from pathlib import Path


def setup_logging():
    """Configure logging for the schedule explorer application."""
    # Create logs directory next to our backend directory
    current_path = Path(os.path.dirname(os.path.abspath(__file__)))
    logs_dir = current_path.parent / "logs"

    # Create logs directory if it doesn't exist
    logs_dir.mkdir(exist_ok=True)

    # Configure logging
    logger = logging.getLogger("schedule_explorer")
    logger.setLevel(logging.DEBUG)

    # Prevent duplicate handlers
    if not logger.handlers:
        # File handler for detailed logging
        file_handler = logging.FileHandler(logs_dir / "schedule_explorer.log")
        file_handler.setLevel(logging.DEBUG)
        file_formatter = logging.Formatter(
            "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
        )
        file_handler.setFormatter(file_formatter)
        file_handler.maxBytes = 10 * 1024 * 1024  # 10 MB

        # Console handler for important messages
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.DEBUG)
        console_formatter = logging.Formatter(
            "%(levelname)s: \t %(asctime)s - %(message)s"
        )
        console_handler.setFormatter(console_formatter)

        # Add handlers
        logger.addHandler(file_handler)
        logger.addHandler(console_handler)

    return logger


def bytes_to_mb(bytes: int, precision: int = 2) -> int:
    """Convert bytes to megabytes."""
    return round(bytes / (1024 * 1024), precision)
