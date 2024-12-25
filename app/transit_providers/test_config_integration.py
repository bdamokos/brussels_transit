"""Integration tests for the configuration system"""

import pytest
from pathlib import Path
import sys
import types
from config import get_config, _import_config
from .config_schema import validate_provider_config
from .config_compat import convert_to_provider_format
from .be.stib import StibProvider
from .be.stib.api import get_waiting_times as stib_get_waiting_times
from .be.delijn import DelijnProvider
from .hu.bkk import BKKProvider
from .hu.bkk.api import get_waiting_times as bkk_get_waiting_times

@pytest.fixture
def test_config():
    """Create a test configuration module"""
    config = types.ModuleType('config.test')
    
    # Add test configuration
    config.STIB_STOPS = [{
        'id': '8122',
        'name': 'ROODEBEEK',
        'lines': {
            '1': ['STOCKEL', "GARE DE L'OUEST"],
            '5': ['HERRMANN-DEBROUX', 'ERASME']
        },
        'direction': 'Suburb'
    }]
    
    config.DELIJN_STOP_IDS = ['307250', '307251']
    config.DELIJN_MONITORED_LINES = ['116', '117', '118', '144']
    
    config.PROVIDER_CONFIG = {
        'bkk': {
            'STOP_IDS': ['F01111'],
            'MONITORED_LINES': ['3040']
        }
    }
    
    return config

@pytest.fixture
def mock_config(monkeypatch, test_config):
    """Mock the config loading to use our test config"""
    def mock_import_config(module_name: str):
        if module_name == 'test':
            return test_config
        return None
    
    monkeypatch.setattr('config._import_config', mock_import_config)
    monkeypatch.setattr('config.local_config', test_config)
    monkeypatch.setattr('config.default_config', None)
    
    return test_config

def test_config_loading_and_merging(mock_config):
    """Test that configs are properly loaded and merged"""
    # Get config from our test module
    stib_stops = mock_config.STIB_STOPS
    assert len(stib_stops) == 1
    assert stib_stops[0]['id'] == '8122'
    assert '5' in stib_stops[0]['lines']
    
    # Validate the config
    validated = validate_provider_config({'STIB_STOPS': stib_stops})
    assert len(validated['stops']) == 1
    assert len(validated['stops'][0]['lines']['5']) == 2
    
    # Convert back to STIB format
    converted = convert_to_provider_format('stib', validated)
    assert len(converted['STIB_STOPS']) == 1
    assert len(converted['STIB_STOPS'][0]['lines']['5']) == 2

@pytest.mark.asyncio
async def test_stib_provider_integration():
    """Test that STIB provider works with the new config format"""
    # Get STIB config
    stib_config = get_config('STIB_STOPS')
    validated = validate_provider_config({'STIB_STOPS': stib_config})
    
    # Convert to old format
    old_format = convert_to_provider_format('stib', validated)
    
    # Initialize STIB provider with old format
    provider = StibProvider()
    provider.config = old_format
    
    # Test that we can get real-time data using the API function
    times = await stib_get_waiting_times()
    assert isinstance(times, dict)

@pytest.mark.asyncio
async def test_delijn_provider_integration():
    """Test that De Lijn provider works with the new config format"""
    # Get De Lijn config with defaults
    delijn_config = {
        'STOP_IDS': get_config('DELIJN_STOP_IDS', []),
        'MONITORED_LINES': get_config('DELIJN_MONITORED_LINES', [])
    }
    validated = validate_provider_config(delijn_config)
    
    # Convert to old format
    old_format = convert_to_provider_format('delijn', validated)
    
    # Initialize De Lijn provider with old format
    provider = DelijnProvider()
    provider.config = old_format
    
    # Verify config structure
    assert isinstance(provider.stop_ids, (list, set))
    assert isinstance(provider.monitored_lines, (list, set))

@pytest.mark.asyncio
async def test_bkk_provider_integration():
    """Test that BKK provider works with the new config format"""
    # Get BKK config from PROVIDER_CONFIG with defaults
    bkk_config = get_config('PROVIDER_CONFIG', {}).get('bkk', {
        'STOP_IDS': [],
        'MONITORED_LINES': []
    })
    validated = validate_provider_config(bkk_config)
    
    # Convert to old format
    old_format = convert_to_provider_format('bkk', validated)
    
    # Initialize BKK provider with old format
    provider = BKKProvider()
    provider.config = old_format
    
    # Test that we can get real-time data using the API function
    times = await bkk_get_waiting_times()
    assert isinstance(times, dict)

def test_frontend_data_structure():
    """Test that the frontend data structure remains compatible"""
    # Get STIB config as an example
    stib_config = get_config('STIB_STOPS')
    validated = validate_provider_config({'STIB_STOPS': stib_config})
    
    # Check that the structure matches what frontend expects
    for stop in validated['stops']:
        assert 'id' in stop
        if 'lines' in stop:
            for line_id, destinations in stop['lines'].items():
                assert isinstance(line_id, str)
                assert isinstance(destinations, list)
                for dest in destinations:
                    # Frontend expects either strings or objects with type and value
                    assert isinstance(dest, (dict, str))
                    if isinstance(dest, dict):
                        assert 'type' in dest
                        assert 'value' in dest

def test_config_roundtrip():
    """Test that config can be converted to new format and back without loss"""
    # Original STIB config
    original = {
        'STIB_STOPS': [{
            'id': '8122',
            'name': 'ROODEBEEK',
            'lines': {
                '1': ['STOCKEL', "GARE DE L'OUEST"]
            },
            'direction': 'Suburb'
        }],
        'API_KEY': 'test_key'
    }
    
    # Convert to new format
    validated = validate_provider_config(original)
    
    # Convert back to old format
    converted = convert_to_provider_format('stib', validated)
    
    # Check that the structure is preserved
    assert len(converted['STIB_STOPS']) == len(original['STIB_STOPS'])
    assert converted['STIB_STOPS'][0]['id'] == original['STIB_STOPS'][0]['id']
    assert converted['STIB_STOPS'][0]['lines']['1'] == original['STIB_STOPS'][0]['lines']['1']
    assert converted['API_KEY'] == original['API_KEY'] 