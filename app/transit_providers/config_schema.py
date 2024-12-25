from typing import Dict, List, Optional, Union
from pydantic import BaseModel, Field, model_validator
from enum import Enum

class DirectionType(str, Enum):
    """Type of direction specification"""
    STOP_NAME = "stop_name"  # Destination specified by stop name
    DIRECTION_NAME = "direction_name"  # Direction specified by name (e.g., "City"/"Suburb")
    DIRECTION_ID = "direction_id"  # Direction specified by GTFS direction_id
    STOP_ID = "stop_id"  # Destination specified by stop_id
    HEADSIGN = "headsign"  # Direction specified by GTFS trip_headsign

class LineDestination(BaseModel):
    """Configuration for a line's destination
    
    Examples:
        By stop name:
            {"type": "stop_name", "value": "ROGIER"}
        By direction name:
            {"type": "direction_name", "value": "City"}
        By GTFS direction_id:
            {"type": "direction_id", "value": 0}
        By destination stop_id:
            {"type": "stop_id", "value": "5710"}
        By GTFS headsign:
            {"type": "headsign", "value": "HEYSEL via City"}
    """
    type: DirectionType
    value: Union[str, int]  # Can be stop_name, direction_name, direction_id, stop_id, or headsign

class StopConfig(BaseModel):
    """Configuration for a single stop"""
    id: str = Field(..., description="Stop ID in the provider's system")
    name: Optional[str] = Field(None, description="Human-readable name of the stop")
    lines: Optional[Dict[str, List[Union[str, LineDestination]]]] = Field(
        None,
        description="Dictionary mapping line IDs to list of destinations"
    )
    direction: Optional[str] = Field(
        None,
        description="Legacy field: Direction of travel (e.g., 'City' or 'Suburb')"
    )

    @model_validator(mode='after')
    def convert_legacy_format(self) -> 'StopConfig':
        """Convert legacy direction format to new format"""
        if self.lines:
            converted_lines = {}
            for line_id, destinations in self.lines.items():
                converted_destinations = []
                for dest in destinations:
                    if isinstance(dest, str):
                        # Convert string destination to LineDestination
                        converted_destinations.append(
                            LineDestination(type=DirectionType.STOP_NAME, value=dest)
                        )
                    else:
                        converted_destinations.append(dest)
                converted_lines[line_id] = converted_destinations
            self.lines = converted_lines
        return self

class ProviderConfig(BaseModel):
    """Standard configuration structure for all providers"""
    stops: List[StopConfig] = Field(
        default_factory=list,
        description="List of stops to monitor"
    )
    monitored_lines: Optional[List[str]] = Field(
        None,
        description="List of line IDs to monitor (if not specified in stops)"
    )
    provider_specific: Optional[Dict] = Field(
        None,
        description="Provider-specific configuration options"
    )

def validate_provider_config(config: Dict) -> Dict:
    """Validate and normalize provider configuration"""
    # Extract the standardized fields
    standard_config = {
        'stops': [],
        'monitored_lines': config.get('MONITORED_LINES', []),
        'provider_specific': {}
    }
    
    # Handle STIB-style configuration
    if 'STIB_STOPS' in config:
        standard_config['stops'].extend(config['STIB_STOPS'])
    
    # Handle De Lijn/BKK-style configuration
    if 'STOP_IDS' in config:
        for stop_id in config['STOP_IDS']:
            standard_config['stops'].append({'id': stop_id})
    
    # Move all other fields to provider_specific
    for key, value in config.items():
        if key not in ['STIB_STOPS', 'STOP_IDS', 'MONITORED_LINES']:
            standard_config['provider_specific'][key] = value
    
    # Validate using Pydantic model
    validated = ProviderConfig(**standard_config)
    return validated.model_dump(exclude_none=True)  # Using model_dump instead of dict 