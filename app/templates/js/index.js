// Global variables
let map;
let stopsLayer;
let routesLayer;
let vehiclesLayer;
let vehicleMarkers = new Map();  // Store markers by their unique position key
let stopNames = {};
let delijnConfig = null;
let DELIJN_STOP_IDS = new Set();  // Will be populated when we get delijnConfig
let userLocation = null;
let locationWatchId = null;
let lastLocationUpdate = 0;
const isSecure = window.isSecureContext || location.protocol === 'https:' || location.hostname === 'localhost';

// Add this function to fetch De Lijn route data
async function fetchDeLijnRoutes(lines) {
    const routes = {};
    for (const line of lines) {
        try {
            const response = await fetch(`/api/delijn/lines/${line}/route`);
            if (response.ok) {
                routes[line] = await response.json();
                console.log(`Fetched De Lijn route for line ${line}:`, routes[line]);
            }
        } catch (e) {
            console.error(`Error fetching route for De Lijn line ${line}:`, e);
        }
    }
    return routes;
}

// Add this helper near the top with other utility functions
async function isDelijnEnabled() {
    try {
        const response = await fetch('/api/delijn/config');
        return response.ok;
    } catch (error) {
        console.log('De Lijn provider not enabled');
        return false;
    }
}

// Modify the fetchAndUpdateData function to add checks
async function fetchAndUpdateData() {
    try {
        console.log("Starting data fetch...");
        
        // Fetch STIB data
        const stibResponse = await fetch('/api/data');
        console.log("STIB response status:", stibResponse.status);
        const stibData = await stibResponse.json();
        
        // Check if De Lijn is enabled before making any De Lijn API calls
        const delijnEnabled = await isDelijnEnabled();
        
        // Initialize De Lijn data with empty defaults
        let delijnData = { stops_data: {}, messages: [], processed_vehicles: [] };
        let delijnMessages = [];  // Changed from { messages: [] } to []
        let delijnVehiclesData = [];
        
        if (delijnEnabled) {
            // Only make De Lijn API calls if the provider is enabled
            const delijnResponse = await fetch('/api/delijn/data');
            if (delijnResponse.ok) {
                const responseData = await delijnResponse.json();
                // Ensure we preserve the stops_data structure
                delijnData = {
                    ...responseData,
                    stops_data: delijnData.stops_data
                };
                console.log("De Lijn data:", delijnData);
            }
            
            // Fetch global De Lijn waiting times
            const delijnWaitingTimesResponse = await fetch('/api/delijn/waiting_times');
            if (delijnWaitingTimesResponse.ok) {
                const waitingTimesData = await delijnWaitingTimesResponse.json();
                console.log("De Lijn waiting times raw data:", waitingTimesData);
                
                // Store colors for later use
                if (waitingTimesData.colors) {
                    Object.entries(waitingTimesData.colors).forEach(([line, colors]) => {
                        lineColors[line] = colors;
                    });
                }
                
                // Transform waiting times data into the expected format
                if (waitingTimesData.stops) {
                    console.log("Processing De Lijn stops:", Object.keys(waitingTimesData.stops));
                    Object.entries(waitingTimesData.stops).forEach(([stopId, stopInfo]) => {
                        console.log(`Processing stop ${stopId}:`, stopInfo);
                        if (stopInfo.lines) {
                            console.log(`Stop ${stopId} has lines:`, stopInfo.lines);
                            delijnData.stops_data[stopId] = {
                                name: stopInfo.name,
                                coordinates: stopInfo.coordinates,
                                lines: stopInfo.lines
                            };
                        }
                    });
                    console.log("Transformed De Lijn stops data:", delijnData.stops_data);
                }
            }
            
            const delijnMessagesResponse = await fetch('/api/delijn/messages');
            if (delijnMessagesResponse.ok) {
                delijnMessages = await delijnMessagesResponse.json();  // Extract messages array directly
                console.log("De Lijn messages:", delijnMessages);
            }
            
            if (delijnConfig?.monitored_lines) {
                const delijnVehiclesPromises = delijnConfig.monitored_lines.map(async line => {
                    try {
                        const response = await fetch(`/api/delijn/vehicles/${line}`);
                        if (response.ok) {
                            const data = await response.json();
                            return Array.isArray(data) ? data : data.vehicles || [];
                        }
                    } catch (error) {
                        console.warn(`Error fetching vehicles for line ${line}:`, error);
                    }
                    return [];
                });
                delijnVehiclesData = await Promise.all(delijnVehiclesPromises);
            }
        }

        // Combine the data
        const combinedData = {
            stops_data: {
                ...stibData.stops_data,
                ...delijnData.stops_data
            },
            messages: {
                messages: [
                    ...(stibData.messages?.messages || []),
                    ...delijnMessages  // Use the messages array directly
                ]
            },
            processed_vehicles: [
                ...(stibData.processed_vehicles || []),
                ...delijnVehiclesData.flat()
            ],
            errors: [
                ...(stibData.errors || []),
                ...(delijnData.errors || [])
            ]
        };

        console.log("Combined data:", combinedData);

        // Update the UI with combined data
        console.log("Updating stops data...");
        updateStopsData(combinedData.stops_data);
        
        console.log("Updating service messages...");
        updateServiceMessages(combinedData.messages);
        
        console.log("Updating map data...");
        await updateMapData(combinedData);
        
        console.log("Updating errors...");
        updateErrors(combinedData.errors, []);

    } catch (error) {
        console.error('Error fetching data:', error);
        const errorsContainer = document.getElementById('errors-container');
        if (errorsContainer) {
            errorsContainer.innerHTML = `
                <div class="error-section">
                    <div class="error-message">
                        Error fetching real-time data: ${error.message}
                    </div>
                </div>
            `;
        }
    }
}
function updateStopsData(stopsData) {
    console.log("Updating stops data with:", stopsData);
    const sections = document.querySelectorAll('.stop-section');
    
    sections.forEach(section => {
        const stopName = section.dataset.stopName;
        const content = section.querySelector('.stop-content');
        const physicalStops = content.querySelectorAll('.physical-stop');
        
        physicalStops.forEach(stopContainer => {
            const stopId = stopContainer.dataset.stopId;
            // Determine provider based on stop ID
            const isDelijn = DELIJN_STOP_IDS.has(stopId);
            const provider = isDelijn ? 'delijn' : 'stib';
            stopContainer.dataset.provider = provider;  // Set the provider in the DOM
            const stopInfo = stopsData[stopId];
            
            console.log(`Processing stop ${stopId}:`, {
                provider,
                isDelijn,
                hasData: !!stopInfo,
                hasLines: stopInfo?.lines,
                data: stopInfo,
                inDelijnSet: DELIJN_STOP_IDS.has(stopId),
                delijnStopIds: Array.from(DELIJN_STOP_IDS)
            });
            
            // Clear existing content but keep divider if it exists
            const divider = stopContainer.querySelector('.stop-divider');
            stopContainer.innerHTML = '';
            if (divider) {
                stopContainer.appendChild(divider);
            }
            
            if (stopInfo && stopInfo.lines) {
                for (const [line, destinations] of Object.entries(stopInfo.lines)) {
                    for (const [destination, times] of Object.entries(destinations)) {
                        if (!times || times.length === 0) continue;
                        
                        const lineContainer = document.createElement('div');
                        lineContainer.className = 'line-container';
                        
                        const lineColor = lineColors[line];
                        console.log(`Line ${line} color:`, lineColor);
                        const style = isDelijn && typeof lineColor === 'object'
                            ? `
                                --text-color: ${lineColor.text};
                                --bg-color: ${lineColor.background};
                                --text-border-color: ${lineColor.text_border};
                                --bg-border-color: ${lineColor.background_border};
                            `
                            : `background-color: ${lineColor || '#666'}`;

                        // Process each passing time
                        const timeGroups = [];
                        for (let i = 0; i < times.length; i++) {
                            const time = times[i];
                            console.log(`Processing time entry for ${line} to ${destination}:`, time);  // Debug log
                            
                            if (time.message) {
                                timeGroups.push({
                                    message: time.message,
                                    is_message: true
                                });
                            } else if (isDelijn) {
                                // For De Lijn data, preserve all time information
                                timeGroups.push({
                                    realtime_minutes: time.realtime_minutes,
                                    realtime_time: time.realtime_time,
                                    scheduled_minutes: time.scheduled_minutes,
                                    scheduled_time: time.scheduled_time,
                                    delay: time.delay,
                                    is_realtime: time.is_realtime,
                                    is_delijn: true
                                });
                            } else {
                                // For STIB data
                                timeGroups.push({
                                    minutes: time.minutes,
                                    formatted_time: time.formatted_time,
                                    is_delijn: false
                                });
                            }
                        }
                        
                        lineContainer.innerHTML = `
                            <div class="line-info">
                                <span class="${isDelijn ? 'delijn-line-number' : 'line-number'}" 
                                      style="${style}">
                                    ${line}
                                </span>
                                <span class="direction">→ ${destination}</span>
                            </div>
                            <div class="times-container">
                                ${timeGroups.map(group => {
                                    if (group.message) {
                                        return `<span class="service-message end-service">${group.message}</span>`;
                                    } else if (group.is_delijn) {
                                        // For De Lijn data
                                        if (group.is_realtime) {
                                            const delay = group.delay || 0;
                                            const delayClass = delay < 0 ? 'early' : delay > 0 ? 'late' : 'on-time';
                                            
                                            // Check if realtime and scheduled times are the same
                                            const sameTime = group.realtime_time === group.scheduled_time;
                                            
                                            return `
                                                <span class="time-display delijn">
                                                    <span class="minutes ${delayClass}">${group.realtime_minutes}</span>
                                                    <span class="actual-time">
                                                        ${sameTime ? 
                                                            `(⚡/ ${group.realtime_time})` : 
                                                            `(⚡${group.realtime_time} - 🕒${group.scheduled_time})`}
                                                    </span>
                                                </span>
                                            `;
                                        } else {
                                            return `
                                                <span class="time-display delijn">
                                                    <span class="minutes">${group.scheduled_minutes}</span>
                                                    <span class="actual-time">(🕒 ${group.scheduled_time})</span>
                                                </span>
                                            `;
                                        }
                                    } else {
                                        const minutes = group.minutes;
                                        const time = group.formatted_time;
                                        
                                        if (minutes === undefined || !time) {
                                            console.debug('Missing time data:', group);
                                            return '';
                                        }

                                        return `
                                            <span class="time-display">
                                                <span class="minutes ${parseInt(minutes) < 0 ? 'late' : ''}">${minutes}'</span>
                                                <span class="actual-time"> (${time})</span>
                                            </span>
                                        `;
                                    }
                                }).filter(Boolean).join('')}
                            </div>
                        `;
                        
                        stopContainer.appendChild(lineContainer);
                    }
                }
            } else {
                const noData = document.createElement('div');
                noData.className = 'no-data';
                noData.textContent = 'No real-time data available';
                stopContainer.appendChild(noData);
            }
        });
    });
    
    // Then update map markers
    stopsLayer.eachLayer(marker => {
        const stopId = marker.stopId;
        const stopInfo = stopsData[stopId];
        const isDelijn = delijnConfig?.stops?.some(stop => stop.id === stopId);
        
        if (stopInfo && stopInfo.lines) {
            let popupContent = `<strong>${properTitle(stopInfo.name)}</strong><br>`;
            
            for (const [line, destinations] of Object.entries(stopInfo.lines)) {
                for (const [destination, times] of Object.entries(destinations)) {
                    if (!times || times.length === 0) continue;
                    
                    const lineColor = lineColors[line];
                    const style = isDelijn && typeof lineColor === 'object'
                        ? `
                            --text-color: ${lineColor.text};
                            --bg-color: ${lineColor.background};
                            --text-border-color: ${lineColor.text_border};
                            --bg-border-color: ${lineColor.background_border};
                        `
                        : `background-color: ${lineColor || '#666'}`;
                    
                    // Add line and destination
                    popupContent += `
                        <div class="line-info">
                            <span class="${isDelijn ? 'delijn-line-number' : 'line-number'}" 
                                  style="${style}">
                                ${line}
                            </span>
                            → ${destination}
                        </div>
                    `;
                    
                    // Add next arrival times (limit to 2 for popup)
                    const nextArrivals = times.slice(0, 2).map(time => {
                        if (isDelijn && time.is_realtime) {
                            const sameTime = time.realtime_time === time.scheduled_time;
                            const minutes = time.realtime_minutes !== undefined ? time.realtime_minutes : time.scheduled_minutes;
                            return sameTime ? 
                                `${minutes} (⚡/🕒 ${time.realtime_time})` : 
                                `${minutes} (⚡${time.realtime_time} - 🕒${time.scheduled_time})`;
                        } else {
                            const minutes = time.minutes !== undefined ? time.minutes : time.scheduled_minutes;
                            const displayTime = time.formatted_time || time.scheduled_time;
                            if (minutes === undefined || !displayTime) {
                                console.debug('Missing time data in popup:', time);
                                return '';
                            }
                            return `${minutes} (${displayTime})`;
                        }
                    }).filter(Boolean).join(', ');
                    
                    popupContent += `<div class="arrival-times">${nextArrivals}</div>`;
                }
            }
            
            // Update popup content
            marker.setPopupContent(popupContent);
            
            // If popup is open, update it
            if (marker.isPopupOpen()) {
                marker.getPopup().update();
            }
        }
    });
}

