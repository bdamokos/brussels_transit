function debounce(func, wait) {
    let timeout;
    return function executedFunction(...args) {
        const later = () => {
            clearTimeout(timeout);
            func(...args);
        };
        clearTimeout(timeout);
        timeout = setTimeout(later, wait);
    };
}

// API configuration
const API_BASE_URL = 'http://localhost:8000';

// Map initialization
const map = L.map('map').setView([50.8503, 4.3517], 7);  // Centered on Belgium

// Create custom panes BEFORE adding any layers
map.createPane('routesPane');
map.createPane('stopsPane');
map.createPane('vehiclesPane');

// Set z-index for panes
map.getPane('routesPane').style.zIndex = 400;
map.getPane('stopsPane').style.zIndex = 450;
map.getPane('vehiclesPane').style.zIndex = 500;

// Add the base tile layer
L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
    attribution: '© OpenStreetMap contributors'
}).addTo(map);

// Backend status handling
const backendStatus = document.getElementById('backendStatus');
const providerSelect = document.getElementById('providerSelect');
const fromStationInput = document.getElementById('fromStation');
const toStationInput = document.getElementById('toStation');
const dateInput = document.getElementById('date');

// Provider handling
async function loadProviders() {
    try {
        const response = await fetch(`${API_BASE_URL}/providers`);
        if (!response.ok) {
            throw new Error('Failed to fetch providers');
        }
        const providers = await response.json();
        
        // Clear existing options
        providerSelect.innerHTML = '';
        
        // Add default option
        const defaultOption = document.createElement('option');
        defaultOption.value = '';
        defaultOption.textContent = 'Select a provider';
        providerSelect.appendChild(defaultOption);
        
        // Add providers to dropdown
        providers.forEach(provider => {
            const option = document.createElement('option');
            option.value = provider;
            option.textContent = provider.charAt(0).toUpperCase() + provider.slice(1);
            providerSelect.appendChild(option);
        });
        
        // Enable the select
        providerSelect.disabled = false;
        updateBackendStatus('ready', 'Select a GTFS provider');
        
    } catch (error) {
        console.error('Error loading providers:', error);
        updateBackendStatus('error', 'Failed to load providers');
    }
}

async function setProvider(providerName) {
    if (!providerName) {
        return;
    }

    try {
        updateBackendStatus('loading', `Loading ${providerName} GTFS data...`);
        
        const response = await fetch(`${API_BASE_URL}/provider/${providerName}`, {
            method: 'POST'
        });
        
        if (!response.ok) {
            throw new Error('Failed to set provider');
        }
        
        // Clear existing selections and results
        selectedFromStation = null;
        selectedToStation = null;
        selectedFromStationGroup = null;
        selectedToStationGroup = null;
        fromStationInput.value = '';
        toStationInput.value = '';
        document.getElementById('routeResults').innerHTML = '';
        
        // Clear map layers
        if (routeLayer) {
            map.removeLayer(routeLayer);
            routeLayer = null;
        }
        stopMarkers.forEach(marker => map.removeLayer(marker));
        stopMarkers.clear();

        // Clear cached station data
        availableFromStations = [];
        availableToStations = [];
        
        // Update page title
        document.querySelector('h1').textContent = `${providerName.charAt(0).toUpperCase() + providerName.slice(1)} Route Explorer`;
        
        // Enable inputs
        fromStationInput.disabled = false;
        toStationInput.disabled = false;
        dateInput.disabled = false;
        
        updateBackendStatus('ready', 'Ready');
    } catch (error) {
        console.error('Error setting provider:', error);
        updateBackendStatus('error', `Failed to load ${providerName} data`);
    }
}

// Add provider change event listener
providerSelect.addEventListener('change', (event) => {
    setProvider(event.target.value);
});

// Update backend status handling
function updateBackendStatus(status, message) {
    backendStatus.className = 'backend-status ' + status;
    backendStatus.querySelector('.status-text').textContent = message;
    
    // Enable/disable inputs based on status
    const inputs = [fromStationInput, toStationInput, dateInput];
    inputs.forEach(input => {
        input.disabled = status !== 'ready';
    });
    
    // Initialize dropdowns when backend is ready
    if (status === 'ready') {
        setTimeout(() => {
            backendStatus.classList.add('fade-out');
            setTimeout(() => {
                backendStatus.style.display = 'none';
            }, 2000);
        }, 3000);
    }
}

