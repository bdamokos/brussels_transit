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
   - [ ] Update message parsing in api.py
   - [ ] Update stop name handling
   - [ ] Manage the case where the stop or direction names provided in the config match a language version other than the language taking precedence - e.g. we configure stop with Weststation (Dutch) but the precedence order is en, fr, nl and stops are provided in fr and nl. So the expected behaviour is that the stop with the Dutch name of Weststation is returned but using its French name.
   - [ ] Add tests for language fallback
   - [ ] Add tests for metadata accuracy

4. Documentation:
   - [ ] Document language configuration in README
   - [ ] Add examples for custom language precedence
   - [ ] Document metadata structure



   