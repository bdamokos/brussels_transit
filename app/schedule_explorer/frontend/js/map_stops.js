import { getStopsInBbox, getWaitingTimes } from './api.js';
import { formatTime, formatDuration, simulatedAnnealing, rgbToHex } from './utils.js';

// Store markers by stop ID for easy updates
const stopMarkers = new Map();
// Store route colors by route ID
const routeColors = new Map();
// Store the current provider ID
let currentProviderId = null;
// Store the map instance
let map = null;
// Store the loading state
let isLoading = false;
// Store the debounce timer
let debounceTimer = null;

// Initialize the map
export function initMap() {
    // Create the map if it doesn't exist
    if (!map) {
        map = L.map('map').setView([50.8465, 4.3517], 13);  // Center on Brussels
        L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
            maxZoom: 19,
            attribution: '© OpenStreetMap contributors'
        }).addTo(map);

        // Add locate control
        L.control.locate({
            position: 'topleft',
            strings: {
                title: "Show me where I am"
            }
        }).addTo(map);

        // Add event listeners
        map.on('moveend', debounceLoadStops);
        map.on('zoomend', debounceLoadStops);
    }

    // Return an object with methods to control the map
    return {
        setProvider: function(providerId) {
            currentProviderId = providerId;
            // Clear existing markers
            stopMarkers.forEach(marker => map.removeLayer(marker));
            stopMarkers.clear();
            routeColors.clear();
            // Load stops for the new provider
            loadStops();
        },
        getMap: function() {
            return map;
        }
    };
}

// Debounce the loadStops function to avoid too many requests
function debounceLoadStops() {
    if (debounceTimer) {
        clearTimeout(debounceTimer);
    }
    debounceTimer = setTimeout(loadStops, 300);  // Wait 300ms after the last event
}

// Load stops within the current map bounds
async function loadStops() {
    if (isLoading || !map || !currentProviderId) return;

    try {
        isLoading = true;
        showLoadingIndicator();

        const bounds = map.getBounds();
        const stops = await getStopsInBbox(
            currentProviderId,
            bounds.getSouth(),
            bounds.getWest(),
            bounds.getNorth(),
            bounds.getEast()
        );

        // Remove markers that are no longer in view
        for (const [stopId, marker] of stopMarkers) {
            if (!stops.find(stop => stop.id === stopId)) {
                map.removeLayer(marker);
                stopMarkers.delete(stopId);
            }
        }

        // Update or add markers for stops
        for (const stop of stops) {
            updateStopMarker(stop);
        }

        // Update route colors if needed
        updateRouteColors(stops);

    } catch (error) {
        console.error('Error loading stops:', error);
        showError('Failed to load stops. Please try again later.');
    } finally {
        isLoading = false;
        hideLoadingIndicator();
    }
}

// Update or create a marker for a stop
function updateStopMarker(stop) {
    let marker = stopMarkers.get(stop.id);
    
    if (!marker) {
        // Create new marker
        marker = L.marker([stop.location.lat, stop.location.lon]);
        marker.addTo(map);
        stopMarkers.set(stop.id, marker);
    }

    // Update popup content
    const popupContent = createPopupContent(stop);
    marker.bindPopup(popupContent);
}

// Create HTML content for the stop popup
function createPopupContent(stop) {
    const div = document.createElement('div');
    div.className = 'stop-popup';

    // Add stop name
    const nameDiv = document.createElement('div');
    nameDiv.className = 'stop-name';
    nameDiv.textContent = stop.name;
    div.appendChild(nameDiv);

    // Add routes if available
    if (stop.routes && stop.routes.length > 0) {
        const routesDiv = document.createElement('div');
        routesDiv.className = 'stop-routes';
        
        // Group routes by short_name
        const routeGroups = new Map();
        for (const route of stop.routes) {
            const key = route.short_name || route.route_id;
            if (!routeGroups.has(key)) {
                routeGroups.set(key, []);
            }
            routeGroups.get(key).push(route);
        }

        // Create route badges
        for (const [routeName, routes] of routeGroups) {
            const route = routes[0];  // Use first route for display
            const badge = document.createElement('span');
            badge.className = 'route-badge';
            badge.textContent = routeName;
            
            // Set colors
            const color = route.color ? `#${route.color}` : '#000000';
            const textColor = route.text_color ? `#${route.text_color}` : '#FFFFFF';
            badge.style.backgroundColor = color;
            badge.style.color = textColor;
            
            // Add tooltip with destinations
            const destinations = routes.map(r => r.last_stop).join(' / ');
            badge.title = destinations;
            
            routesDiv.appendChild(badge);
        }
        
        div.appendChild(routesDiv);
    }

    // Add waiting times button
    const waitingTimesBtn = document.createElement('button');
    waitingTimesBtn.className = 'btn btn-sm btn-primary mt-2';
    waitingTimesBtn.textContent = 'View waiting times';
    waitingTimesBtn.onclick = () => showWaitingTimes(stop.id);
    div.appendChild(waitingTimesBtn);

    return div;
}

// Show waiting times in a modal
async function showWaitingTimes(stopId) {
    try {
        const waitingTimes = await getWaitingTimes(currentProviderId, stopId);
        // TODO: Show waiting times in a modal
        console.log('Waiting times:', waitingTimes);
    } catch (error) {
        console.error('Error loading waiting times:', error);
        showError('Failed to load waiting times. Please try again later.');
    }
}

// Update route colors
function updateRouteColors(routes) {
    // Generate a palette of RGB colors
    const colors = [];
    for (let r = 0; r <= 255; r += 32) {
        for (let g = 0; g <= 255; g += 32) {
            for (let b = 0; b <= 255; b += 32) {
                colors.push([r, g, b]);
            }
        }
    }

    // Use simulated annealing to select distinct colors
    const result = simulatedAnnealing(colors, routes.length);
    console.log(`Generated ${routes.length} distinct colors in ${result.time}ms`);

    // Assign colors to routes
    routes.forEach((route, index) => {
        routeColors[route.id] = rgbToHex(result.colors[index]);
    });
}

// Show loading indicator
function showLoadingIndicator() {
    const loading = document.getElementById('loading');
    if (loading) {
        loading.style.display = 'flex';
    }
}

// Hide loading indicator
function hideLoadingIndicator() {
    const loading = document.getElementById('loading');
    if (loading) {
        loading.style.display = 'none';
    }
}

// Show error message
function showError(message) {
    const error = document.getElementById('error');
    if (error) {
        error.textContent = message;
        error.style.display = 'block';
        setTimeout(() => {
            error.style.display = 'none';
        }, 5000);  // Hide after 5 seconds
    }
} 