"""Tests for the configuration schema and validation"""

import pytest
from collections import UserDict
from copy import deepcopy
from pathlib import Path
from pydantic import ValidationError
from .config_schema import (
    DirectionType,
    LineDestination,
    StopConfig,
    ProviderConfig,
    validate_provider_config
)
from .config import redact_config

# Sample configurations from default.py
SAMPLE_STIB_CONFIG = {
    'STIB_STOPS': [
        {
            'id': '8122',
            'name': 'ROODEBEEK',
            'lines': {
                '1': ['STOCKEL', "GARE DE L'OUEST"],
                '5': ['STOCKEL', "GARE DE L'OUEST"]
            },
            'direction': 'Suburb'
        }
    ],
    'API_KEY': 'dummy_key',
    'API_URL': 'https://example.com/api'
}

SAMPLE_DELIJN_CONFIG = {
    'STOP_IDS': ['307250', '307251'],
    'MONITORED_LINES': ['116', '117', '118', '144'],
    'API_URL': 'https://api.delijn.be/v1',
    'API_KEY': 'dummy_key'
}

SAMPLE_BKK_CONFIG = {
    'PROVIDER_ID': 'mdb-990',
    'STOP_IDS': ['F01111'],
    'MONITORED_LINES': ['3040'],
    'CACHE_DIR': Path('cache/bkk'),
    'GTFS_DIR': Path('gtfs/bkk'),
    'API_KEY': 'dummy_key'
}

def test_line_destination_creation():
    """Test creating LineDestination objects with different types"""
    # Test all direction types
    destinations = [
        LineDestination(type=DirectionType.STOP_NAME, value='ROGIER'),
        LineDestination(type=DirectionType.DIRECTION_NAME, value='City'),
        LineDestination(type=DirectionType.DIRECTION_ID, value=0),
        LineDestination(type=DirectionType.STOP_ID, value='5710'),
        LineDestination(type=DirectionType.HEADSIGN, value='HEYSEL via City')
    ]
    
    # Verify each destination
    assert destinations[0].type == DirectionType.STOP_NAME
    assert destinations[0].value == 'ROGIER'
    assert destinations[1].type == DirectionType.DIRECTION_NAME
    assert destinations[1].value == 'City'
    assert destinations[2].type == DirectionType.DIRECTION_ID
    assert destinations[2].value == 0
    assert destinations[3].type == DirectionType.STOP_ID
    assert destinations[3].value == '5710'
    assert destinations[4].type == DirectionType.HEADSIGN
    assert destinations[4].value == 'HEYSEL via City'

def test_stop_config_creation():
    """Test creating StopConfig objects"""
    # Test minimal stop config
    minimal_stop = StopConfig(id='1234')
    assert minimal_stop.id == '1234'
    assert minimal_stop.name is None
    assert minimal_stop.lines is None
    assert minimal_stop.direction is None

    # Test full stop config
    full_stop = StopConfig(
        id='5678',
        name='Test Stop',
        lines={
            '1': [
                LineDestination(type=DirectionType.STOP_NAME, value='Dest A'),
                LineDestination(type=DirectionType.STOP_NAME, value='Dest B')
            ]
        },
        direction='City'
    )
    assert full_stop.id == '5678'
    assert full_stop.name == 'Test Stop'
    assert len(full_stop.lines['1']) == 2
    assert full_stop.direction == 'City'

def test_legacy_format_conversion():
    """Test converting legacy format to new format"""
    legacy_stop = StopConfig(
        id='1234',
        name='Legacy Stop',
        lines={
            '55': ['DA VINCI', 'ROGIER']
        },
        direction='City'
    )
    
    # After validation, the string destinations should be converted to LineDestination objects
    assert isinstance(legacy_stop.lines['55'][0], LineDestination)
    assert legacy_stop.lines['55'][0].type == DirectionType.STOP_NAME
    assert legacy_stop.lines['55'][0].value == 'DA VINCI'

def test_stib_config_validation():
    """Test validating STIB configuration"""
    validated = validate_provider_config(SAMPLE_STIB_CONFIG)
    
    # Check that the stops were properly converted
    assert len(validated['stops']) == 1
    stop = validated['stops'][0]
    assert stop['id'] == '8122'
    assert stop['name'] == 'ROODEBEEK'
    assert len(stop['lines']['1']) == 2
    
    # Check that provider-specific fields were preserved
    assert validated['provider_specific']['API_KEY'] == 'dummy_key'
    assert validated['provider_specific']['API_URL'] == 'https://example.com/api'


@pytest.mark.parametrize('config', [
    {},
    {'STIB_STOPS': None},
    {'STIB_STOPS': []},
    {'STOP_IDS': None},
    {'STOP_IDS': []},
    {'STIB_STOPS': None, 'STOP_IDS': None},
])
def test_unset_stops_config(config):
    assert validate_provider_config(config)['stops'] == []


@pytest.mark.parametrize('config', [
    {'STIB_STOPS': None, 'STOP_IDS': ['1234']},
    {'STIB_STOPS': [{'id': '1234'}], 'STOP_IDS': None},
])
def test_unset_stops_preserve_other_stop_format(config):
    assert validate_provider_config(config)['stops'] == [{'id': '1234'}]


