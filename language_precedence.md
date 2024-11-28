# Language Precedence Implementation Plan

## Configuration Structure

1. Global Language Configuration (default.py/local.py):
   - LANGUAGE_PRECEDENCE = ['en', 'fr', 'nl']  # Default fallback chain
   - Can be overridden in local.py for different preferences

2. Provider-specific Language Configuration (in provider config):
   - STIB config: AVAILABLE_LANGUAGES = ['en', 'fr', 'nl']
   - De Lijn config: AVAILABLE_LANGUAGES = ['nl']
   - Each provider declares its available languages

## Language Selection Logic

1. For any multilingual content (stop names, messages, etc.):
   - Follow LANGUAGE_PRECEDENCE order
   - For each language in the chain:
     - Check if language exists in provider's AVAILABLE_LANGUAGES
     - Check if content exists in that language
     - Use first matching content and include language metadata

2. Provider Language Handling:
   - If provider has languages not in LANGUAGE_PRECEDENCE:
     - Insert these languages in fallback chain before "raw" fallback
     - Example: SNCB ['en', 'fr', 'nl', 'de'] would result in:
       en -> fr -> nl -> de -> raw
     - Include warning about unordered languages

3. Response Format:
   {
     "content": "Message content",
     "_metadata": {
       "language": {
         "requested": "en",
         "provided": "fr",
         "available": ["fr", "nl"],
         "warning": "Fallback to fr: content not available in en"
       }
     }
   }

## Implementation Tasks

1. Configuration:
   - [x] Add LANGUAGE_PRECEDENCE to default.py
   - [x] Add AVAILABLE_LANGUAGES to provider configs
   - [x] Update example local.py documentation

2. Core Implementation:
   - [x] Create language selection utility function
   - [x] Implement warning system for unordered languages
   - [x] Add language metadata to response structure

3. Integration:
   - [x] Update message parsing in api.py
   - [x] Update stop name handling with multi-source resolution:
     - API names (primary source)
     - GTFS translations (secondary source)
     - Stop ID fallback (last resort)
   - [ ] Manage the case where the stop or direction names provided in the config match a language version other than the language taking precedence
   - [ ] Add tests for language fallback
   - [ ] Add tests for metadata accuracy

4. Documentation:
   - [ ] Document language configuration in README
   - [ ] Add examples for custom language precedence
   - [ ] Document metadata structure

## Testing Requirements

1. Stop Name Resolution Chain:
   - Test API response handling:
     - Complete responses (both fr/nl present)
     - Partial responses (only one language)
     - Empty/error responses
   - Test GTFS fallback:
     - Valid trans_id in stops.txt
     - Missing trans_id
     - Missing translations.txt
   - Test metadata accuracy:
     - Source tracking (api/gtfs_translations/fallback)
     - Language selection
     - trans_id preservation

2. Edge Cases:
   - Stop IDs with suffixes (e.g., 5710F vs 5710)
   - Identical names in different languages
   - Missing or corrupted cache files
   - API timeouts and errors
   - GTFS file encoding issues

3. Language Selection:
   - Test precedence order follows configuration
   - Test fallback chain when preferred language unavailable
   - Test metadata warnings for language fallbacks
   - Test handling of unordered languages

4. Cache Behavior:
   - Test cache structure maintains backward compatibility
   - Test cache updates when new translations become available
   - Test cache persistence across restarts

## Current Status (2024-11-28)

1. Implemented Features:
   - Complete name resolution chain in get_stop_names.py
   - Metadata tracking for name sources and translations
   - Backward compatibility with v1 API
   - GTFS translation integration

2. Next Steps:
   - Implement comprehensive test suite
   - Add more logging for debugging language selection
   - Document the new name resolution process
   - Consider adding language stats collection for monitoring

3. Open Questions:
   - How to handle conflicting translations between API and GTFS?
   - Should we cache GTFS translations separately?
   - How to handle dynamic language updates?

Note: Need to test thoroughly with real-world data, especially:
- Stops with different names in fr/nl
- GTFS translation accuracy
- API response variations
- Cache consistency

## API Investigation Findings

1. STIB Stop Names API:
   ```json
   {
     "name": {
       "fr": "SIMONIS",
       "nl": "SIMONIS"
     }
   }
   ```
   - Stop names are provided in both French and Dutch
   - Some stops have identical names in both languages
   - No English names provided by default

2. STIB Waiting Times API:
   ```json
   {
     "message": {
       "en": "End of service",
       "fr": "Fin de service",
       "nl": "Einde dienst"
     }
   }
   ```
   - Service messages are provided in all three languages
   - Need to check more examples as this was an end-of-service message

3. Next Steps for Integration:
   a) First: Update message parsing in api.py
   b) Then: Update stop name handling
   c) Finally: Handle terminus name matching across languages

Note: Need to get more API examples for:
- Regular waiting time messages with terminus information
- Stop names with different translations
- Service disruption messages



   