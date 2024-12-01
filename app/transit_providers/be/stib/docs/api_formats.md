# STIB API Format Differences (v1 vs v2)

## Overview

This document describes the differences between v1 and v2 API formats for the `/api/data` endpoint.

## Top-Level Structure

### v1 Format
```json
{
    "stops_data": { /* Stop data object */ },
    "messages": {
        "messages": [ /* Message array */ ]
    },
    "processed_vehicles": [ /* Vehicle array */ ],
    "errors": [ /* Error array */ ]
}
```

### v2 Format
```json
{
    "stops": { /* Stop data object */ },
    "messages": [ /* Message array */ ],
    "vehicles": {
        "vehicles": [ /* Vehicle array */ ]
    },
    "colors": { /* Line colors object */ }
}
```

## Stop Data Format

### v1 Format (`stops_data`)
```json
{
    "stop_id": {
        "name": "Stop Name",
        "coordinates": {
            "lat": 50.8,
            "lon": 4.3
        },
        "lines": {
            "line_number": {
                "destination": [{
                    "destination": "DESTINATION",
                    "formatted_time": "14:30",
                    "message": "",
                    "minutes": 5
                }]
            }
        }
    }
}
```

### v2 Format (`stops`)
```json
{
    "stop_id": {
        "name": "Stop Name",
        "coordinates": {
            "coordinates": {
                "lat": 50.8,
                "lon": 4.3
            },
            "metadata": {
                "source": "api|gtfs|cache_gtfs",
                "original_id": "optional_id",
                "warning": "optional_warning"
            }
        },
        "lines": {
            "line_number": {
                "destination": [{
                    "destination": "DESTINATION",
                    "destination_data": {
                        "fr": "French Name",
                        "nl": "Dutch Name"
                    },
                    "formatted_time": "14:30",
                    "message": "",
                    "minutes": 5,
                    "_metadata": {
                        "language": {
                            "available": ["fr", "nl"],
                            "provided": "fr",
                            "requested": null,
                            "warning": null
                        }
                    }
                }]
            }
        }
    }
}
```

## Message Format

### v1 Format
```json
{
    "messages": {
        "messages": [{
            "text": "Message text",
            "lines": ["line1", "line2"],
            "points": ["stop1", "stop2"],
            "stops": ["Stop Name 1", "Stop Name 2"],
            "priority": 5,
            "type": "LongText",
            "is_monitored": true
        }]
    }
}
```

### v2 Format
```json
{
    "messages": [{
        "text": "Message text",
        "lines": ["line1", "line2"],
        "points": ["stop1", "stop2"],
        "stops": ["Stop Name 1", "Stop Name 2"],
        "priority": 5,
        "type": "LongText",
        "is_monitored": true,
        "_metadata": {
            "language": {
                "available": ["en", "fr", "nl"],
                "provided": "en",
                "requested": null,
                "warning": null
            }
        }
    }]
}
```

## Vehicle Format

### v1 Format
```json
{
    "processed_vehicles": [{
        "line": "64",
        "direction": "City",
        "current_segment": ["stop1", "stop2"],
        "distance_to_next": 0,
        "interpolated_position": [50.8, 4.3],
        "is_valid": true,
        "raw_data": {
            "distance": 0,
            "next_stop": "stop1"
        },
        "bearing": 0.0,
        "segment_length": 374.47,
        "shape_segment": [[4.3, 50.8], [4.4, 50.9]]
    }]
}
```

### v2 Format
```json
{
    "vehicles": {
        "vehicles": [{
            "line": "64",
            "direction": "City",
            "current_segment": ["stop1", "stop2"],
            "distance_to_next": 0,
            "interpolated_position": [50.8, 4.3],
            "is_valid": true,
            "raw_data": {
                "distance": 0,
                "next_stop": "stop1"
            },
            "bearing": 0.0,
            "segment_length": 374.47,
            "shape_segment": [[4.3, 50.8], [4.4, 50.9]]
        }]
    }
}
```

## Additional v2 Features

### Line Colors
```json
{
    "colors": {
        "line_number": {
            "background": "#RRGGBB",
            "text": "#RRGGBB"
        }
    }
}
```

## Key Differences

1. **Structure Changes**:
   - `stops_data` renamed to `stops`
   - Messages flattened from nested to array
   - Vehicles moved to nested structure
   - Added colors data

2. **Enhanced Metadata**:
   - Stop coordinates include source information
   - Messages include language metadata
   - Destinations include multiple language versions

3. **Language Support**:
   - Added language metadata throughout
   - Multiple language versions for destinations
   - Language fallback information

4. **Error Handling**:
   - v1: Simple error array
   - v2: Metadata includes warnings and source information

## Frontend Compatibility

The frontend currently expects the v1 format. When migrating to v2:
1. Stop coordinates need to be extracted from the nested structure
2. Messages need to be flattened
3. Vehicle data structure needs to be adjusted
4. Language metadata can be used for better localization 