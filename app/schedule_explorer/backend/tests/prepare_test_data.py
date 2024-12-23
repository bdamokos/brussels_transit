from pathlib import Path
import shutil

def prepare_test_data():
    """Prepare test data for GitHub Actions"""
    # Set up test directories
    test_downloads_dir = Path(__file__).parent / "test_data" / "downloads"
    
    # Ensure the test data directory exists and is empty
    if test_downloads_dir.exists():
        shutil.rmtree(test_downloads_dir)
    test_downloads_dir.mkdir(parents=True, exist_ok=True)
    
    # Get the real downloads directory
    real_downloads_dir = Path(__file__).parent.parent.parent.parent.parent / "downloads"
    
    # Copy over the metadata file
    shutil.copy2(real_downloads_dir / "datasets_metadata.json", test_downloads_dir / "datasets_metadata.json")
    
    # Copy over all provider directories with truncated GTFS files
    for provider_dir in real_downloads_dir.glob('*'):
        if provider_dir.is_dir():
            # Skip if it's not a provider directory (e.g., __pycache__)
            if provider_dir.name.startswith('__'):
                continue
                
            # Create the provider directory in test data
            test_provider_dir = test_downloads_dir / provider_dir.name
            test_provider_dir.mkdir(parents=True, exist_ok=True)
            
            # Copy each dataset directory
            for dataset_dir in provider_dir.glob('*'):
                if dataset_dir.is_dir():
                    test_dataset_dir = test_provider_dir / dataset_dir.name
                    test_dataset_dir.mkdir(parents=True, exist_ok=True)
                    
                    # Copy and truncate each GTFS file
                    for gtfs_file in dataset_dir.glob('*.txt'):
                        print(f"Copying {gtfs_file.name} from {gtfs_file} to {test_dataset_dir / gtfs_file.name}")
                        with open(gtfs_file, 'r') as src, open(test_dataset_dir / gtfs_file.name, 'w') as dst:
                            # Copy header line
                            header = next(src, None)
                            if header is not None:
                                dst.write(header)
                                # Copy next 999 lines (total 1000 including header)
                                for _ in range(999):
                                    line = next(src, None)
                                    if line is None:
                                        break
                                    dst.write(line)

if __name__ == '__main__':
    prepare_test_data() 