// Check backend status on load
async function checkBackendStatus() {
    try {
        // Initially disable inputs
        fromStationInput.disabled = true;
        toStationInput.disabled = true;
        dateInput.disabled = true;
        
        // Load providers first
        await loadProviders();
    } catch (error) {
        console.error('Backend status check failed:', error);
        updateBackendStatus('error', 'Backend error - please refresh the page');
    }
}

// Start checking backend status
checkBackendStatus();

// Function to generate a slightly varied color
function generateRouteColor(index) {
    // Convert Flixbus green to HSL
    const hue = 93;  // Green hue
    const saturation = 100;  // Full saturation
    const lightness = 42;  // Base lightness
    
    // Vary the lightness slightly based on the index
    const variedLightness = lightness + (index * 5) % 20 - 10;
    
    return `hsl(${hue}, ${saturation}%, ${variedLightness}%)`;
}

// Global variables
let routeLayer = null;  // Will be initialized when first used
let stopMarkers = new Map();
let availableFromStations = [];
let availableToStations = [];
let selectedFromStation = null;
let selectedToStation = null;
let selectedFromStationGroup = null;
let selectedToStationGroup = null;

// Set default date to today
dateInput.valueAsDate = new Date();

// Update the searchStations function to handle multiple filter stations
async function searchStations(query, filterByStations = null, isOrigin = true) {
    try {
        let allStations = new Set();
        
        if (filterByStations) {
            // If we're filtering, fetch destinations/origins for each station
            const endpoint = isOrigin ? 'origins' : 'destinations';
            const stationIds = Array.isArray(filterByStations) ? 
                filterByStations.map(s => s.id) : [filterByStations.id];
            
            for (const stationId of stationIds) {
                const url = `${API_BASE_URL}/stations/${endpoint}/${stationId}`;
                const response = await fetch(url);
                
                if (response.status === 503) {
                    updateBackendStatus('loading', 'Loading GTFS data...');
                    continue;
                }
                if (!response.ok) {
                    const error = await response.text();
                    console.error(`Failed to fetch stations for ${stationId}:`, error);
                    continue;
                }
                
                const stations = await response.json();
                stations.forEach(station => allStations.add(JSON.stringify(station)));
            }
            
            // Convert back to array and parse JSON
            const stations = Array.from(allStations).map(s => JSON.parse(s));
            
            // Filter by query if provided
            if (query && query.length >= 2) {
                return stations.filter(station => 
                    station.name.toLowerCase().includes(query.toLowerCase())
                );
            }
            return stations;
            
        } else if (query && query.length >= 2) {
            // Regular station search with query
            const url = `${API_BASE_URL}/stations/search?query=${encodeURIComponent(query)}`;
            const response = await fetch(url);
            
            if (response.status === 503) {
                updateBackendStatus('loading', 'Loading GTFS data...');
                return [];
            }
            if (!response.ok) {
                const error = await response.text();
                throw new Error(error || 'Failed to fetch stations');
            }
            
            return await response.json();
        } else {
            // For empty queries, get all stations and return a subset
            const url = `${API_BASE_URL}/stations/search?query=a`;  // Get a broad set of stations
            const response = await fetch(url);
            
            if (response.status === 503) {
                updateBackendStatus('loading', 'Loading GTFS data...');
                return [];
            }
            if (!response.ok) {
                const error = await response.text();
                throw new Error(error || 'Failed to fetch stations');
            }
            
            const stations = await response.json();
            // Return first 50 stations sorted by name
            return stations
                .sort((a, b) => a.name.localeCompare(b.name))
                .slice(0, 50);
        }
    } catch (error) {
        console.error('Error searching stations:', error);
        if (error.message.includes('Failed to fetch')) {
            updateBackendStatus('error', 'Backend error - please refresh the page');
        }
        throw error;
    }
}

// Update the updateAvailableStations function
async function updateAvailableStations(isFrom = true) {
    try {
        let stations;
        if (isFrom && selectedToStation) {
            // Get origins for all selected destination stations
            stations = await searchStations('', 
                selectedToStationGroup || selectedToStation, 
                true
            );
        } else if (!isFrom && selectedFromStation) {
            // Get destinations for all selected origin stations
            stations = await searchStations('', 
                selectedFromStationGroup || selectedFromStation, 
                false
            );
        } else {
            // Get all stations
            stations = await searchStations('');
        }
        
        if (isFrom) {
            availableFromStations = stations;
        } else {
            availableToStations = stations;
        }
        
        return stations;
    } catch (error) {
        console.error('Error updating available stations:', error);
        return [];
    }
}

