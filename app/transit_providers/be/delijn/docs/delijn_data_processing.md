# De Lijn Data Processing

This document explains how we process De Lijn GTFS and GTFS-RT data to show real-time vehicle positions on the map.

## Data Flow

### 1. Configuration
- The app reads monitored line numbers from configuration (e.g., "118")
- Each line can have vehicles running in both directions (HEEN/TERUG)

### 2. GTFS Static Data Processing
- First, we find route_ids in `routes.txt` where `route_short_name` matches our monitored line
- A single line number can have multiple route_ids (e.g., one for each direction)

Example from routes.txt:
| route_id | route_short_name |
|----------|-----------------|
| 3118_2VR3128-20_0 | 118 |
| 3118_2VR3128-19_0 | 118 |
| 3118_2VR3128-19_1 | 118 |
| 3118_2VR3128-20_1 | 118 |

### 3. Trip Information
- Using the route_ids, we find all matching trips in `trips.txt`
- Each trip contains direction and destination information

Example from trips.txt:
| trip_id | route_id | direction_id | trip_headsign |
|---------|----------|--------------|---------------|
| 3118_2VR3128-19_0_2VR3128-19_3288-0863mod2951... | 3118_2VR3128-19_0 | `0` | Brussel Zuid - Itterbeek - `Schepdaal` |
| 3118_2VR3128-19_1_2VR3128-19_3288-0863mod2951... | 3118_2VR3128-19_1 | 1 | Schepdaal - Itterbeek - Brussel Zuid |

### 4. Vehicle Position Matching
- GTFS realtime returns ~800 vehicles across the entire network
- For each vehicle:
  - Extract the `trip_id` from the vehicle data
  - Check if this `trip_id` matches any of our monitored trips
  - If it matches, we get the direction and headsign from our trip mapping
  - Add the vehicle to our processed results with:
    - Line number
    - Direction (HEEN/TERUG)
    - Headsign (final destination)
    - Position (lat/lon)
    - Bearing
    - Delay

Example vehicle position data:
```json
{
  "trip": {
    "tripId": "3118_2VR3128-19_0_2VR3128-19_3288-0863mod2951..."
  },
  "position": {
    "latitude": 50.7654,
    "longitude": 4.5678
  },
  "bearing": 310.03,
  "delay": 180
}
```

## Important Notes

- We must match the entire trip_id exactly, not just parts of it
- Each vehicle's trip_id must match a trip in our GTFS static data
- The headsign from GTFS static data is preferred over the direction
- Direction is used as a fallback if headsign is not available
- Vehicles are only shown if they belong to our monitored lines

## Frontend Display

The frontend receives the processed vehicle data and displays:
1. Vehicle markers on the map with line numbers
2. Popups showing:
   - Line number
   - Headsign (destination)
   - Direction (if headsign not available)
   - Delay information

## Debugging Tips

1. Check the number of route_ids found for a line in routes.txt
2. Verify the number of trips found for these route_ids in trips.txt
3. Look at the trip_ids in GTFS realtime data
4. Ensure exact trip_id matching is working
5. Monitor the number of matched vs unmatched vehicles in the logs 

### Direction Mapping Verification
To verify direction mapping, try:
```bash
curl -X GET "https://api.delijn.be/DLKernOpenData/api/v1/lijnen/3/118/lijnrichtingen/HEEN" \
     -H "Cache-Control: no-cache" \
     -H "Ocp-Apim-Subscription-Key: YOUR_API_KEY" | python -m json.tool
```

Example response:
```json
{
    "entiteitnummer": "3",
    "lijnnummer": "118",
    "richting": "HEEN",
    "omschrijving": "Brussel - Schepdaal",
    "links": {}
}
```

From this, we can see that:
- The bus heading to Schepdaal is going "HEEN"
- In trips.txt, the bus with the headsign for Schepdaal has direction_id = 0
- The bus to Brussel has direction_id = 1 (this is the return, or TERUG direction)
### Example from trips.txt
| route_id | service_id | trip_id | trip_headsign | trip_short_name | direction_id | block_id | shape_id |
|----------|------------|---------|---------------|-----------------|--------------|-----------|-----------|
| 3118_2VR3128-19_0 | 1956 | 3118_101_404_2VR3128-19_3288-0863mod2951_1433_1034d2511267a1e815e372681f1e12b05b4b5c774f7c15b855a68ba7a044d1c8 | Brussel Zuid - Itterbeek - `Schepdaal` | 101 | `0` | 3288-0863mod2951 | 3118404 |
| 3118_2VR3128-19_1 | 1612 | 3118_104_406_2VR3128-19_3288-0863mod2951_1581_c1db6f3129dc61c84f378eeca36d005d31a16fe7d4c45dec41ab0ad8a8576b7b | Schepdaal - Itterbeek - Brussel Zuid | 104 | 1 | 3288-0863mod2951 | 3118406 |