function updateServiceMessages(messages) {
    const primaryContainer = document.getElementById('primary-messages-container');
    const secondaryContainer = document.getElementById('secondary-messages-container');
    
    if (!messages || !messages.messages) {
        primaryContainer.innerHTML = '';
        secondaryContainer.innerHTML = '';
        return;
    }
    
    const primaryMessages = messages.messages.filter(m => m.is_monitored);
    const secondaryMessages = messages.messages.filter(m => !m.is_monitored);
    
    // Make this function async and await the renderMessages
    (async () => {
        // Update primary messages
        if (primaryMessages.length > 0) {
            primaryContainer.innerHTML = `
                <div class="primary-messages">
                    <h2>Important Service Messages</h2>
                    ${await renderMessages(primaryMessages, false)}
                </div>`;
        } else {
            primaryContainer.innerHTML = '';
        }
        
        // Update secondary messages
        if (secondaryMessages.length > 0) {
            secondaryContainer.innerHTML = `
                <div class="secondary-messages">
                    <h2>Other Service Messages</h2>
                    ${await renderMessages(secondaryMessages, true)}
                </div>`;
        } else {
            secondaryContainer.innerHTML = '';
        }
    })();
}

async function renderMessages(messages, isSecondary) {
    const messageElements = messages.map(message => {
        console.log('Message object:', message);

        const title = message.title || '';
        const text = message.text || message.description || '';
        const messageContent = title ? `<strong>${title}</strong><br>${text}` : text;

        // Get the lines array
        const lines = message.lines || message.affected_lines || [];
        
        // Render affected lines with proper styling
        const lineElements = lines.map(line => {
            // Check if this message has line_colors data
            if (message.line_colors && message.line_colors[line]) {
                const colors = message.line_colors[line];
                return `
                    <span class="delijn-line-number" style="
                        --text-color: ${colors.text};
                        --bg-color: ${colors.background};
                        --text-border-color: ${colors.text_border};
                        --bg-border-color: ${colors.background_border};
                    ">${line}</span>
                `;
            } else {
                // Default STIB styling
                return `
                    <span class="line-number" style="background-color: ${lineColors[line] || '#666'}">
                        ${line}
                    </span>
                `;
            }
        }).join('');

        // Rest of the message rendering...
        const stops = message.stops ? message.stops.join(', ') : 
                     message.affected_stops ? message.affected_stops.map(stop => stop.name).join(', ') : '';

        return `
            <div class="message ${isSecondary ? 'secondary' : ''}">
                ${messageContent}
                <div class="affected-details">
                    <div class="affected-lines">
                        Lines: ${lineElements}
                    </div>
                    ${stops ? `
                        <div class="affected-stops">
                            Stops: ${stops}
                        </div>
                    ` : ''}
                </div>
            </div>
        `;
    });

    return messageElements.join('');
}

