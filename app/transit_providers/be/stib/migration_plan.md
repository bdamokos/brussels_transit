# STIB Provider Migration Plan

## Current Status (Test Results)

### Working Endpoints ✓
- [x] /api/data (v1)
- [x] /api/static_data (v1)
- [x] /api/stop_names (v1)
- [x] /api/stop_coordinates/{id} (v1)
- [x] /api/stib/config (v2)
- [x] /api/stib/route/{id} (v2, partial - missing shapes)
- [x] /api/stib/stops (v2)
- [x] /api/stib/stop/{id}/coordinates (v2)
- [x] /api/stib/waiting_times (v2)
- [x] /api/messages (v1)
- [x] /api/stib/messages (v2)

### Partially Working Endpoints ⚠️
- [~] /api/stib/vehicles (v2, returns data but format differs from v1)
- [~] /api/stib/colors (v2, works but needs line number handling)

### Non-working Endpoints ❌
- [ ] /api/waiting_times (v1)
- [ ] /api/vehicles (v1)
- [ ] /api/stib/realtime (v2)
- [ ] /api/stib/static (v2)
- [ ] /api/stib/get_stop_by_name (v2)
- [ ] /api/stib/get_nearest_stops (v2)

## Immediate Priorities

### Phase 1: Fix Critical Endpoints
1. Stop Data (HIGH PRIORITY)
   - [x] Fix /api/stib/stops endpoint
   - [x] Fix /api/stib/stop/{id}/coordinates endpoint
   - [x] Ensure data format matches v1

1b. Regression testing for all endpoints marked as working
   - [x] /api/static_data (v1)
   - [x] /api/stop_names (v1)
   - [x] /api/stop_coordinates/{id} (v1)
   - [x] /api/stib/config (v2)
   - [x] /api/stib/route/{id} (v2, partial - missing shapes, some stops have null coordinates)
   - [x] /api/stib/stops (v2)
   - [x] /api/stib/stop/{id}/coordinates (v2)
   - [ ] /api/data (v1) - test last as it depends on other endpoints

2. Real-time Data (HIGH PRIORITY)
   - [x] Fix waiting times endpoint (empty array issue)
     - [x] Filter stops using configured STIB_STOPS from config
       - [x] Extract monitored stop IDs and line numbers
       - [x] Only return data for monitored stops
       - [x] Fix regression: if a stop is given as parameter, return data for that stop even if it's not monitored
       - [x] Fix regression: if a list of stops is given as parameter, return data for all stops even if some are not monitored
     - [x] Use stop_coordinates.py for coordinates
     - [x] Use get_stop_names.py for stop names
     - [x] Match v1 data structure exactly:
       - [x] Return data under "stops_data" key
       - [x] Match waiting times format:
         ```json
         {
           "destination": "DESTINATION",
           "formatted_time": "14:30",
           "message": "",
           "minutes": 5
         }
         ```
       - [x] Ensure all fields are in same order as v1
     - [x] Add proper error handling and logging
       - [x] Log API failures
       - [x] Log data parsing issues
       - [x] Log when stops/lines are not found
   - [ ] Align vehicle positions format with v1
        - [ ] Analysis phase:
            - [ ] Check raw STIB response
            - [ ] Check v1 response
            - [ ] Check DeLijn response
            - [ ] Check frontend expectation
        - [ ] Document findings in the migration plan, and document code where needed
        - [ ] Implementation phase:
            - [ ] Add vehicle positions to v2 response

   - [x] Fix messages endpoint (NoneType error)
     - [x] Fix message parsing
     - [x] Add line filtering
     - [x] Add stop name lookup
     - [x] Add error handling
     - [x] Add tests

2b. Regression testing for all endpoints marked as working

3. Route Data (MEDIUM PRIORITY)
   - [ ] Add shape data to route endpoint
   - [ ] Fix colors endpoint to handle single line requests
   - [ ] Standardize route data format

3b. Regression testing for all endpoints marked as working

### Phase 2: Implement Aggregated Endpoints
1. Realtime Endpoint
   - [ ] Create /api/stib/realtime endpoint
   - [ ] Combine waiting times, messages, vehicles
   - [ ] Match v1 data format

1b. Regression testing for all endpoints marked as working

2. Static Endpoint
   - [ ] Create /api/stib/static endpoint
   - [ ] Include routes, stops, colors
   - [ ] Match v1 data format

2b. Regression testing for all endpoints marked as working

3. See if /api/data endpoint finally works in both v1 and v2

### Phase 3: Fix Search Endpoints
1. Stop Search
   - [ ] Fix parameter handling for get_stop_by_name
   - [ ] Fix parameter handling for get_nearest_stops
   - [ ] Add proper error handling

### Phase 4: Lateral improvements
1. Stop coordinates and names if not found on API, test in GTFS (stops_gtfs.json)
   - [~] Implement in v2
     - [x] Create stops_gtfs.json from GTFS data
     - [x] Add fallback to GTFS data when API returns null coordinates
     - [x] Add caching to avoid repeated GTFS lookups
     - [x] Investigate stops with format like "6934F" and "5053G" that are missing from both API and GTFS
     - [x] Add stop ID normalization function (remove letters from stop IDs)
     - [x] Add logging for stops not found in either source
   - [ ] Backport to v1
     - [ ] Share GTFS data lookup between v1 and v2
     - [ ] Ensure consistent coordinate format
2. Figure out if we are actually downloading the GTFS data
   - [ ] Add logging
   - [ ] Check if the file is actually downloaded
   - [ ] See what functions use GTFS data
   - [ ] See if anyone is overwriting cache/stib/stops_gtfs.json (is it supposed to contain all stops from the GTFS or just the ones that we have looked up)
   - [ ] See what is using stib/cache/stops.json and if it is still needed
3. . Message Handling
   - [ ] Implement language fallback for service messages (en -> fr -> nl -> raw message)
   - [ ] Add debug logging for message language selection
   - [ ] Add configuration for message language, and fallback order

## Technical Debt Items
1. Data Format Standardization
   - [ ] Document v1 response formats
   - [ ] Create format conversion utilities
   - [ ] Add format validation

2. Error Handling
   - [ ] Add proper error messages
   - [ ] Implement parameter validation
   - [ ] Add request logging

3. Testing
   - [ ] Add unit tests for each endpoint
   - [ ] Add format validation tests
   - [ ] Add integration tests

## Dependencies
- GTFS data access
- API keys and authentication
- Cache directory structure
- Configuration files

## Success Criteria
- All v2 endpoints match v1 functionality
- No degradation in performance
- Improved error handling
- Better code organization
- Comprehensive tests
- Complete documentation

## Notes
- Keep v1 endpoints working during migration
- Test each fix thoroughly
- Document all changes
- Monitor API usage limits 