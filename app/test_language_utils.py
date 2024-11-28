"""Test cases for language utilities"""

import logging
from utils import select_language, find_stop_by_name
import json

# Configure basic logging for tests
logging.basicConfig(level=logging.INFO)

def run_test(name, content, expected_warning=None):
    print(f"\n=== Test: {name} ===")
    print(f"Input: {content}")
    result, metadata = select_language(content, provider_languages=['en', 'fr', 'nl'])
    print(f"Result: {result}")
    print(f"Metadata: {metadata}")
    if expected_warning == metadata['language']['warning']:
        print("✓ Test passed")
    else:
        print(f"✗ Test failed")
        print(f"Expected warning: {expected_warning}")
        print(f"Got warning: {metadata['language']['warning']}")

def run_stop_test(name, stops, search_name, expected_name=None):
    print(f"\n=== Test: {name} ===")
    print(f"Search for: {search_name}")
    print(f"In stops: {stops}")
    result = find_stop_by_name(stops, search_name)
    print(f"Result: {result}")
    if result and expected_name:
        if result.get('name') == expected_name:
            print("✓ Test passed")
        else:
            print(f"✗ Test failed")
            print(f"Expected name: {expected_name}")
            print(f"Got name: {result.get('name')}")
    elif not result and not expected_name:
        print("✓ Test passed")
    else:
        print(f"✗ Test failed")
        print(f"Expected to {'find' if expected_name else 'not find'} a stop")

if __name__ == "__main__":
    print("\nRunning select_language() tests...")
    
    # Basic test cases
    run_test(
        "Simple string content",
        "Just a simple message",
        None
    )
    
    run_test(
        "Dictionary without language keys",
        {"title": "Hello", "body": "World"},
        None
    )
    
    run_test(
        "Normal language content",
        {
            "en": "English message",
            "fr": "Message en français",
            "nl": "Nederlands bericht"
        },
        None
    )
    
    run_test(
        "Unexpected language",
        {
            "de": "Deutsche nachricht",
            "es": "Mensaje en español"
        },
        "Found unexpected language keys: {'de', 'es'}. Possible API change?"
    )
    
    run_test(
        "Mixed content structure",
        {
            "en": "English text",
            "details": {"time": "12:00"},
            "fr": "Texte français"
        },
        None
    )
    
    run_test(
        "Empty language values",
        {
            "en": "",
            "fr": None,
            "nl": "Nederlandse tekst"
        },
        None
    )
    
    run_test(
        "Different key structure",
        {
            "message_fr": "Message en français",
            "message_en": "English message"
        },
        None
    )
    
    run_test(
        "Nested language structure",
        {
            "text": {
                "en": "English",
                "fr": "Français"
            },
            "title": {
                "en": "Title",
                "fr": "Titre"
            }
        },
        None
    )
    
    run_test(
        "All empty values",
        {
            "en": "",
            "fr": None,
            "nl": ""
        },
        "Found language keys but no valid content in any language"
    )
    
    print("\n=== Real-world Test Cases ===")
    
    # Test 10: STIB Service Message (Real)
    stib_message = json.loads('[{"text": [{"en": "Works. Nov 8, 2024, 8PM-Mar 28, 2025, tram 19 replaced by T-bus btw SIMONIS and MIROIR.T-bus at stop bus 13 to UZ-VUB", "fr": "Travaux. 8/11/24, 20h- 28/3/25,T19 remplacé par T-bus entre SIMONIS et MIROIR. T-bus à l\'arrêt du bus 13 vers UZ-VUB", "nl": "Werken. 8/11/24, 20u- 28/3/25, T19 vervangen door T-bus tss SIMONIS en SPIEGEL. T-bus aan halte bus 13 naar UZ-VUB"}], "type": "Description"}]')
    
    # Test the nested text content directly
    run_test(
        "STIB Service Message - Text Content",
        stib_message[0]['text'][0],
        None
    )
    
    # Test 11: STIB Stop Name (Real)
    run_test(
        "STIB Stop Name",
        json.loads('{"fr": "SIMONIS", "nl": "SIMONIS"}'),
        None
    )
    
    # Test 12: STIB Waiting Time Message (Real)
    run_test(
        "STIB Waiting Time Message",
        json.loads('{"en": "End of service", "fr": "Fin de service", "nl": "Einde dienst"}'),
        None
    )
    
    # Test 13: De Lijn Stop (Real)
    run_test(
        "De Lijn Stop",
        {
            "entiteitnummer": "5",
            "haltenummer": "567754",
            "omschrijving": "Polenplein",
            "omschrijvingLang": "Ruiselede Polenplein",
            "gemeentenummer": "1559",
            "omschrijvingGemeente": "Ruiselede",
            "taal": "?"
        },
        None
    )
    
    print("\n=== Cross-language Stop Matching Tests ===")
    
    # Test case: Dutch config name matches French API name
    stops_data = [
        {
            'id': '1234',
            'name': {
                'fr': 'GARE DE L\'OUEST',
                'nl': 'WESTSTATION'
            }
        },
        {
            'id': '5678',
            'name': {
                'fr': 'SIMONIS',
                'nl': 'SIMONIS'
            }
        }
    ]
    
    run_stop_test(
        "Dutch config name matches French API name",
        stops_data,
        "WESTSTATION",  # Config uses Dutch name
        "GARE DE L'OUEST"  # Should return French name due to precedence
    )
    
    # Test case: Exact match in non-preferred language
    run_stop_test(
        "Exact match in non-preferred language",
        stops_data,
        "GARE DE L'OUEST",  # Config uses French name
        "GARE DE L'OUEST"  # Should return French name as it's the match
    )
    
    # Test case: Case-insensitive matching
    run_stop_test(
        "Case-insensitive matching",
        stops_data,
        "Weststation",  # Mixed case in config
        "GARE DE L'OUEST"  # Should still match and return French name
    )
    
    # Test case: No match in any language
    run_stop_test(
        "No match in any language",
        stops_data,
        "CENTRAL",  # Non-existent stop
        None  # Should return None
    )
    
    # Test case: Partial name match
    stops_data_partial = [
        {
            'id': '1234',
            'name': {
                'fr': 'GARE DE L\'OUEST / BRUXELLES',
                'nl': 'WESTSTATION / BRUSSEL'
            }
        }
    ]
    
    run_stop_test(
        "Partial name match",
        stops_data_partial,
        "WESTSTATION",  # Partial match in Dutch
        "GARE DE L'OUEST / BRUXELLES"  # Should return full French name
    ) 