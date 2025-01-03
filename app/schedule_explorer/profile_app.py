#!/usr/bin/env python3
import logging
import json
from pathlib import Path
from datetime import datetime
from backend.profiler import run_full_profile

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

logger = logging.getLogger("schedule_explorer.profile_app")

def main():
    # Get the GTFS data directory
    data_dir = Path(__file__).parent.parent.parent / "downloads" / "mdb-1859_Societe_nationale_des_chemins_de_fer_belges_NMBS_SNCB" / "mdb-1859-202501020029"
    
    # Create output directory for profiling results
    output_dir = Path(__file__).parent.parent.parent / "profiling_results"
    output_dir.mkdir(exist_ok=True)
    
    # Use real stop IDs from SNCB data
    # Brussels-Luxembourg to Ottignies (a common route)
    sample_start_id = "8811304"  # Brussels-Luxembourg
    sample_end_id = "8811601"    # Ottignies
    
    logger.info("Starting profiling session")
    logger.info(f"Testing route from {sample_start_id} to {sample_end_id}")
    
    try:
        # Run profiling
        metrics = run_full_profile(data_dir, sample_start_id, sample_end_id)
        
        # Save results
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_file = output_dir / f"profile_results_{timestamp}.json"
        
        with open(output_file, 'w') as f:
            json.dump(metrics, f, indent=2)
            
        logger.info(f"Profiling results saved to {output_file}")
        
    except Exception as e:
        logger.error(f"Error during profiling: {e}", exc_info=True)

if __name__ == "__main__":
    main() 