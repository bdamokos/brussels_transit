"""Tests for the configuration schema and validation"""

import pytest
from pathlib import Path
from .config_schema import (
    DirectionType,
    LineDestination,
    StopConfig,
    ProviderConfig,
    validate_provider_config
)

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