import time
import psutil
import json
import subprocess
from pathlib import Path
from functools import wraps
from typing import Callable, Dict, Any
from datetime import datetime

def get_power_source() -> Dict[str, Any]:
    """Get the current power source information for macOS."""
    try:
        # Run pmset -g batt
        result = subprocess.run(['pmset', '-g', 'batt'], capture_output=True, text=True)
        output = result.stdout
        
        # Parse the output
        power_info = {
            "on_battery": False,
            "battery_percent": None,
            "time_remaining": None,
            "power_source": "Unknown"
        }
        
        if "AC Power" in output:
            power_info["power_source"] = "AC Power"
        elif "Battery Power" in output:
            power_info["power_source"] = "Battery Power"
            power_info["on_battery"] = True
            
        # Try to extract battery percentage
        import re
        percent_match = re.search(r'(\d+)%', output)
        if percent_match:
            power_info["battery_percent"] = int(percent_match.group(1))
            
        # Try to extract time remaining
        time_match = re.search(r'(\d+:\d+) remaining', output)
        if time_match:
            power_info["time_remaining"] = time_match.group(1)
            
        return power_info
    except Exception as e:
        return {
            "power_source": f"Error detecting power source: {str(e)}",
            "on_battery": None,
            "battery_percent": None,
            "time_remaining": None
        }

def get_directory_size(path: Path) -> Dict[str, int]:
    """Calculate total size and individual file sizes in a directory."""
    total_size = 0
    file_sizes = {}
    
    for file in path.glob('*.txt'):
        size = file.stat().st_size
        file_sizes[file.name] = size
        total_size += size
    
    return {
        "total_size_bytes": total_size,
        "file_sizes_bytes": file_sizes
    }

def measure_performance(func: Callable) -> Callable:
    """
    Decorator to measure execution time and memory usage of a function.
    Records start/peak/end memory usage and execution time.
    """
    @wraps(func)
    def wrapper(*args, **kwargs) -> tuple[Any, Dict]:
        process = psutil.Process()
        peak_memory = 0
        
        # Get power source information before starting
        power_info = get_power_source()
        
        # Start measurements
        start_time = time.time()
        start_memory = process.memory_info().rss / 1024 / 1024  # MB
        
        # Monitor peak memory during execution
        def memory_monitor():
            nonlocal peak_memory
            current = process.memory_info().rss / 1024 / 1024
            peak_memory = max(peak_memory, current)
            return current
        
        # Execute function with periodic memory checks
        result = func(*args, **kwargs)
        memory_monitor()  # One final check
        
        # End measurements
        end_time = time.time()
        end_memory = process.memory_info().rss / 1024 / 1024  # MB
        
        # Get input data size if applicable
        input_size = {}
        if args and isinstance(args[0], (str, Path)):
            data_dir = Path(args[0])
            if data_dir.is_dir():
                input_size = get_directory_size(data_dir)
        
        # Get output size if result is bytes (serialized data)
        output_size = len(result) if isinstance(result, bytes) else None
        
        # Get CPU frequency
        cpu_freq = psutil.cpu_freq()
        cpu_info = {
            "current_freq_mhz": cpu_freq.current if cpu_freq else None,
            "min_freq_mhz": cpu_freq.min if cpu_freq else None,
            "max_freq_mhz": cpu_freq.max if cpu_freq else None
        }
        
        # Collect metrics
        metrics = {
            "function_name": func.__name__,
            "execution_time_seconds": end_time - start_time,
            "start_memory_mb": start_memory,
            "end_memory_mb": end_memory,
            "memory_change_mb": end_memory - start_memory,
            "peak_memory_mb": peak_memory or end_memory,  # fallback to end_memory if peak not captured
            "timestamp": datetime.now().isoformat(),
            "input_size": input_size,
            "output_size_bytes": output_size,
            "power_source": power_info,
            "cpu_info": cpu_info
        }
        
        return result, metrics
    
    return wrapper

def save_metrics(metrics: Dict, output_dir: str = "performance_metrics") -> None:
    """Save performance metrics to a JSON file."""
    output_path = Path(output_dir)
    output_path.mkdir(exist_ok=True)
    
    # Create filename with timestamp and function name
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"{metrics['function_name']}_{timestamp}.json"
    
    with open(output_path / filename, 'w') as f:
        json.dump(metrics, f, indent=2)

def print_metrics(metrics: Dict) -> None:
    """Print performance metrics in a readable format."""
    print(f"\nPerformance Metrics for {metrics['function_name']}:")
    
    # Power source information
    power_info = metrics.get('power_source', {})
    print("\nPower Source:")
    print(f"  Source: {power_info.get('power_source', 'Unknown')}")
    if power_info.get('battery_percent') is not None:
        print(f"  Battery: {power_info['battery_percent']}%")
    if power_info.get('time_remaining'):
        print(f"  Time Remaining: {power_info['time_remaining']}")
    
    # CPU information
    cpu_info = metrics.get('cpu_info', {})
    if cpu_info.get('current_freq_mhz'):
        print("\nCPU Frequency:")
        print(f"  Current: {cpu_info['current_freq_mhz']:.0f} MHz")
        print(f"  Min: {cpu_info['min_freq_mhz']:.0f} MHz")
        print(f"  Max: {cpu_info['max_freq_mhz']:.0f} MHz")
    
    print(f"\nExecution Time: {metrics['execution_time_seconds']:.2f} seconds")
    print(f"Memory Usage:")
    print(f"  Start: {metrics['start_memory_mb']:.2f} MB")
    print(f"  End:   {metrics['end_memory_mb']:.2f} MB")
    print(f"  Change: {metrics['memory_change_mb']:.2f} MB")
    print(f"  Peak:  {metrics['peak_memory_mb']:.2f} MB")
    
    if metrics.get('input_size'):
        total_mb = metrics['input_size']['total_size_bytes'] / (1024 * 1024)
        print(f"\nInput GTFS Size: {total_mb:.2f} MB")
        print("Individual file sizes:")
        for file, size in metrics['input_size']['file_sizes_bytes'].items():
            print(f"  {file}: {size / 1024:.2f} KB")
    
    if metrics.get('output_size_bytes'):
        output_mb = metrics['output_size_bytes'] / (1024 * 1024)
        print(f"\nOutput Size: {output_mb:.2f} MB")
        if metrics.get('input_size'):
            compression_ratio = metrics['input_size']['total_size_bytes'] / metrics['output_size_bytes']
            print(f"Compression Ratio: {compression_ratio:.2f}x") 