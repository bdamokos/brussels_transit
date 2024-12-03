# Transit Display Architecture

## Directory Structure
```
app/
├── templates/
│   ├── js/
│   │   ├── config/
│   │   │   └── map_config.js     # Map configuration (center, zoom, etc.)
│   │   ├── core/
│   │   │   ├── init.js          # Core initialization (map, layers, geolocation)
│   │   │   ├── map.js          # Map-related functions (layers, markers, etc.)
│   │   │   ├── stops.js        # Stop display and updates
│   │   │   ├── vehicles.js     # Vehicle display and updates
│   │   │   ├── messages.js     # Service message display
│   │   │   └── utils.js        # Shared utilities (formatters, calculations)
│   │   └── main.js             # Main entry point
│   └── css/
│       └── index.css           # Core CSS styles
│   └── static/                    # Static assets
│       └── css/
│       └── js/
├── transit_providers/
│   ├── be/                     # Belgium
│   │   ├── stib/              # STIB (Brussels)
│   │   │   ├── js/
│   │   │   │   ├── provider.js
│   │   │   │   ├── colors.js
│   │   │   │   └── formatters.js
│   │   │   ├── css/
│   │   │   │   └── stib.css
│   │   │   ├── docs/
│   │   │   │   └── README.md
│   │   │   └── images/
│   │   │       └── logo.png
│   │   └── delijn/            # De Lijn (Flanders)
│   │       ├── js/
│   │       │   ├── provider.js
│   │       │   ├── colors.js
│   │       │   └── formatters.js
│   │       ├── css/
│   │       │   └── delijn.css
│   │       ├── docs/
│   │       │   └── README.md
│   │       └── images/
│   │           └── logo.png
│   └── fr/                     # France (prepared for future)
│       └── ratp/              # Example future provider

```

## Core Concepts

### 1. Provider Interface
Each transit provider (STIB, De Lijn) must implement these core methods:
- \`isEnabled()\`: Check if provider is configured and available
- \`getConfig()\`: Get provider configuration
- \`getStops()\`: Get list of stops
- \`getWaitingTimes()\`: Get real-time waiting times
- \`getVehicles()\`: Get vehicle positions
- \`getMessages()\`: Get service messages
- \`getRoutes()\`: Get route shapes

Optional methods:
- \`getColors()\`: Get provider-specific colors
- \`customizeStopDisplay()\`: Custom stop display logic
- \`customizeMessageDisplay()\`: Custom message display logic

### 2. Data Structures

#### Stop Data
\`\`\`javascript
{
    id: "stop_id",
    name: "Stop Name",
    coordinates: {
        lat: 50.8465,
        lon: 4.3517
    },
    lines: {
        "line_id": {
            "destination": [{
                minutes: 5,
                scheduled_time: "14:30",
                realtime_time: "14:32",
                is_realtime: true,
                message: null
            }]
        }
    }
}
\`\`\`

#### Vehicle Data
\`\`\`javascript
{
    line: "line_id",
    direction: "destination",
    coordinates: {
        lat: 50.8465,
        lon: 4.3517
    },
    bearing: 45,
    delay: 120,  // seconds
    is_realtime: true
}
\`\`\`

#### Message Data
\`\`\`javascript
{
    title: "Message Title",
    description: "Message Description",
    affected_lines: ["line1", "line2"],
    affected_stops: ["stop1", "stop2"],
    is_monitored: true,
    period: {
        start: "2024-01-01T00:00:00",
        end: "2024-01-02T00:00:00"
    }
}
\`\`\`

### 3. Core Components

#### Map Manager
- Handles map initialization
- Manages layers (routes, stops, vehicles)
- Updates markers and popups
- Handles user interaction

#### Stop Display
- Renders stop information
- Updates waiting times
- Handles provider-specific display customization

#### Vehicle Display
- Shows vehicle positions
- Updates vehicle movements
- Handles vehicle popups

#### Message Display
- Shows service messages
- Separates primary/secondary messages
- Handles provider-specific message formatting

### 4. Utilities
- Distance calculations
- Time formatting
- Color handling
- Error management
- Geolocation services

## Implementation Plan

1. Set up directory structure
2. Create base provider interface
3. Implement core components
4. Create STIB provider
5. Create De Lijn provider
6. Add error handling
7. Add documentation
8. Add tests

## Usage Example

\`\`\`javascript
// Initialize transit display
const transitDisplay = new TransitDisplay();

// Register providers
transitDisplay.registerProvider(new STIBProvider());
transitDisplay.registerProvider(new DeLijnProvider());

// Initialize display
await transitDisplay.initialize();

// Start refresh cycle
transitDisplay.startRefreshCycle();
\`\`\`

## Adding New Providers

To add a new transit provider:

1. Create a new directory under \`providers/\`
2. Implement the provider interface
3. Add provider-specific formatters
4. Register the provider in \`main.js\`

## Error Handling

All components should:
- Log errors appropriately
- Fail gracefully
- Show user-friendly error messages
- Continue operating with partial data

## Performance Considerations

- Minimize DOM updates
- Use efficient data structures
- Cache provider data appropriately
- Handle network failures gracefully 