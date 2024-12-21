import json
from pathlib import Path
from collections import defaultdict
from typing import Dict, List
import statistics
from datetime import datetime

def load_metrics_files(metrics_dir: str = "performance_metrics") -> Dict[str, List[Dict]]:
    """Load all metrics files and group them by function name."""
    metrics_by_function = defaultdict(list)
    metrics_path = Path(metrics_dir)
    
    if not metrics_path.exists():
        print(f"No metrics directory found at {metrics_dir}")
        return {}
    
    for file in metrics_path.glob("*.json"):
        try:
            with open(file, 'r') as f:
                metrics = json.load(f)
                metrics_by_function[metrics['function_name']].append(metrics)
        except Exception as e:
            print(f"Error loading {file}: {e}")
    
    return metrics_by_function

def calculate_statistics(metrics_list: List[Dict]) -> Dict:
    """Calculate statistics for a list of metrics."""
    if not metrics_list:
        return {}
    
    # Extract values for different metrics
    execution_times = [m['execution_time_seconds'] for m in metrics_list]
    memory_changes = [m['memory_change_mb'] for m in metrics_list]
    peak_memories = [m['peak_memory_mb'] for m in metrics_list]
    
    # Group by power source
    ac_times = [m['execution_time_seconds'] for m in metrics_list 
                if m.get('power_source', {}).get('power_source') == 'AC Power']
    battery_times = [m['execution_time_seconds'] for m in metrics_list 
                    if m.get('power_source', {}).get('power_source') == 'Battery Power']
    
    stats = {
        "execution_time": {
            "mean": statistics.mean(execution_times),
            "median": statistics.median(execution_times),
            "min": min(execution_times),
            "max": max(execution_times),
            "stddev": statistics.stdev(execution_times) if len(execution_times) > 1 else 0
        },
        "memory_change": {
            "mean": statistics.mean(memory_changes),
            "median": statistics.median(memory_changes),
            "min": min(memory_changes),
            "max": max(memory_changes)
        },
        "peak_memory": {
            "mean": statistics.mean(peak_memories),
            "median": statistics.median(peak_memories),
            "min": min(peak_memories),
            "max": max(peak_memories)
        },
        "power_source_comparison": {
            "ac_power": {
                "mean": statistics.mean(ac_times) if ac_times else None,
                "count": len(ac_times)
            },
            "battery_power": {
                "mean": statistics.mean(battery_times) if battery_times else None,
                "count": len(battery_times)
            }
        },
        "sample_count": len(metrics_list)
    }
    
    # Add compression stats if available
    compression_ratios = []
    for m in metrics_list:
        if m.get('input_size') and m.get('output_size_bytes'):
            ratio = m['input_size']['total_size_bytes'] / m['output_size_bytes']
            compression_ratios.append(ratio)
    
    if compression_ratios:
        stats["compression_ratio"] = {
            "mean": statistics.mean(compression_ratios),
            "min": min(compression_ratios),
            "max": max(compression_ratios)
        }
    
    return stats

def print_summary(metrics_by_function: Dict[str, List[Dict]]):
    """Print a summary of all metrics."""
    print("\n=== Performance Metrics Summary ===\n")
    
    for func_name, metrics_list in metrics_by_function.items():
        print(f"\n{func_name}:")
        print("-" * (len(func_name) + 1))
        
        stats = calculate_statistics(metrics_list)
        
        print(f"Sample Count: {stats['sample_count']}")
        
        print("\nExecution Time (seconds):")
        print(f"  Mean:   {stats['execution_time']['mean']:.2f}")
        print(f"  Median: {stats['execution_time']['median']:.2f}")
        print(f"  Min:    {stats['execution_time']['min']:.2f}")
        print(f"  Max:    {stats['execution_time']['max']:.2f}")
        print(f"  StdDev: {stats['execution_time']['stddev']:.2f}")
        
        print("\nMemory Change (MB):")
        print(f"  Mean:   {stats['memory_change']['mean']:.2f}")
        print(f"  Median: {stats['memory_change']['median']:.2f}")
        print(f"  Min:    {stats['memory_change']['min']:.2f}")
        print(f"  Max:    {stats['memory_change']['max']:.2f}")
        
        print("\nPeak Memory (MB):")
        print(f"  Mean:   {stats['peak_memory']['mean']:.2f}")
        print(f"  Median: {stats['peak_memory']['median']:.2f}")
        print(f"  Min:    {stats['peak_memory']['min']:.2f}")
        print(f"  Max:    {stats['peak_memory']['max']:.2f}")
        
        # Power source comparison
        ac = stats['power_source_comparison']['ac_power']
        battery = stats['power_source_comparison']['battery_power']
        print("\nPower Source Comparison:")
        if ac['mean'] is not None:
            print(f"  AC Power (n={ac['count']}): {ac['mean']:.2f}s")
        if battery['mean'] is not None:
            print(f"  Battery (n={battery['count']}): {battery['mean']:.2f}s")
        if ac['mean'] and battery['mean']:
            slowdown = (battery['mean'] - ac['mean']) / ac['mean'] * 100
            print(f"  Battery Slowdown: {slowdown:.1f}%")
        
        if "compression_ratio" in stats:
            print("\nCompression Ratio:")
            print(f"  Mean: {stats['compression_ratio']['mean']:.2f}x")
            print(f"  Min:  {stats['compression_ratio']['min']:.2f}x")
            print(f"  Max:  {stats['compression_ratio']['max']:.2f}x")
        
        print("\n" + "=" * 40)

if __name__ == "__main__":
    metrics = load_metrics_files()
    print_summary(metrics) 