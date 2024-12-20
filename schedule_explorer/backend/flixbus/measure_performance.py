import os
from pathlib import Path
from gtfs_loader import load_feed, load_stops, load_trips, serialize_gtfs_data, deserialize_gtfs_data, load_translations
from performance_metrics import measure_performance, save_metrics, print_metrics

@measure_performance
def measure_load_feed(data_dir: str):
    return load_feed(data_dir)

@measure_performance
def measure_load_stops(data_dir: Path, translations: dict):
    return load_stops(data_dir, translations)

@measure_performance
def measure_load_trips(data_dir: Path):
    return load_trips(data_dir)

@measure_performance
def measure_serialize_gtfs_data(feed):
    return serialize_gtfs_data(feed)

@measure_performance
def measure_deserialize_gtfs_data(data: bytes):
    return deserialize_gtfs_data(data)

def find_gtfs_dirs(base_dir: str = ".") -> list[str]:
    """Find all directories starting with 'gtfs_'"""
    gtfs_dirs = []
    for item in os.listdir(base_dir):
        if item.startswith("gtfs_") and os.path.isdir(item):
            gtfs_dirs.append(item)
    return gtfs_dirs

def run_performance_tests(data_dir: str):
    """Run performance tests on a GTFS directory."""
    print(f"\nRunning performance tests on {data_dir}")
    
    try:
        # Measure load_feed
        feed, feed_metrics = measure_load_feed(data_dir)
        print_metrics(feed_metrics)
        save_metrics(feed_metrics)
        
        # Load translations first (needed for load_stops)
        translations = load_translations(Path(data_dir))
        
        # Measure load_stops
        stops, stops_metrics = measure_load_stops(Path(data_dir), translations)
        print_metrics(stops_metrics)
        save_metrics(stops_metrics)
        
        # Measure load_trips
        trips, trips_metrics = measure_load_trips(Path(data_dir))
        print_metrics(trips_metrics)
        save_metrics(trips_metrics)
        
        # Measure serialize_gtfs_data
        serialized_data, serialize_metrics = measure_serialize_gtfs_data(feed)
        print_metrics(serialize_metrics)
        save_metrics(serialize_metrics)
        
        # Measure deserialize_gtfs_data
        deserialized_feed, deserialize_metrics = measure_deserialize_gtfs_data(serialized_data)
        print_metrics(deserialize_metrics)
        save_metrics(deserialize_metrics)
        
    except Exception as e:
        print(f"Error processing {data_dir}: {str(e)}")

def run_all_performance_tests():
    """Run performance tests on all GTFS directories."""
    gtfs_dirs = find_gtfs_dirs()
    if not gtfs_dirs:
        print("No GTFS directories found!")
        return
    
    print(f"Found GTFS directories: {', '.join(gtfs_dirs)}")
    for data_dir in gtfs_dirs:
        run_performance_tests(data_dir)

if __name__ == "__main__":
    run_all_performance_tests() 