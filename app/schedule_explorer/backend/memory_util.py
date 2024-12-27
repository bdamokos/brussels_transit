from pathlib import Path
import psutil
import logging
from .logging_config import setup_logging

logger = setup_logging()

def check_memory_for_file(file_path: Path, safety_factor: float = 2.0) -> bool:
    """
    Check if there's enough memory to safely load a file with low_memory=False.
    
    Args:
        file_path: Path to the CSV file
        safety_factor: Multiply file size by this factor to ensure enough buffer (default 2.0)
    
    Returns:
        bool: True if there's enough memory, False otherwise
    """
    try:
        # Get file size in bytes
        file_size = file_path.stat().st_size
        
        # Get available system memory
        available_memory = psutil.virtual_memory().available
        
        # Estimate memory needed (file size * safety factor)
        # CSV data typically expands in memory due to parsing and pandas overhead
        estimated_memory_needed = file_size * safety_factor
        
        logger.debug(f"File size: {file_size / 1024 / 1024:.1f}MB")
        logger.debug(f"Available memory: {available_memory / 1024 / 1024:.1f}MB")
        logger.debug(f"Estimated memory needed: {estimated_memory_needed / 1024 / 1024:.1f}MB")
        
        return available_memory > estimated_memory_needed
        
    except Exception as e:
        logger.warning(f"Error checking memory availability: {e}")
        return False