// Update the station group handling
async function updateStationGroup(station, isFrom) {
    if (!document.getElementById('mergeSameNameStations').checked) {
        return null;
    }
    
    try {
        // Get all stations
        const allStations = await searchStations('');
        // Find all stations with the same name
        const sameNameStations = allStations.filter(s => s.name === station.name);
        console.log(`Found ${sameNameStations.length} stations with name "${station.name}"`);
        return sameNameStations;
    } catch (error) {
        console.error('Error updating station group:', error);
        return null;
    }
}

// Update the createStationList function
function createStationList(stations, container, input, isFrom) {
    container.innerHTML = '';
    container.classList.add('show');
    
    if (stations.length === 0) {
        container.innerHTML = '<div class="dropdown-item no-results">No stations found</div>';
        return;
    }
    
    // Group stations by name if merging is enabled
    const mergeSameNameStations = document.getElementById('mergeSameNameStations').checked;
    let displayStations = stations;
    
    if (mergeSameNameStations) {
        const stationsByName = new Map();
        stations.forEach(station => {
            if (!stationsByName.has(station.name)) {
                stationsByName.set(station.name, []);
            }
            stationsByName.get(station.name).push(station);
        });
        // Use the first station of each group for display
        displayStations = Array.from(stationsByName.values()).map(group => ({
            ...group[0],
            group: group
        }));
    }
    
    displayStations.forEach(station => {
        const item = document.createElement('a');
        item.href = '#';
        item.className = 'dropdown-item';
        item.textContent = station.name;
        if (mergeSameNameStations && station.group && station.group.length > 1) {
            item.textContent += ` (${station.group.length} locations)`;
        }
        
        item.onclick = async (e) => {
            e.preventDefault();
            input.value = station.name;
            
            if (isFrom) {
                selectedFromStation = station;
                selectedFromStationGroup = mergeSameNameStations ? station.group : null;
                console.log('Selected from station group:', selectedFromStationGroup);
                
                // Update available destinations
                updateAvailableStations(false).then(() => {
                    // Clear destination if it's no longer valid
                    const validDestination = availableToStations.some(d => d.id === selectedToStation?.id);
                    if (!validDestination) {
                        toStationInput.value = '';
                        selectedToStation = null;
                        selectedToStationGroup = null;
                    }
                });
            } else {
                selectedToStation = station;
                selectedToStationGroup = mergeSameNameStations ? station.group : null;
                console.log('Selected to station group:', selectedToStationGroup);
                
                // Update available origins
                updateAvailableStations(true).then(() => {
                    // Clear origin if it's no longer valid
                    const validOrigin = availableFromStations.some(o => o.id === selectedFromStation?.id);
                    if (!validOrigin) {
                        fromStationInput.value = '';
                        selectedFromStation = null;
                        selectedFromStationGroup = null;
                    }
                });
            }
            
            // Hide dropdown after selection
            container.classList.remove('show');
            searchRoutes();
        };
        container.appendChild(item);
    });
}

// Initialize dropdowns when backend is ready
async function initializeDropdowns() {
    await updateAvailableStations(true);
    await updateAvailableStations(false);
}

// Show all stations when clicking input (if no text entered)
fromStationInput.addEventListener('click', async () => {
    if (!fromStationInput.value) {
        // If no value, show all available stations
        await updateAvailableStations(true);
        createStationList(availableFromStations, fromStationResults, fromStationInput, true);
    }
});

toStationInput.addEventListener('click', async () => {
    if (!toStationInput.value) {
        // If no value, show all available stations
        await updateAvailableStations(false);
        createStationList(availableToStations, toStationResults, toStationInput, false);
    }
});

