import httpx
from datetime import datetime, timedelta
import logging
from config import get_config
from logging.config import dictConfig

# Setup logging using configuration
logging_config = get_config('LOGGING_CONFIG')
logging_config['log_dir'].mkdir(exist_ok=True)
dictConfig(logging_config)

# Get logger
logger = logging.getLogger('utils')

class RateLimiter:
    def __init__(self):
        self.remaining = None
        self.reset_time = None
        self.limit = None
        self.last_logged_hundreds = None
        self.first_update = True
        
    def update_from_headers(self, headers):
        try:
            previous_remaining = self.remaining
            self.remaining = int(headers.get('x-ratelimit-remaining', 0))
            reset_time_str = headers.get('x-ratelimit-reset', '0')
            try:
                self.reset_time = datetime.fromisoformat(reset_time_str)
            except (ValueError, TypeError):
                # Fallback to current time plus 1 hour if parsing fails
                self.reset_time = datetime.now() + timedelta(hours=1)
            
            self.limit = int(headers.get('x-ratelimit-limit', 0))
            
            # Log initial quota status
            if self.first_update:
                logger.info(
                    f"Initial API quota status: {self.remaining}/{self.limit} calls available "
                    f"(Reset at {self.reset_time.strftime('%H:%M:%S')})"
                )
                self.first_update = False
            
            # Log when we cross each hundred threshold
            elif previous_remaining is not None:
                current_hundreds = self.remaining // 100
                previous_hundreds = previous_remaining // 100
                
                if current_hundreds < previous_hundreds:
                    logger.info(
                        f"API calls remaining: {self.remaining}/{self.limit} "
                        f"(Reset at {self.reset_time.strftime('%H:%M:%S')})"
                    )
            
            logger.debug(f"Rate limit update: {self.remaining} requests remaining")
            logger.debug(f"Reset time: {self.reset_time}")
            
        except (ValueError, TypeError) as e:
            logger.warning(f"Error parsing rate limit headers: {e}")
            self.remaining = 0  # Set to 0 on error
            self.limit = 0
            self.reset_time = datetime.now() + timedelta(hours=1)  # Set default reset time

    def can_make_request(self) -> bool:
        """Check if we can make a request based on rate limits"""
        if self.remaining is None or self.reset_time is None:
            return True
        
        if self.remaining <= 0:
            # Check if reset time has passed
            if datetime.now() > self.reset_time:
                self.remaining = None
                self.reset_time = None
                return True
                
            logger.info(f"Rate limit exceeded. Reset at {self.reset_time.strftime('%H:%M:%S')}")
            return False
            
        # Keep some requests in reserve
        return self.remaining > 100

async def get_client():
    return httpx.AsyncClient(timeout=30.0) 