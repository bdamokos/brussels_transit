/**
 * Map management module
 */

import { properTitle } from './utils.js';
import { getProvider } from './provider.js';

// Map instance and layers
let map;
let stopsLayer;
let routesLayer;
let vehiclesLayer;
let vehicleMarkers = new Map();

/**
 * Initialize the map and its layers
 */
export function initializeMap() {
    // Create the map
    map = L.map('map', {
        center: [map_config.center.lat, map_config.center.lon],
        zoom: map_config.zoom,
        zoomControl: true,
        layers: []
    });
    
    // Add the tile layer
    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
        maxZoom: map_config.maxZoom,
        minZoom: map_config.minZoom,
        attribution: '© OpenStreetMap contributors'
    }).addTo(map);
    
    // Create custom panes
    map.createPane('routesPane');
    map.createPane('stopsPane');
    map.createPane('vehiclesPane');
    
    // Set z-index for panes
    map.getPane('routesPane').style.zIndex = 400;
    map.getPane('stopsPane').style.zIndex = 450;
    map.getPane('vehiclesPane').style.zIndex = 500;
    
    // Create feature groups
    routesLayer = L.featureGroup([], { pane: 'routesPane' }).addTo(map);
    stopsLayer = L.featureGroup([], { pane: 'stopsPane' }).addTo(map);
    vehiclesLayer = L.featureGroup([], { pane: 'vehiclesPane' }).addTo(map);
    
    // Add layer control
    const overlays = {
        "Routes": routesLayer,
        "Stops": stopsLayer,
        "Vehicles": vehiclesLayer
    };
    L.control.layers(null, overlays).addTo(map);
}

/**
 * Reset the map view to default
 */
export function resetMapView() {
    map.setView(
        [map_config.center.lat, map_config.center.lon],
        map_config.zoom
    );
}

/**
 * Add a stop marker to the map
 * @param {string} stopId - Stop ID
 * @param {object} stopInfo - Stop information
 */
export function addStopMarker(stopId, stopInfo) {
    const marker = L.circleMarker([stopInfo.coordinates.lat, stopInfo.coordinates.lon], {
        radius: 8,
        fillColor: '#fff',
        color: '#000',
        weight: 2,
        opacity: 1,
        fillOpacity: 0.8,
        pane: 'stopsPane'
    });
    
    marker.stopId = stopId;
    updateStopMarkerPopup(marker, stopInfo);
    marker.addTo(stopsLayer);
}

/**
 * Update a stop marker's popup content
 * @param {L.CircleMarker} marker - The marker to update
 * @param {object} stopInfo - Stop information
 */
function updateStopMarkerPopup(marker, stopInfo) {
    let popupContent = `<strong>${properTitle(stopInfo.name)}</strong><br>`;
    
    if (stopInfo.lines) {
        for (const [line, destinations] of Object.entries(stopInfo.lines)) {
            const provider = getProvider(stopInfo.provider);
            const lineColor = provider ? provider.getLineColor(line) : '#666';
            
            const style = typeof lineColor === 'object'
                ? `
                    --text-color: ${lineColor.text};
                    --bg-color: ${lineColor.background};
                    --text-border-color: ${lineColor.text_border};
                    --bg-border-color: ${lineColor.background_border};
                `
                : `background-color: ${lineColor}`;
            
            popupContent += `
                <div class="line-info">
                    <span class="${provider ? 'provider-line-number' : 'line-number'}" 
                          style="${style}">
                        ${line}
                    </span>
                    → ${destinations.join(', ')}
                </div>
            `;
        }
    }
    
    marker.bindPopup(popupContent);
}

/**
 * Add a route to the map
 * @param {string} line - Line number
 * @param {object} routeData - Route data
 */
export function addRoute(line, routeData) {
    const provider = getProvider(routeData.provider);
    const lineColor = provider ? provider.getLineColor(line) : '#666';
    const color = typeof lineColor === 'object' ? lineColor.background : lineColor;
    
    if (Array.isArray(routeData.shape)) {
        // Single shape
        L.polyline(routeData.shape.map(coord => [coord[1], coord[0]]), {
            color,
            weight: 3,
            opacity: 0.7,
            pane: 'routesPane',
            interactive: false
        }).addTo(routesLayer);
    } else if (routeData.variants) {
        // Multiple variants
        routeData.variants.forEach(variant => {
            if (variant.coordinates) {
                L.polyline(variant.coordinates, {
                    color,
                    weight: 3,
                    opacity: 0.7,
                    pane: 'routesPane',
                    interactive: false
                }).addTo(routesLayer);
            }
        });
    }
}

/**
 * Update vehicle positions on the map
 * @param {Array} vehicles - List of vehicle positions
 */