// Station search event handlers
fromStationInput.addEventListener('input', debounce(async (e) => {
    const query = e.target.value;
    const resultsContainer = document.getElementById('fromStationResults');
    
    // Show dropdown when input is focused
    resultsContainer.classList.add('show');
    
    if (query.length < 2) {
        // Clear selection if input is cleared
        if (!query) {
            selectedFromStation = null;
            selectedFromStationGroup = null;
            // Reset available destinations
            await updateAvailableStations(false);
            // Show all available stations if input is cleared
            createStationList(availableFromStations, resultsContainer, fromStationInput, true);
        } else {
            // Show message for short query
            resultsContainer.innerHTML = '<div class="dropdown-item text-muted">Please enter at least 2 characters to search</div>';
        }
        return;
    }
    
    try {
        // Filter available stations by query
        const stations = await searchStations(query, selectedToStation, true);
        createStationList(stations, resultsContainer, fromStationInput, true);
    } catch (error) {
        resultsContainer.innerHTML = `
            <div class="dropdown-item text-danger">
                Failed to search stations: ${error.message}
            </div>
        `;
    }
}, 300));

toStationInput.addEventListener('input', debounce(async (e) => {
    const query = e.target.value;
    const resultsContainer = document.getElementById('toStationResults');
    
    // Show dropdown when input is focused
    resultsContainer.classList.add('show');
    
    if (query.length < 2) {
        // Clear selection if input is cleared
        if (!query) {
            selectedToStation = null;
            selectedToStationGroup = null;
            // Reset available origins
            await updateAvailableStations(true);
            // Show all available stations if input is cleared
            createStationList(availableToStations, resultsContainer, toStationInput, false);
        } else {
            // Show message for short query
            resultsContainer.innerHTML = '<div class="dropdown-item text-muted">Please enter at least 2 characters to search</div>';
        }
        return;
    }
    
    try {
        // Filter available stations by query
        const stations = await searchStations(query, selectedFromStation, false);
        createStationList(stations, resultsContainer, toStationInput, false);
    } catch (error) {
        resultsContainer.innerHTML = `
            <div class="dropdown-item text-danger">
                Failed to search stations: ${error.message}
            </div>
        `;
    }
}, 300));

// Add click handlers to hide dropdowns when clicking outside
document.addEventListener('click', (e) => {
    const fromResults = document.getElementById('fromStationResults');
    const toResults = document.getElementById('toStationResults');
    
    // If click is outside the dropdowns and their inputs, hide them
    if (!e.target.closest('#fromStation') && !e.target.closest('#fromStationResults')) {
        fromResults.classList.remove('show');
    }
    if (!e.target.closest('#toStation') && !e.target.closest('#toStationResults')) {
        toResults.classList.remove('show');
    }
});

// Update the searchRoutes function
async function searchRoutes() {
    if (!selectedFromStation || !selectedToStation) {
        return;
    }

    const date = document.getElementById('date').value;
    if (!date) {
        return;
    }

    try {
        const mergeSameNameStations = document.getElementById('mergeSameNameStations').checked;
        
        // Get all station IDs for the search
        let fromStationIds = [];
        let toStationIds = [];
        
        if (mergeSameNameStations) {
            // Use all station IDs from the groups
            fromStationIds = selectedFromStationGroup ? 
                selectedFromStationGroup.map(s => s.id) : [selectedFromStation.id];
            toStationIds = selectedToStationGroup ? 
                selectedToStationGroup.map(s => s.id) : [selectedToStation.id];
        } else {
            fromStationIds = [selectedFromStation.id];
            toStationIds = [selectedToStation.id];
        }
        
        console.log('Searching routes with:', {
            fromStations: fromStationIds,
            toStations: toStationIds,
            date,
            mergingEnabled: mergeSameNameStations
        });
        
        // Make a single API call with all station IDs
        const response = await fetch(
            `${API_BASE_URL}/routes?` + new URLSearchParams({
                from_station: fromStationIds.join(','),
                to_station: toStationIds.join(','),
                date: date
            })
        );
        
        if (!response.ok) {
            throw new Error(`HTTP error! status: ${response.status}`);
        }
        
        const data = await response.json();
        console.log(`Received ${data.routes.length} routes`);
        displayRoutes(data.routes);
        
    } catch (error) {
        console.error('Error searching routes:', error);
        const resultsContainer = document.getElementById('routeResults');
        resultsContainer.innerHTML = `
            <div class="alert alert-danger">
                Failed to search routes: ${error.message}
            </div>
        `;
    }
}

// Helper function to format time
function formatTime(timeStr) {
    if (!timeStr) return '';
    
    const [hours, minutes] = timeStr.split(':');
    const h = parseInt(hours);
    
    if (h >= 24) {
        return `${(h - 24).toString().padStart(2, '0')}:${minutes}+1`;
    }
    return `${hours.padStart(2, '0')}:${minutes}`;
}