@pytest.mark.parametrize('stops', [[{}], [{'id': '1234', 'lines': {'1': [None]}}]])
def test_invalid_stib_stops_are_rejected(stops):
    with pytest.raises(ValidationError):
        validate_provider_config({'STIB_STOPS': stops})


@pytest.mark.parametrize('config, expected', [
    ({}, {}),
    ({'API_KEY': 'test_key'}, {'API_KEY': 'test_key'}),
    ({'provider_specific': {'API_KEY': 'test_key'}}, {'API_KEY': 'test_key'}),
    ({'provider_specific': UserDict({'API_KEY': 'test_key'})}, {'API_KEY': 'test_key'}),
    ({'provider_specific': None}, {}),
    ({'provider_specific': {}}, {}),
    ({'provider_specific': None, 'API_KEY': 'test_key'}, {'API_KEY': 'test_key'}),
    ({'provider_specific': {}, 'API_KEY': 'test_key'}, {'API_KEY': 'test_key'}),
    (
        {'provider_specific': {'API_KEY': 'test_key'}, 'RATE_LIMIT_DELAY': 0.5},
        {'API_KEY': 'test_key', 'RATE_LIMIT_DELAY': 0.5},
    ),
])
def test_grouped_provider_settings(config, expected):
    assert validate_provider_config(config)['provider_specific'] == expected


@pytest.mark.parametrize('nested_first', [False, True])
def test_top_level_provider_settings_take_precedence_without_mutating_input(nested_first):
    grouped = {'provider_specific': {
        'API_KEY': 'nested_test_key',
        'OPTIONS': {'languages': ['fr', 'nl']},
    }}
    top_level = {'API_KEY': 'top_test_key'}
    config = {**grouped, **top_level} if nested_first else {**top_level, **grouped}
    original = deepcopy(config)

    validated = validate_provider_config(config)

    assert validated['provider_specific'] == {
        'API_KEY': 'top_test_key',
        'OPTIONS': {'languages': ['fr', 'nl']},
    }
    assert config == original
    validated['provider_specific']['API_KEY'] = 'changed_test_key'
    validated['provider_specific']['OPTIONS']['languages'].append('en')
    assert config == original


@pytest.mark.parametrize('settings', [[], [('API_KEY', 'test_key')], '', 'invalid', 0, 42, False])
def test_malformed_grouped_provider_settings_are_rejected(settings):
    with pytest.raises(ValidationError) as error:
        validate_provider_config({'provider_specific': settings, 'API_KEY': 'test_key'})

    assert any(
        item['loc'] == ('provider_specific',) and item['type'] == 'dict_type'
        for item in error.value.errors()
    )


def test_delijn_config_validation():
    """Test validating De Lijn configuration"""
    validated = validate_provider_config(SAMPLE_DELIJN_CONFIG)
    
    # Check that STOP_IDS were converted to stops
    assert len(validated['stops']) == 2
    assert validated['stops'][0]['id'] == '307250'
    assert validated['stops'][1]['id'] == '307251'
    
    # Check that monitored_lines were preserved
    assert validated['monitored_lines'] == ['116', '117', '118', '144']
    
    # Check that provider-specific fields were preserved
    assert validated['provider_specific']['API_KEY'] == 'dummy_key'
    assert validated['provider_specific']['API_URL'] == 'https://api.delijn.be/v1'

def test_bkk_config_validation():
    """Test validating BKK configuration"""
    validated = validate_provider_config(SAMPLE_BKK_CONFIG)
    
    # Check that STOP_IDS were converted to stops
    assert len(validated['stops']) == 1
    assert validated['stops'][0]['id'] == 'F01111'
    
    # Check that monitored_lines were preserved
    assert validated['monitored_lines'] == ['3040']
    
    # Check that provider-specific fields were preserved
    assert validated['provider_specific']['PROVIDER_ID'] == 'mdb-990'
    assert validated['provider_specific']['CACHE_DIR'] == Path('cache/bkk')
    assert validated['provider_specific']['GTFS_DIR'] == Path('gtfs/bkk')
    assert validated['provider_specific']['API_KEY'] == 'dummy_key'

def test_redact_config_masks_sensitive_values():
    """Test redaction for provider config logging."""
    config = {
        "API_KEY": "secret",
        "MOBILITY_API_PRIMARY_KEY": "secret",
        "LEGACY_REALTIME_URL": "https://example.test/feed?key=secret",
        "provider_specific": {
            "MOBILITY_API_SECONDARY_KEY": "secret",
            "PUBLIC_URL": "https://example.test/feed",
        },
        "stops": [{"id": "5710", "token": "secret"}],
    }

    redacted = redact_config(config)

    assert redacted["API_KEY"] == "<redacted>"
    assert redacted["MOBILITY_API_PRIMARY_KEY"] == "<redacted>"
    assert redacted["LEGACY_REALTIME_URL"] == "<redacted>"
    assert redacted["provider_specific"]["MOBILITY_API_SECONDARY_KEY"] == "<redacted>"
    assert redacted["provider_specific"]["PUBLIC_URL"] == "https://example.test/feed"
    assert redacted["stops"][0]["token"] == "<redacted>"