export function updateVehicles(vehicles) {
    const newVehiclePositions = new Set();
    
    vehicles.forEach(vehicle => {
        const position = vehicle.interpolated_position || 
                        (vehicle.position ? [vehicle.position.lat, vehicle.position.lon] : null);
        
        if (!position) return;
        
        const [lat, lon] = position;
        const provider = getProvider(vehicle.provider);
        const lineColor = provider ? provider.getLineColor(vehicle.line) : '#666';
        
        // Create a key for this vehicle
        const vehicleKey = `${vehicle.line}-${vehicle.direction}`;
        
        // Try to find an existing marker
        let existingMarker = null;
        let minDistance = Infinity;
        
        vehicleMarkers.forEach((marker, key) => {
            if (!key.startsWith(vehicleKey)) return;
            
            const markerPos = marker.getLatLng();
            const distance = map.distance([lat, lon], [markerPos.lat, markerPos.lng]);
            
            if (distance < 500 && distance < minDistance) {
                existingMarker = marker;
                minDistance = distance;
            }
        });
        
        if (existingMarker) {
            // Update existing marker
            existingMarker.setLatLng([lat, lon]);
            updateVehicleMarker(existingMarker, vehicle, lineColor);
        } else {
            // Create new marker
            const marker = createVehicleMarker(vehicle, lineColor, lat, lon);
            const markerKey = `${vehicleKey}-${lat}-${lon}`;
            vehicleMarkers.set(markerKey, marker);
            newVehiclePositions.add(markerKey);
        }
    });
    
    // Remove markers that are no longer present
    vehicleMarkers.forEach((marker, key) => {
        if (!newVehiclePositions.has(key)) {
            marker.remove();
            vehicleMarkers.delete(key);
        }
    });
}

/**
 * Create a new vehicle marker
 * @param {object} vehicle - Vehicle information
 * @param {string|object} lineColor - Line color information
 * @param {number} lat - Latitude
 * @param {number} lon - Longitude
 * @returns {L.Marker} The created marker
 */
function createVehicleMarker(vehicle, lineColor, lat, lon) {
    const marker = L.marker([lat, lon], {
        icon: createVehicleIcon(vehicle, lineColor),
        pane: 'vehiclesPane',
        zIndexOffset: 1000
    });
    
    updateVehiclePopup(marker, vehicle);
    marker.addTo(vehiclesLayer);
    
    return marker;
}

/**
 * Create a vehicle icon
 * @param {object} vehicle - Vehicle information
 * @param {string|object} lineColor - Line color information
 * @returns {L.DivIcon} The created icon
 */
function createVehicleIcon(vehicle, lineColor) {
    let style;
    if (typeof lineColor === 'object') {
        style = `
            --text-color: ${lineColor.text};
            --bg-color: ${lineColor.background};
            --text-border-color: ${lineColor.text_border};
            --bg-border-color: ${lineColor.background_border};
        `;
    } else {
        style = `--bg-color: ${lineColor}; --text-color: white;`;
    }
    
    return L.divIcon({
        html: `
            <div class="vehicle-marker-content" style="
                --bearing: ${vehicle.bearing}deg;
                ${style}
            ">
                <div class="line-number">
                    ${vehicle.line}
                </div>
                <div class="vehicle-arrow"></div>
            </div>
        `,
        className: 'vehicle-marker',
        iconSize: [20, 20],
        iconAnchor: [10, 10],
        popupAnchor: [0, -10]
    });
}

/**
 * Update a vehicle marker's icon and popup
 * @param {L.Marker} marker - The marker to update
 * @param {object} vehicle - Vehicle information
 * @param {string|object} lineColor - Line color information
 */
function updateVehicleMarker(marker, vehicle, lineColor) {
    marker.setIcon(createVehicleIcon(vehicle, lineColor));
    updateVehiclePopup(marker, vehicle);
}

/**
 * Update a vehicle marker's popup content
 * @param {L.Marker} marker - The marker to update
 * @param {object} vehicle - Vehicle information
 */
function updateVehiclePopup(marker, vehicle) {
    const directionDisplay = vehicle.headsign || vehicle.direction;
    const delayMinutes = vehicle.delay ? Math.round(vehicle.delay / 60) : 0;
    
    marker.bindPopup(`
        <strong>Line ${vehicle.line}</strong><br>
        To: ${directionDisplay}<br>
        ${vehicle.current_segment ? `Between: ${vehicle.current_segment.join(' and ')}<br>` : ''}
        ${delayMinutes ? `Delay: ${delayMinutes} minutes` : ''}
    `);
}

// Export map instance for use in other modules
export { map }; 