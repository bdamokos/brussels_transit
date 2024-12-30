import httpx
from datetime import datetime, timedelta
import logging
from config import get_config
from logging.config import dictConfig

# Only configure logging if we're not being imported for testing
if __name__ != "__main__" and not any(p.endswith('test_language_utils.py') for p in __import__('sys').argv):
    # Setup logging using configuration
    logging_config = get_config('LOGGING_CONFIG')
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

def select_language(content, provider_languages, requested_language=None):
    """Select the best matching language for multilingual content.
    
    Args:
        content: Content object that might contain language-specific versions
        provider_languages: List of languages available from the provider
        requested_language: Optional specific language to try first
        
    Returns:
        tuple: (selected_content, metadata)
        metadata format:
        {
            "language": {
                "requested": str,  # Language that was requested
                "provided": str,   # Language that was actually provided
                "available": list, # Languages available in the content
                "warning": str     # Warning message if API structure might have changed
            }
        }
    """
    from config import get_config
    
    # If content is not a dictionary, return as is
    if not isinstance(content, dict):
        return content, {
            "language": {
                "requested": requested_language,
                "provided": None,
                "available": [],
                "warning": None
            }
        }
    
    # Get language precedence from config
    language_precedence = get_config('LANGUAGE_PRECEDENCE', ['en', 'fr', 'nl'])
    
    # Check if any keys look like language codes (2-3 chars)
    # Use list to preserve order from API
    possible_lang_keys = [k for k in content.keys() 
                         if isinstance(k, str) and len(k) in (2, 3)]
    
    # If no keys look like language codes, return as is
    if not possible_lang_keys:
        return content, {
            "language": {
                "requested": requested_language,
                "provided": None,
                "available": [],
                "warning": None
            }
        }
    
    # Get available languages that match our provider's languages
    # Use list comprehension to preserve order from API
    available_languages = [lang for lang in possible_lang_keys 
                         if lang in provider_languages]
    
    # If we found language-like keys but none match our provider's languages,
    # this might indicate an API change
    if possible_lang_keys and not available_languages:
        return content, {
            "language": {
                "requested": requested_language,
                "provided": None,
                "available": possible_lang_keys,
                "warning": f"Found unexpected language keys: {possible_lang_keys}. Possible API change?"
            }
        }
    
    # Build the fallback chain
    fallback_chain = []
    if requested_language and requested_language in provider_languages:
        fallback_chain.append(requested_language)
    for lang in language_precedence:
        if lang in provider_languages and lang not in fallback_chain:
            fallback_chain.append(lang)
    
    # Add any remaining provider languages in API order
    for lang in available_languages:
        if lang not in fallback_chain:
            fallback_chain.append(lang)
    
    # Try each language in the chain
    for lang in fallback_chain:
        if lang in content and content[lang]:
            return content[lang], {
                "language": {
                    "requested": requested_language,
                    "provided": lang,
                    "available": available_languages,
                    "warning": (f"Fallback to {lang}: content not available in {requested_language}"
                              if requested_language and lang != requested_language
                              else None)
                }
            }
    
    # If we get here, we found language keys but couldn't get valid content
    return content, {
        "language": {
            "requested": requested_language,
            "provided": None,
            "available": available_languages,
            "warning": "Found language keys but no valid content in any language"
        }
    }

def matches_destination(configured_name: str, destination_data: dict) -> bool:
    """
    Check if a configured destination name matches any language version of the actual destination.
    
    Args:
        configured_name: The destination name from config (e.g., "STOCKEL")
        destination_data: Multilingual destination data (e.g., {"fr": "STOCKEL", "nl": "STOKKEL"})
        
    Returns:
        bool: True if the configured name matches any language version
    """
    if not destination_data or not isinstance(destination_data, dict):
        return False
        
    # Normalize names for comparison (uppercase)
    configured_name = configured_name.upper()
    destination_values = [str(v).upper() for v in destination_data.values()]
    
    return configured_name in destination_values

