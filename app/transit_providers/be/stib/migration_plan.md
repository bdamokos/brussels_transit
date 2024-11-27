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

### Partially Working Endpoints ⚠️
- [~] /api/stib/vehicles (v2, returns data but format differs from v1)
- [~] /api/stib/waiting_times (v2, returns empty array)
- [~] /api/stib/colors (v2, works but needs line number handling)

### Non-working Endpoints ❌
- [ ] /api/waiting_times (v1)
- [ ] /api/vehicles (v1)
- [ ] /api/messages (v1)
- [ ] /api/stib/messages (v2)
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
   - [ ] Fix waiting times endpoint (empty array issue)
   - [ ] Align vehicle positions format with v1
   - [ ] Fix messages endpoint (NoneType error)

3. Route Data (MEDIUM PRIORITY)
   - [ ] Add shape data to route endpoint
   - [ ] Fix colors endpoint to handle single line requests
   - [ ] Standardize route data format

### Phase 2: Implement Aggregated Endpoints
1. Realtime Endpoint
   - [ ] Create /api/stib/realtime endpoint
   - [ ] Combine waiting times, messages, vehicles
   - [ ] Match v1 data format

2. Static Endpoint
   - [ ] Create /api/stib/static endpoint
   - [ ] Include routes, stops, colors
   - [ ] Match v1 data format

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
     - [ ] Investigate stops with format like "6934F" and "5053G" that are missing from both API and GTFS
     - [ ] Consider adding a stop ID normalization function
     - [ ] Add logging for stops not found in either source
   - [ ] Backport to v1
     - [ ] Share GTFS data lookup between v1 and v2
     - [ ] Ensure consistent coordinate format

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