async function updateMapData(data) {
    // Only update vehicles, not routes and stops
    if (data.processed_vehicles) {
        const newVehiclePositions = new Set();
        
        data.processed_vehicles.forEach(vehicle => {
            // Handle both position formats
            const position = vehicle.interpolated_position || 
                           (vehicle.position ? [vehicle.position.lat, vehicle.position.lon] : null);
            
            if (!position) return;
            
            const [lat, lon] = position;
            const routeColor = lineColors[vehicle.line] || '#666';
            
            // Create a key for this vehicle based on line and direction
            const vehicleKey = `${vehicle.line}-${vehicle.direction}`;
            
            // Try to find an existing marker for this vehicle
            let existingMarker = null;
            let minDistance = Infinity;
            
            vehicleMarkers.forEach((marker, key) => {
                // Only consider markers of the same line and direction
                if (!key.startsWith(vehicleKey)) return;
                
                const markerPos = marker.getLatLng();
                const distance = map.distance([lat, lon], [markerPos.lat, markerPos.lng]);
                
                // Consider it the same vehicle if it's within 500 meters
                // (adjust this threshold based on your needs)
                if (distance < 500 && distance < minDistance) {
                    existingMarker = marker;
                    minDistance = distance;
                }
            });
            
            if (existingMarker) {
                // Update existing marker
                existingMarker.setLatLng([lat, lon]);
                
                // Update the icon's bearing
                const isDelijn = delijnConfig?.monitored_lines?.includes(vehicle.line);
                let markerStyle;
                
                if (isDelijn && typeof routeColor === 'object') {
                    markerStyle = `
                        --text-color: ${routeColor.text};
                        --bg-color: ${routeColor.background};
                        --text-border-color: ${routeColor.text_border};
                        --bg-border-color: ${routeColor.background_border};
                    `;
                } else {
                    markerStyle = `--bg-color: ${routeColor}; --text-color: white;`;
                }

                const newIcon = L.divIcon({
                    html: `
                        <div class="vehicle-marker-content" style="
                            --bearing: ${vehicle.bearing}deg;
                            ${markerStyle}
                        ">
                            <div class="${isDelijn ? 'delijn-line-number' : 'line-number'}">
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
                existingMarker.setIcon(newIcon);
                
                // Format direction display
                const directionDisplay = vehicle.headsign || vehicle.direction;
                const segmentInfo = getSegmentInfo(vehicle);
                
                existingMarker.setPopupContent(`
                    <strong>Line ${vehicle.line}</strong><br>
                    To: ${directionDisplay}<br>
                    ${segmentInfo}
                    ${vehicle.delay ? `<br>Delay: ${Math.round(vehicle.delay / 60)} minutes` : ''}
                `);
                
                // Mark this position as seen
                newVehiclePositions.add(`${vehicleKey}-${lat}-${lon}`);
            } else {
                // Create new marker as before
                const marker = createVehicleMarker(vehicle, routeColor, lat, lon);
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
}

// Helper function to create a new vehicle marker
function createVehicleMarker(vehicle, routeColor, lat, lon) {
    const isDelijn = delijnConfig?.monitored_lines?.includes(vehicle.line);
    let markerStyle;
    
    if (isDelijn && typeof routeColor === 'object') {
        markerStyle = `
            --text-color: ${routeColor.text};
            --bg-color: ${routeColor.background};
            --text-border-color: ${routeColor.text_border};
            --bg-border-color: ${routeColor.background_border};
        `;
    } else {
        markerStyle = `--bg-color: ${routeColor}; --text-color: white;`;
    }
    
    const vehicleIcon = L.divIcon({
        html: `
            <div class="vehicle-marker-content" style="
                --bearing: ${vehicle.bearing}deg;
                ${markerStyle}
            ">
                <div class="${isDelijn ? 'delijn-line-number' : 'line-number'}">
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
    
    const marker = L.marker([lat, lon], {
        icon: vehicleIcon,
        pane: 'vehiclesPane',
        zIndexOffset: 1000
    });
    
    // Format direction display
    const directionDisplay = vehicle.headsign || vehicle.direction;
    const segmentInfo = getSegmentInfo(vehicle);
    
    marker.bindPopup(`
        <strong>Line ${vehicle.line}</strong><br>
        To: ${directionDisplay}<br>
        ${segmentInfo}
        ${vehicle.delay ? `<br>Delay: ${Math.round(vehicle.delay / 60)} minutes` : ''}
    `);
    
    marker.addTo(vehiclesLayer);
    return marker;
}

// Add this function to fetch coordinates for a stop
async function fetchStopCoordinates(stopId) {
    try {
        // First try STIB coordinates
        const stibResponse = await fetch(`/api/stop_coordinates/${stopId}`);
        if (stibResponse.ok) {
            const data = await stibResponse.json();
            if (data.coordinates && data.coordinates.lat && data.coordinates.lon) {
                return data.coordinates;
            }
        }

        // If not found in STIB, check if it's a De Lijn stop
        if (delijnConfig && delijnConfig.stops) {
            const delijnStop = delijnConfig.stops.find(stop => stop.id === stopId);
            if (delijnStop && delijnStop.coordinates) {
                return delijnStop.coordinates;
            }
        }

        console.warn(`No coordinates found for stop ${stopId}`);
        return null;
    } catch (error) {
        console.error(`Error fetching coordinates for stop ${stopId}:`, error);
        return null;
    }
}

// Update the updateStopMarkerPopup function to handle De Lijn colors
async function updateStopMarkerPopup(stopId, stopInfo) {
    stopsLayer.eachLayer(async (marker) => {
        if (marker.stopId === stopId) {
            let popupContent = `<strong>${properTitle(stopInfo.name)}</strong><br>`;
            
            if (stopInfo.lines) {
                // Process all lines at once
                const linePromises = Object.entries(stopInfo.lines).map(async ([line, destinations]) => {
                    const isDelijn = delijnConfig?.monitored_lines?.includes(line);
                    let style;
                    
                    if (isDelijn) {
                        const delijnColors = await getDeLijnColors(line);
                        if (delijnColors) {
                            style = `
                                --text-color: ${delijnColors.text};
                                --bg-color: ${delijnColors.background};
                                --text-border-color: ${delijnColors.text_border};
                                --bg-border-color: ${delijnColors.background_border};
                            `;
                        }
                    } else {
                        const lineColor = lineColors[line] || '#666';
                        style = `--bg-color: ${lineColor}; --text-color: white;`;
                    }

                    return `
                        <div class="line-info">
                            <span class="${isDelijn ? 'delijn-line-number' : 'line-number'}" 
                                  style="${style}">
                                ${line}
                            </span>
                            → ${destinations.join(', ')}
                        </div>
                    `;
                });
                
                // Wait for all line styles to be processed
                const lineElements = await Promise.all(linePromises);
                popupContent += lineElements.join('');
            }
            
            marker.setPopupContent(popupContent);
        }
    });
}

// Modify the initializeMapLayers function to store stopId with markers
async function initializeMapLayers(data) {
    console.log("Initializing map layers with data:", data);
    
    // Add route shapes
    if (data.shapes) {
        console.log('Processing shapes data:', data.shapes);
        for (const [line, shapeData] of Object.entries(data.shapes)) {
            console.log(`Processing shape for line ${line}:`, shapeData);
            
            // Add null check here
            if (!shapeData) {
                console.warn(`No shape data available for line ${line}`);
                continue;
            }
            
            // Handle STIB shapes (array format)
            if (Array.isArray(shapeData)) {
                console.log(`Line ${line} has array format with ${shapeData.length} variants`);
                shapeData.forEach((variant, index) => {
                    console.log(`Processing variant ${index} for line ${line}:`, variant);
                    if (variant && variant.shape) {
                        console.log(`Shape coordinates for line ${line} variant ${index}:`, variant.shape.slice(0, 3), '... (first 3 points)');
                        const convertedCoords = variant.shape.map(coord => {
                            return [coord[1], coord[0]];
                        });
                        console.log(`Converted coordinates for line ${line} variant ${index}:`, convertedCoords.slice(0, 3), '... (first 3 points)');
                        L.polyline(convertedCoords, {
                            color: lineColors[line] || '#666',
                            weight: 3,
                            opacity: 0.7,
                            pane: 'routesPane',
                            interactive: false
                        }).addTo(routesLayer);
                    } else {
                        console.warn(`No shape data for line ${line} variant ${index}`);
                    }
                });
            }
            // Handle De Lijn shapes (object format with variants)
            else if (shapeData.variants) {
                console.log(`Line ${line} has object format with variants`);
                shapeData.variants.forEach((variant, index) => {
                    console.log(`Processing De Lijn variant ${index} for line ${line}:`, variant);
                    if (variant && variant.coordinates) {
                        console.log(`Coordinates for line ${line} variant ${index}:`, variant.coordinates.slice(0, 3), '... (first 3 points)');
                        const lineColor = typeof lineColors[line] === 'object' 
                            ? lineColors[line].background 
                            : lineColors[line] || '#666';
                            
                        L.polyline(variant.coordinates, {
                            color: lineColor,
                            weight: 3,
                            opacity: 0.7,
                            pane: 'routesPane',
                            interactive: false
                        }).addTo(routesLayer);
                    } else {
                        console.warn(`No coordinates for line ${line} variant ${index}`);
                    }
                });
            }
            else {
                console.warn(`Unknown shape data format for line ${line}:`, shapeData);
            }
        }
    } else {
        console.warn('No shapes data in response');
    }
    
    // Add stops
    if (data.display_stops) {
        for (const stop of data.display_stops) {
            const coordinates = await fetchStopCoordinates(stop.id);
            if (coordinates && coordinates.lat && coordinates.lon) {
                const marker = L.circleMarker([coordinates.lat, coordinates.lon], {
                    radius: 8,
                    fillColor: '#fff',
                    color: '#000',
                    weight: 2,
                    opacity: 1,
                    fillOpacity: 0.8,
                    pane: 'stopsPane'
                });
                
                // Store the stop ID with the marker
                marker.stopId = stop.id;
                
                // Initial popup content
                let popupContent = `<strong>${properTitle(stop.name)}</strong><br>`;
                if (stop.lines) {
                    popupContent += Object.entries(stop.lines)
                        .map(([line, destinations]) => 
                            `<span class="line-number" style="background-color: ${lineColors[line] || '#666'}">${line}</span> → ${destinations.join(', ')}`
                        ).join('<br>');
                }
                
                marker.bindPopup(popupContent);
                marker.addTo(stopsLayer);
            } else {
                console.warn(`Missing or invalid coordinates for stop ${stop.name} (${stop.id})`);
            }
        }
    }
}

// Add this function to calculate walking time
function calculateWalkingTime(meters) {
    const seconds = meters / WALKING_SPEED;
    const minutes = Math.round(seconds / 60);
    return minutes;
}

// Add this function to format distance
function formatDistance(meters) {
    if (meters < 1000) {
        return `${Math.round(meters)}m`;
    }
    return `${(meters / 1000).toFixed(1)}km`;
}

// Modify the updateDistances function
function updateDistances(position) {
    if (!position || (!position.lat && !position.latitude)) {
        console.log('No valid position available');
        return;
    }
    
    // Normalize position format
    const lat = position.lat || position.latitude;
    const lng = position.lng || position.longitude;
    
    const stopsContainer = document.getElementById('stops-container');
    const stopSections = Array.from(stopsContainer.querySelectorAll('.stop-section'));
    const distanceInfo = document.getElementById('distance-info');
    
    // Create an array to store stop sections with their distances
    const stopsWithDistances = [];
    
    stopSections.forEach(section => {
        const stopId = section.querySelector('.physical-stop')?.dataset.stopId;
        if (!stopId) return;
        
        const h2 = section.querySelector('h2');
        
        // Find or create distance element
        let distanceElement = section.querySelector('.stop-distance');
        if (!distanceElement) {
            distanceElement = document.createElement('div');
            distanceElement.className = 'stop-distance';
            h2.appendChild(distanceElement);
        }
        
        // Find stop marker and calculate distance
        stopsLayer.eachLayer(marker => {
            if (marker.stopId === stopId) {
                const markerPos = marker.getLatLng();
                const distance = map.distance(
                    [lat, lng],
                    [markerPos.lat, markerPos.lng]
                );
                
                const walkingTime = calculateWalkingTime(distance);
                distanceElement.innerHTML = `
                    <span class="walking-time">🚶 ${walkingTime} min</span>
                    <span class="distance">(${formatDistance(distance)})</span>
                `;
                
                stopsWithDistances.push({
                    element: section,
                    distance: distance
                });
            }
        });
    });
    
    // Sort stops by distance
    stopsWithDistances.sort((a, b) => a.distance - b.distance);
    
    // Reorder the DOM elements
    stopsWithDistances.forEach(stop => {
        stopsContainer.appendChild(stop.element);
    });
    
    // Hide the loading popup after calculations are complete
    if (distanceInfo) {
        distanceInfo.classList.add('hidden');
        setTimeout(() => {
            distanceInfo.remove();
        }, 300);
    }
}

// Add error handling function
function updateErrors(errors, shapeErrors) {
    const errorsContainer = document.getElementById('errors-container');
    if (!errorsContainer) {
        console.warn('Errors container not found');
        return;
    }

    let html = '';
    
    if (errors && errors.length > 0) {
        html += '<div class="error-section"><h2>Errors</h2>';
        errors.forEach(error => {
            html += `<div class="error-message">${error}</div>`;
        });
        html += '</div>';
    }
    
    if (shapeErrors && shapeErrors.length > 0) {
        html += '<div class="error-section"><h3>Shape Data Errors</h3>';
        shapeErrors.forEach(error => {
            html += `<div class="error-message secondary">${error}</div>`;
        });
        html += '</div>';
    }
    
    errorsContainer.innerHTML = html;
}

// Add this function to fetch stop names
async function fetchStopNames(stopIds) {
    try {
        const response = await fetch('/api/stop_names', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify(stopIds)
        });
        
        if (!response.ok) {
            throw new Error(`HTTP error! status: ${response.status}`);
        }
        
        const data = await response.json();
        if (data && data.stops) {
            stopNames = {...stopNames, ...data.stops};
        }
    } catch (error) {
        console.error('Error fetching stop names:', error);
    }
}

function getSegmentInfo(vehicle) {
    let segmentInfo = '';
    if (vehicle.current_segment && vehicle.current_segment.length === 2) {
        const [currentStopId, nextStopId] = vehicle.current_segment;
        const currentStop = stopNames[currentStopId]?.name || currentStopId;
        const nextStop = stopNames[nextStopId]?.name || nextStopId;
        segmentInfo = `Between ${properTitle(currentStop)} and ${properTitle(nextStop)}`;
        
        // Fetch missing stop names if needed
        const missingStops = [];
        if (!stopNames[currentStopId]) missingStops.push(currentStopId);
        if (!stopNames[nextStopId]) missingStops.push(nextStopId);
        if (missingStops.length > 0) {
            fetchStopNames(missingStops);
        }
    }
    return segmentInfo;
}

// Add function to fetch De Lijn colors for a line
async function getDeLijnColors(line) {
    const isDelijnLine = delijnConfig?.monitored_lines?.includes(line);
    if (!isDelijnLine) {
        return null;
    }

    try {
        if (lineColors[line] && typeof lineColors[line] === 'object') {
            return lineColors[line];
        }

        const response = await fetch(`/api/delijn/lines/${line}/colors`);
        if (response.ok) {
            const colors = await response.json();
            lineColors[line] = colors;
            return colors;
        }
    } catch (e) {
        console.error(`Error fetching colors for line ${line}:`, e);
    }
    return null;
}

function properTitle(text) {
    // Handle undefined, null, or non-string input
    if (!text) {
        return '';
    }
    
    // Convert to string if it isn't already
    text = String(text);
    
    // List of words that should remain uppercase
    const uppercaseWords = new Set(['uz', 'vub', 'ulb']);
    
    // Split on spaces and hyphens
    const words = text.toLowerCase().replace('-', ' - ').split(' ');
    
    // Process each word
    return words.map(word => {
        // Skip empty words
        if (!word) return '';
        
        // Handle words with periods (abbreviations)
        if (word.includes('.')) {
            const parts = word.split('.');
            return parts.map(p => 
                p && uppercaseWords.has(p.toLowerCase()) ? 
                    p.toUpperCase() : 
                    p ? p.charAt(0).toUpperCase() + p.slice(1).toLowerCase() : ''
            ).join('.');
        } else if (uppercaseWords.has(word)) {
            return word.toUpperCase();
        } else {
            return word.charAt(0).toUpperCase() + word.slice(1);
        }
    }).filter(Boolean).join(' ') || 'Unknown';  // Return 'Unknown' if result is empty
}

// Add this function
function resetMapView() {
    map.setView(
        [map_config.center.lat, map_config.center.lon], 
        map_config.zoom
    );
    if (!userLocation) {
        // If we're using map center for distances, update them
        userLocation = map.getCenter();
        updateDistances(userLocation);
    }
}

// Add this function to handle using map center for distances
function useMapCenter() {
    userLocation = map.getCenter();
    updateDistances(userLocation);
    
    // Update distances when map is moved
    map.on('moveend', () => {
        userLocation = map.getCenter();
        updateDistances(userLocation);
    });
}

// Initialize everything when the DOM is loaded
document.addEventListener('DOMContentLoaded', async () => {
    try {
        console.log("Starting initialization...");
        
        // First fetch De Lijn config
        const delijnConfigResponse = await fetch('/api/delijn/config');
        if (!delijnConfigResponse.ok) {
            throw new Error('Error fetching De Lijn configuration');
        }
        delijnConfig = await delijnConfigResponse.json();
        console.log('De Lijn config:', delijnConfig);

        // Populate DELIJN_STOP_IDS
        if (delijnConfig && delijnConfig.stops) {
            DELIJN_STOP_IDS = new Set(delijnConfig.stops.map(stop => stop.id));
        }

        // Add De Lijn stops to the page
        if (delijnConfig.stops && delijnConfig.stops.length > 0) {
            const stopsContainer = document.getElementById('stops-container');
            
            delijnConfig.stops.forEach(stop => {
                const stopSection = document.createElement('div');
                stopSection.className = 'stop-section';
                stopSection.dataset.stopName = stop.name;
                
                stopSection.innerHTML = `
                    <h2>${properTitle(stop.name)}</h2>
                    <div class="stop-content">
                        <div class="physical-stop" data-stop-id="${stop.id}" data-provider="delijn">
                            <div class="loading">Loading real-time data...</div>
                        </div>
                    </div>
                `;
                
                stopsContainer.appendChild(stopSection);
            });
        }

        // Fetch STIB static data
        const stibStaticResponse = await fetch('/api/static_data');
        if (!stibStaticResponse.ok) {
            throw new Error('Error fetching STIB static data');
        }
        const stibStaticData = await stibStaticResponse.json();
        console.log('STIB static data:', stibStaticData);

        // Update lineColors with STIB colors
        Object.assign(lineColors, stibStaticData.route_colors);

        // Fetch De Lijn routes and colors
        if (delijnConfig && delijnConfig.monitored_lines) {
            console.log("Fetching De Lijn routes and colors...");
            const [routes, colors] = await Promise.all([
                fetchDeLijnRoutes(delijnConfig.monitored_lines),
                Promise.all(delijnConfig.monitored_lines.map(async line => {
                    const response = await fetch(`/api/delijn/lines/${line}/colors`);
                    if (response.ok) {
                        const colorData = await response.json();
                        lineColors[line] = colorData;
                        return { line, colors: colorData };
                    }
                }))
            ]);
            
            console.log("De Lijn routes:", routes);
            console.log("De Lijn colors:", colors);
            
            // Add routes to static data
            stibStaticData.shapes = {
                ...stibStaticData.shapes,
                ...routes
            };
        }

        // Initialize map with combined static data
        const combinedStaticData = {
            ...stibStaticData,
            display_stops: [
                ...stibStaticData.display_stops,
                ...(delijnConfig?.stops || [])
            ]
        };
        
        // Initialize map
        map = L.map('map', {
            center: [
                map_config.center.lat, 
                map_config.center.lon
            ],
            zoom: map_config.zoom,
            zoomControl: true,
            layers: []
        });
        
        // Add the tile layer first
        L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
            maxZoom: 19,
            minZoom: 11,
            attribution: '© OpenStreetMap contributors'
        }).addTo(map);
        
        // Create custom panes BEFORE creating the layers
        map.createPane('routesPane');
        map.createPane('stopsPane');
        map.createPane('vehiclesPane');
        
        // Set z-index for panes
        map.getPane('routesPane').style.zIndex = 400;
        map.getPane('stopsPane').style.zIndex = 450;
        map.getPane('vehiclesPane').style.zIndex = 500;
        
        // Now create the feature groups with their specific panes
        routesLayer = L.featureGroup([], {
            pane: 'routesPane'
        }).addTo(map);
        
        stopsLayer = L.featureGroup([], {
            pane: 'stopsPane'
        }).addTo(map);
        
        vehiclesLayer = L.featureGroup([], {
            pane: 'vehiclesPane'
        }).addTo(map);
        
        // Add layer control
        const overlays = {
            "Routes": routesLayer,
            "Stops": stopsLayer,
            "Vehicles": vehiclesLayer
        };
        L.control.layers(null, overlays).addTo(map);

        console.log("Initializing map with combined data:", combinedStaticData);
        await initializeMapLayers(combinedStaticData);

        // Handle any errors
        if (stibStaticData.errors?.length > 0) {
            updateErrors([], stibStaticData.errors);
        }

        // Initial fetch
        await fetchAndUpdateData();
        
        // Update every 60 seconds
        setInterval(fetchAndUpdateData, REFRESH_INTERVAL);

        // Add geolocation handling
        if ('geolocation' in navigator && isSecure) {
            const distanceInfo = document.getElementById('distance-info');
            distanceInfo.innerHTML = 'Requesting location access...';
            
            // Initial position request
            navigator.geolocation.getCurrentPosition(
                (position) => {
                    userLocation = {
                        lat: position.coords.latitude,
                        lng: position.coords.longitude
                    };
                    lastLocationUpdate = Date.now();
                    updateDistances(userLocation);
                    
                    // Set up periodic location updates
                    locationWatchId = navigator.geolocation.watchPosition(
                        (newPosition) => {
                            // Only update if enough time has passed
                            if (Date.now() - lastLocationUpdate >= LOCATION_UPDATE_INTERVAL) {
                                userLocation = {
                                    lat: newPosition.coords.latitude,
                                    lng: newPosition.coords.longitude
                                };
                                lastLocationUpdate = Date.now();
                                updateDistances(userLocation);
                            }
                        },
                        null,
                        { 
                            enableHighAccuracy: true,
                            maximumAge: LOCATION_UPDATE_INTERVAL,
                            timeout: 10000
                        }
                    );
                },
                (error) => {
                    console.log('Geolocation error:', error);
                    useMapCenter();
                }
            );
        } else {
            console.log('Geolocation not available or not in secure context');
            useMapCenter();
        }

        // Clean up location watch when page is hidden/closed
        document.addEventListener('visibilitychange', () => {
            if (document.hidden && locationWatchId !== null) {
                navigator.geolocation.clearWatch(locationWatchId);
                locationWatchId = null;
            } else if (!document.hidden && !locationWatchId && 'geolocation' in navigator) {
                // Restart watching when page becomes visible again
                navigator.geolocation.getCurrentPosition(position => {
                    userLocation = {
                        lat: position.coords.latitude,
                        lng: position.coords.longitude
                    };
                    lastLocationUpdate = Date.now();
                    updateDistances(userLocation);
                    
                    locationWatchId = navigator.geolocation.watchPosition(
                        // ... same watch options as above ...
                    );
                });
            }
        });

    } catch (error) {
        console.error('Error during initialization:', error);
        const errorsContainer = document.getElementById('errors-container');
        if (errorsContainer) {
            errorsContainer.innerHTML = `
                <div class="error-section">
                    <div class="error-message">
                        Error during initialization: ${error.message}
                    </div>
                </div>
            `;
        }
    }
});

async function getSettingsToken() {
    try {
        const response = await fetch('/api/auth/token');
        if (!response.ok) throw new Error('Failed to get token');
        const data = await response.json();
        return data.token;
    } catch (error) {
        console.error('Error getting settings token:', error);
        return null;
    }
}

// Use the token when fetching settings
async function getSettings() {
    try {
        const token = await getSettingsToken();
        if (!token) throw new Error('No token available');

        const response = await fetch('/api/settings', {
            headers: {
                'X-Settings-Token': token
            }
        });
        if (!response.ok) throw new Error('Failed to get settings');
        return await response.json();
    } catch (error) {
        console.error('Error fetching settings:', error);
        return null;
    }
} 

