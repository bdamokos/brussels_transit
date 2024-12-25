"""Integration tests for the configuration system"""

import pytest
from pathlib import Path
from config import get_config
from .config_schema import validate_provider_config
from .be.stib.api import StibAPI
from .be.delijn.api import DeLijnAPI
from .hu.bkk.api import BkkAPI

@pytest.fixture
def sample_config_dir(tmp_path):
    """Create a temporary config directory with sample config files"""
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    
    # Create sample default.py
    with open(config_dir / "default.py", "w") as f:
        f.write("""
STIB_STOPS = [
    {
        'id': '8122',
        'name': 'ROODEBEEK',
        'lines': {
            '1': ['STOCKEL', "GARE DE L'OUEST"]
        },
        'direction': 'Suburb'
    }
]

PROVIDER_CONFIG = {
    'bkk': {
        'STOP_IDS': ['F01111'],
        'MONITORED_LINES': ['3040']
    }
}
""")
    
    # Create sample local.py that overrides some values
    with open(config_dir / "local.py", "w") as f:
        f.write("""
STIB_STOPS = [
    {
        'id': '8122',
        'name': 'ROODEBEEK',
        'lines': {
            '1': ['STOCKEL', "GARE DE L'OUEST"],
            '5': ['HERRMANN-DEBROUX', 'ERASME']
        },
        'direction': 'Suburb'
    }
]
""")
    
    return config_dir

def test_config_loading_and_merging(sample_config_dir, monkeypatch):
    """Test that configs are properly loaded and merged"""
    # Set up environment
    monkeypatch.setenv('PYTHONPATH', str(sample_config_dir))
    
    # Get merged config
    stib_stops = get_config('STIB_STOPS')
    assert len(stib_stops) == 1
    assert stib_stops[0]['id'] == '8122'
    assert '5' in stib_stops[0]['lines']  # From local.py
    
    # Validate the merged config
    validated = validate_provider_config({'STIB_STOPS': stib_stops})
    assert len(validated['stops']) == 1
    assert len(validated['stops'][0]['lines']['5']) == 2

@pytest.mark.asyncio
async def test_stib_provider_integration():
    """Test that STIB provider works with the new config format"""
    # Get STIB config
    stib_config = get_config('STIB_STOPS')
    validated = validate_provider_config({'STIB_STOPS': stib_config})
    
    # Initialize STIB API with validated config
    api = StibAPI(validated)
    
    # Test that we can still get stop info
    stops = await api.get_stops()
    assert len(stops) > 0
    
    # Test that we can get real-time data
    times = await api.get_waiting_times()
    assert isinstance(times, dict)

@pytest.mark.asyncio
async def test_delijn_provider_integration():
    """Test that De Lijn provider works with the new config format"""
    # Get De Lijn config
    delijn_config = {
        'STOP_IDS': get_config('DELIJN_STOP_IDS'),
        'MONITORED_LINES': get_config('DELIJN_MONITORED_LINES')
    }
    validated = validate_provider_config(delijn_config)
    
    # Initialize De Lijn API with validated config
    api = DeLijnAPI(validated)
    
    # Test that we can still get stop info
    stops = await api.get_stops()
    assert len(stops) > 0

@pytest.mark.asyncio
async def test_bkk_provider_integration():
    """Test that BKK provider works with the new config format"""
    # Get BKK config from PROVIDER_CONFIG
    bkk_config = get_config('PROVIDER_CONFIG', {}).get('bkk', {})
    validated = validate_provider_config(bkk_config)
    
    # Initialize BKK API with validated config
    api = BkkAPI(validated)
    
    # Test that we can still get stop info
    stops = await api.get_stops()
    assert len(stops) > 0

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