// Helper function to normalize time for sorting
function normalizeTime(timeStr) {
    const [hours, minutes] = timeStr.split(':');
    const h = parseInt(hours);
    return (h >= 24 ? h - 24 : h) + parseInt(minutes)/60;
}

// Add route type mapping
const ROUTE_TYPES = {
    0: 'Tram',
    1: 'Subway/Metro',
    2: 'Rail',
    3: 'Bus',
    4: 'Ferry',
    5: 'Cable Tram',
    6: 'Aerial Lift',
    7: 'Funicular',
    11: 'Trolleybus',
    12: 'Monorail'
};

function getRouteTypeLabel(type) {
    return type !== null ? ROUTE_TYPES[type] || `Unknown (${type})` : '';
}

function getRouteName(route) {
    const parts = [];
    if (route.route_short_name) {
        parts.push(`<span class="badge bg-light text-dark me-2">${route.route_short_name}</span>`);
    }
    if (route.route_long_name) {
        parts.push(route.route_long_name);
    } else if (route.route_name && route.route_name !== route.route_short_name) {
        parts.push(route.route_name);
    }
    return parts.join(' ');
}

// Update the displayRoutes function
function displayRoutes(routes) {
    if (!routeLayer) {
        routeLayer = L.layerGroup().addTo(map);
    } else {
        routeLayer.clearLayers();
    }
    stopMarkers.clear();
    
    const resultsContainer = document.getElementById('routeResults');
    if (!routes || routes.length === 0) {
        resultsContainer.innerHTML = `
            <div class="alert alert-warning">
                No routes found for the selected stations and date.
            </div>
        `;
        return;
    }
    
    const showStopIds = document.getElementById('showStopIds').checked;
    const isCondensedView = document.getElementById('condensedTimetable').checked;
    
    if (isCondensedView) {
        // Group routes by line number/name
        const routeGroups = new Map();
        routes.forEach(route => {
            const key = route.route_short_name || route.route_name;
            if (!routeGroups.has(key)) {
                routeGroups.set(key, {
                    route: route,
                    departures: new Set()
                });
            }
            // Only add departure time from the first stop
            const firstStop = route.stops[0];
            routeGroups.get(key).departures.add(firstStop.departure_time);
        });
        
        // Display condensed view
        resultsContainer.innerHTML = Array.from(routeGroups.entries()).map(([key, data]) => {
            const route = data.route;
            const departures = Array.from(data.departures);
            
            // Calculate duration range for this route
            const durations = routes
                .filter(r => (r.route_short_name || r.route_name) === key)
                .map(r => r.duration_minutes);
            const minDuration = Math.min(...durations);
            const maxDuration = Math.max(...durations);
            const durationText = minDuration === maxDuration ? 
                `Duration: ${Math.floor(minDuration / 60)}h ${minDuration % 60}m` :
                `Duration: ${Math.floor(minDuration / 60)}h ${minDuration % 60}m - ${Math.floor(maxDuration / 60)}h ${maxDuration % 60}m`;
            
            // Group departures by hour
            const departuresByHour = new Map();
            departures.forEach(time => {
                const [hours] = time.split(':');
                const hour = parseInt(hours) >= 24 ? parseInt(hours) - 24 : parseInt(hours);
                if (!departuresByHour.has(hour)) {
                    departuresByHour.set(hour, new Set());
                }
                departuresByHour.get(hour).add(time);
            });
            
            const routeColorStyle = route.color ? 
                `background-color: #${route.color}; color: #${route.text_color || 'FFFFFF'};` : 
                'background-color: #73D700; color: #FFFFFF;';

            const routeTypeLabel = getRouteTypeLabel(route.route_type);
            const routeTypeHtml = routeTypeLabel ? 
                `<span class="badge bg-secondary me-2">${routeTypeLabel}</span>` : '';
            
            const sortedHours = Array.from(departuresByHour.keys()).sort((a, b) => a - b);
            
            return `
                <div class="card route-card">
                    <div class="card-header" style="${routeColorStyle}">
                        <h5 class="mb-0">
                            ${routeTypeHtml}
                            ${getRouteName(route)}
                        </h5>
                    </div>
                    <div class="card-body">
                        <p class="mb-2">${durationText}</p>
                        <p class="mb-2">Service days: ${route.service_days.map(day => 
                            day.charAt(0).toUpperCase() + day.slice(1)
                        ).join(', ')}</p>
                        <div class="table-responsive">
                            <table class="table table-sm timetable">
                                <thead>
                                    <tr>
                                        <th>Hour</th>
                                        <th>Departures</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    ${sortedHours.map(hour => {
                                        const times = Array.from(departuresByHour.get(hour))
                                            .sort((a, b) => normalizeTime(a) - normalizeTime(b))
                                            .map(t => formatTime(t).split(':')[1]);
                                        return `
                                            <tr>
                                                <td class="hour-cell">${hour.toString().padStart(2, '0')}</td>
                                                <td class="departures-cell">${times.join(' ')}</td>
                                            </tr>
                                        `;
                                    }).join('')}
                                </tbody>
                            </table>
                        </div>
                    </div>
                </div>
            `;
        }).join('');
    } else {
        // Display detailed view
        resultsContainer.innerHTML = routes.map(route => {
            const firstStop = route.stops[0];
            const isDepartureNextDay = parseInt(firstStop.departure_time.split(':')[0]) >= 24;
            
            const routeColorStyle = route.color ? 
                `background-color: #${route.color}; color: #${route.text_color || 'FFFFFF'};` : 
                'background-color: #73D700; color: #FFFFFF;';

            const routeTypeLabel = getRouteTypeLabel(route.route_type);
            const routeTypeHtml = routeTypeLabel ? 
                `<span class="badge bg-secondary me-2">${routeTypeLabel}</span>` : '';
            
            return `
                <div class="card route-card">
                    <div class="card-header" style="${routeColorStyle}">
                        <h5 class="mb-0">
                            ${routeTypeHtml}
                            ${getRouteName(route)}
                        </h5>
                    </div>
                    <div class="card-body">
                        <p class="mb-2">Duration: ${Math.floor(route.duration_minutes / 60)}h ${route.duration_minutes % 60}m</p>
                        <p class="mb-2">Service days: ${route.service_days.map(day => 
                            day.charAt(0).toUpperCase() + day.slice(1)
                        ).join(', ')}</p>
                        ${isDepartureNextDay ? 
                            '<p class="mb-2 text-info">Note: This trip departs after midnight of the selected date</p>' 
                            : ''}
                        <div class="table-responsive">
                            <table class="table table-sm">
                                <thead>
                                    <tr>
                                        <th>Stop</th>
                                        ${showStopIds ? '<th>Stop ID</th>' : ''}
                                        <th>Arrival</th>
                                        <th>Departure</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    ${route.stops.map(stop => `
                                        <tr>
                                            <td>${stop.name}</td>
                                            ${showStopIds ? `<td><small class="text-muted">${stop.id}</small></td>` : ''}
                                            <td class="stop-time">${formatTime(stop.arrival_time)}</td>
                                            <td class="stop-time">${formatTime(stop.departure_time)}</td>
                                        </tr>
                                    `).join('')}
                                </tbody>
                            </table>
                        </div>
                    </div>
                </div>
            `;
        }).join('');
    }
    
    // Collect all coordinates for bounds calculation
    let allCoordinates = [];
    
    // Display routes on map
    routes.forEach((route, index) => {
        const routeColor = route.color ? 
            `#${route.color}` : generateRouteColor(index);
        
        // Get coordinates from route shape or stops
        let coordinates = [];
        if (route.shape && Array.isArray(route.shape.points) && route.shape.points.length > 0) {
            coordinates = route.shape.points.map(point => {
                if (Array.isArray(point)) {
                    return point;
                }
                if (typeof point === 'string' && point.startsWith('(') && point.endsWith(')')) {
                    const [lat, lon] = point.slice(1, -1).split(',').map(Number);
                    return [lat, lon];
                }
                if (point && typeof point === 'object' && 'lat' in point && 'lon' in point) {
                    return [point.lat, point.lon];
                }
                return null;
            }).filter(point => point !== null);
        }
        
        if (coordinates.length < 2) {
            coordinates = route.stops.map(stop => [stop.location.lat, stop.location.lon]);
        }
        
        if (coordinates.length < 2) {
            console.error('Insufficient coordinates for route:', route);
            return;
        }
        
        // Add coordinates to bounds calculation
        allCoordinates.push(...coordinates);
        
        // Draw route line
        const routeLine = L.polyline(coordinates, {
            color: routeColor,
            weight: 3,
            opacity: 0.8,
            pane: 'routesPane'
        }).addTo(routeLayer);
        
        // Add markers for stops
        route.stops.forEach(stop => {
            const markerKey = `${stop.location.lat},${stop.location.lon}`;
            if (!stopMarkers.has(markerKey)) {
                const marker = L.circleMarker([stop.location.lat, stop.location.lon], {
                    radius: 6,
                    fillColor: '#fff',
                    color: '#000',
                    weight: 2,
                    opacity: 1,
                    fillOpacity: 0.8,
                    pane: 'stopsPane'
                });
                
                const popupContent = showStopIds ? 
                    `<strong>${stop.name}</strong><br><small class="text-muted">ID: ${stop.id}</small>` :
                    `<strong>${stop.name}</strong>`;
                
                marker.bindPopup(popupContent, {
                    offset: [0, -2],
                    closeButton: true
                });
                
                marker.addTo(routeLayer);
                stopMarkers.set(markerKey, { marker, stop });
            }
        });
    });
    
    // Fit map to show all coordinates
    if (allCoordinates.length > 0) {
        const bounds = L.latLngBounds(allCoordinates);
        map.fitBounds(bounds, { padding: [50, 50] });
    }
}

