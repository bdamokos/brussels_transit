''' Download the required GTFS data from the STIB API.'''

from transit_providers.config import get_provider_config
import httpx
from logging.config import dictConfig
import logging

# Get logger
logger = logging.getLogger('stib.gtfs')

# Get provider configuration
provider_config = get_provider_config('stib')
logger.debug(f"Provider config: {provider_config}")



STIB_API_KEY = provider_config.get('API_KEY')
GTFS_API_URL = provider_config.get('GTFS_API_URL')
GTFS_DIR = provider_config.get('GTFS_DIR')
GTFS_USED_FILES = provider_config.get('GTFS_USED_FILES')
GTFS_DIR.mkdir(parents=True, exist_ok=True)
GTFS_CACHE_DURATION = provider_config.get('GTFS_CACHE_DURATION')
GTFS_USED_FILES = provider_config.get('GTFS_USED_FILES')

async def download_gtfs_data():
    '''Connects to the GTFS API, and parses the response to get the required files.'''
    try:
        # Ensure GTFS directory exists
        GTFS_DIR.mkdir(parents=True, exist_ok=True)
        
        async with httpx.AsyncClient() as client:
            # Get the GTFS files listing
            url = f"{GTFS_API_URL}?apikey={STIB_API_KEY}"
            response = await client.get(url)
            if response.status_code != 200:
                logger.error(f"Failed to get GTFS files: {response.status_code} {response.text}")
                return
                
            data = response.json()
            files = data.get('results', [])
            
            # Download each file
            for file_data in files:
                try:
                    file_info = file_data.get('file', {})
                    filename = file_info.get('filename')
                    file_url = file_info.get('url')
                    
                    if not filename or not file_url:
                        logger.error(f"Missing filename or URL in file data: {file_data}")
                        continue
                        
                    if filename not in GTFS_USED_FILES:
                        logger.debug(f"Skipping unused file: {filename}")
                        continue
                    
                    logger.info(f"Downloading {filename} from {file_url}")
                    file_response = await client.get(
                        file_url, 
                        params={'apikey': STIB_API_KEY},
                        follow_redirects=True
                    )
                    
                    if file_response.status_code != 200:
                        logger.error(f"Failed to download {filename}: {file_response.status_code}")
                        continue
                        
                    # Save file
                    file_path = GTFS_DIR / filename
                    file_path.write_bytes(file_response.content)
                    logger.info(f"Successfully downloaded {filename} to {file_path}")
                    
                except Exception as e:
                    logger.error(f"Error downloading {filename}: {e}")
                    import traceback
                    logger.error(traceback.format_exc())
                    continue
            
            # Verify downloads
            downloaded_files = list(GTFS_DIR.glob('*.txt'))
            logger.info(f"Downloaded files: {[f.name for f in downloaded_files]}")
            
            if not (GTFS_DIR / 'stops.txt').exists():
                logger.error(f"stops.txt not found after download. Files in directory: {[f.name for f in downloaded_files]}")
                return False
                
            return True
            
    except Exception as e:
        logger.error(f"Error in download_gtfs_data: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return False

def ensure_gtfs_data():
    '''Ensures the GTFS data is downloaded and available.'''
    if not all((GTFS_DIR / file).exists() for file in GTFS_USED_FILES):
        return download_gtfs_data()
    return True

if __name__ == "__main__":
    import asyncio
    asyncio.run(download_gtfs_data())