// Date change event handler
dateInput.addEventListener('change', searchRoutes); 

// Move all styles to the top of the file, after the global variables
const styles = `
    .stop-marker {
        background: none;
        border: none;
    }
    .stop-marker-inner {
        width: 12px;
        height: 12px;
        background: white;
        border: 2px solid black;
        border-radius: 50%;
    }
    .stop-popup {
        min-width: 200px;
        padding: 5px;
    }
    .stop-popup h6 {
        margin: 0 0 8px 0;
        font-size: 14px;
    }
    .stop-times {
        font-size: 12px;
        line-height: 1.4;
    }
    .timetable .hour-cell {
        font-weight: bold;
        width: 80px;
    }
    .timetable .departures-cell {
        font-family: monospace;
        letter-spacing: 0.1em;
    }
`;

// Create and append stylesheet once
const styleSheet = document.createElement("style");
styleSheet.textContent = styles;
document.head.appendChild(styleSheet);

// Add this helper function at the file level
function findClosestPointIndex(points, target) {
    let minDist = Infinity;
    let minIndex = 0;
    
    points.forEach((point, index) => {
        const dist = Math.pow(point[0] - target[0], 2) + Math.pow(point[1] - target[1], 2);
        if (dist < minDist) {
            minDist = dist;
            minIndex = index;
        }
    });
    
    return minIndex;
} 

// Update the event listener for the show stop IDs checkbox
document.getElementById('showStopIds').addEventListener('change', () => {
    // Update all existing marker popups
    stopMarkers.forEach((markerInfo, key) => {
        const showStopIds = document.getElementById('showStopIds').checked;
        const popupContent = showStopIds ? 
            `<strong>${markerInfo.stop.name}</strong><br><small class="text-muted">ID: ${markerInfo.stop.id}</small>` :
            `<strong>${markerInfo.stop.name}</strong>`;
        markerInfo.marker.setPopupContent(popupContent);
    });
    
    // Refresh the route display
    if (selectedFromStation && selectedToStation) {
        searchRoutes();
    }
});

// Update the event listener for the merge stations checkbox
document.getElementById('mergeSameNameStations').addEventListener('change', async () => {
    const mergingEnabled = document.getElementById('mergeSameNameStations').checked;
    console.log('Merging stations:', mergingEnabled);
    
    if (mergingEnabled) {
        // Update station groups based on current selections
        if (selectedFromStation) {
            selectedFromStationGroup = await updateStationGroup(selectedFromStation, true);
        }
        if (selectedToStation) {
            selectedToStationGroup = await updateStationGroup(selectedToStation, false);
        }
    } else {
        // Clear station groups
        selectedFromStationGroup = null;
        selectedToStationGroup = null;
    }
    
    // Refresh routes with updated groups
    if (selectedFromStation && selectedToStation) {
        searchRoutes();
    }
}); 

// Add event listener for the condensed timetable checkbox
document.getElementById('condensedTimetable').addEventListener('change', () => {
    if (selectedFromStation && selectedToStation) {
        searchRoutes();
    }
}); 