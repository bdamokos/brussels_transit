// Global variables
let map;
let stopsLayer;
let routesLayer;
let vehiclesLayer;
let vehicleMarkers = new Map();  // Store markers by their unique position key
let stopNames = {};
let DELIJN_STOP_IDS = new Set();  // Will be populated when we get delijnConfig
let userLocation = null;
let locationWatchId = null;
let lastLocationUpdate = 0;
const isSecure = window.isSecureContext || location.protocol === 'https:' || location.hostname === 'localhost';

// Utility functions
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

// Data fetching and update functions
async function fetchAndUpdateData() {
    try {
        console.log("Starting data fetch...");
        
        // Fetch STIB data
        const stibResponse = await fetch('/api/data');
        console.log("STIB response status:", stibResponse.status);
        const stibData = await stibResponse.json();
        
        // Fetch STIB colors for monitored lines
        if (stibData.stops_data) {
            const monitoredLines = new Set();
            Object.values(stibData.stops_data).forEach(stop => {
                if (stop.lines) {
                    Object.keys(stop.lines).forEach(line => monitoredLines.add(line));
                }
            });

            for (const line of monitoredLines) {
                try {
                    const colorResponse = await fetch(`/api/stib/colors/${line}`);
                    if (colorResponse.ok) {
                        const color = await colorResponse.json();
                        transitApp.lineColors[line] = color;
                    }
                } catch (error) {
                    console.warn(`Error fetching color for STIB line ${line}:`, error);
                }
            }
        }
        
        // Initialize De Lijn data with empty defaults
        let delijnData = { stops_data: {}, messages: [], processed_vehicles: [] };
        let delijnMessages = [];
        let delijnVehiclesData = [];
        
        // Fetch De Lijn data if enabled
        if (transitApp.config.delijn) {
            // Fetch global De Lijn waiting times
            const delijnWaitingTimesResponse = await fetch('/api/delijn/waiting_times');
            if (delijnWaitingTimesResponse.ok) {
                const waitingTimesData = await delijnWaitingTimesResponse.json();
                console.log("De Lijn waiting times raw data:", waitingTimesData);
                
                // Store colors for later use
                if (waitingTimesData.colors) {
                    Object.entries(waitingTimesData.colors).forEach(([line, colors]) => {
                        transitApp.lineColors[line] = colors;
                    });
                }
                
                // Transform waiting times data into the expected format
                if (waitingTimesData.stops) {
                    Object.entries(waitingTimesData.stops).forEach(([stopId, stopInfo]) => {
                        if (stopInfo.lines) {
                            delijnData.stops_data[stopId] = {
                                name: stopInfo.name,
                                coordinates: stopInfo.coordinates,
                                lines: stopInfo.lines
                            };
                        }
                    });
                }
            }
            
            // Fetch De Lijn messages
            const delijnMessagesResponse = await fetch('/api/delijn/messages');
            if (delijnMessagesResponse.ok) {
                delijnMessages = await delijnMessagesResponse.json();
            }
            
            // Fetch De Lijn vehicles
            if (transitApp.config.delijn.monitored_lines) {
                const delijnVehiclesPromises = transitApp.config.delijn.monitored_lines.map(async line => {
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

        // Initialize BKK data with empty defaults
        let bkkData = { stops_data: {}, messages: [], processed_vehicles: [] };
        let bkkMessages = [];
        let bkkVehiclesData = [];
        
        // Fetch BKK data if enabled
        if (transitApp.config.bkk) {
            try {
                // Fetch BKK waiting times
                const bkkWaitingTimes = await transitApp.bkkModule.fetchBkkWaitingTimes();
                console.log("BKK waiting times:", bkkWaitingTimes);
                
                // Store colors for later use
                if (bkkWaitingTimes.colors) {
                    Object.entries(bkkWaitingTimes.colors).forEach(([line, colors]) => {
                        transitApp.lineColors[line] = colors;
                    });
                }
                
                // Transform waiting times data into the expected format
                if (bkkWaitingTimes.stops_data) {
                    Object.entries(bkkWaitingTimes.stops_data).forEach(([stopId, stopInfo]) => {
                        if (stopInfo.lines) {
                            bkkData.stops_data[stopId] = {
                                name: stopInfo.name,
                                coordinates: stopInfo.coordinates,
                                lines: Object.entries(stopInfo.lines).reduce((acc, [lineId, lineData]) => {
                                    // Get line info for display name
                                    const info = transitApp.bkkModule.getLineInfo(lineId);
                                    const metadata = {
                                        route_short_name: info?.displayName || lineData._metadata?.route_short_name || lineId
                                    };
                                    
                                    // Remove metadata from line data and add it separately
                                    const { _metadata, ...destinations } = lineData;
                                    acc[lineId] = {
                                        _metadata: metadata,
                                        ...destinations
                                    };
                                    return acc;
                                }, {})
                            };
                        }
                    });
                }
                
                // Fetch BKK messages
                bkkMessages = await transitApp.bkkModule.fetchBkkMessages();
                
                // Fetch BKK vehicles
                if (transitApp.config.bkk.monitored_lines) {
                    const bkkVehiclesPromises = transitApp.config.bkk.monitored_lines.map(async line => {
                        try {
                            const response = await fetch(`/api/bkk/vehicles/${line}`);
                            if (response.ok) {
                                const data = await response.json();
                                return Array.isArray(data) ? data : data.vehicles || [];
                            }
                        } catch (error) {
                            console.warn(`Error fetching vehicles for line ${line}:`, error);
                        }
                        return [];
                    });
                    bkkVehiclesData = await Promise.all(bkkVehiclesPromises);
                }
            } catch (error) {
                console.error('Error fetching BKK data:', error);
            }
        }

        // Combine the data from all providers
        const combinedData = {
            stops_data: {
                ...stibData.stops_data,
                ...delijnData.stops_data,
                ...bkkData.stops_data
            },
            messages: {
                messages: [
                    ...(stibData.messages?.messages || []),
                    ...delijnMessages,
                    ...bkkMessages
                ]
            },
            processed_vehicles: [
                ...(stibData.processed_vehicles || []),
                ...delijnVehiclesData.flat(),
                ...bkkVehiclesData.flat()
            ],
            errors: [
                ...(stibData.errors || []),
                ...(delijnData.errors || []),
                ...(bkkData.errors || [])
            ]
        };

        console.log("Combined data:", combinedData);

        // Update the UI with combined data
        console.log("Updating stops data...");
        updateStopsData(combinedData.stops_data);
        
        console.log("Updating service messages...");
        await updateServiceMessages(combinedData.messages);
        
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

// UI update functions
function updateStopsData(stopsData) {
    console.log("Updating stops data with:", stopsData);
    const sections = document.querySelectorAll('.stop-section');
    
    sections.forEach(section => {
        const stopName = section.dataset.stopName;
        const content = section.querySelector('.stop-content');
        const physicalStops = content.querySelectorAll('.physical-stop');
        
        physicalStops.forEach(stopContainer => {
            const stopId = stopContainer.dataset.stopId;
            const provider = stopContainer.dataset.provider;
            const stopInfo = stopsData[stopId];
            
            // Clear existing content but keep divider if it exists
            const divider = stopContainer.querySelector('.stop-divider');
            stopContainer.innerHTML = '';
            if (divider) {
                stopContainer.appendChild(divider);
            }
            
            if (stopInfo && stopInfo.lines) {
                for (const [line, lineData] of Object.entries(stopInfo.lines)) {
                    const lineContainer = document.createElement('div');
                    lineContainer.className = 'line-container';
                    
                    const lineColor = transitApp.lineColors[line];
                    const style = (provider === 'delijn' || provider === 'bkk') && typeof lineColor === 'object'
                        ? `
                            --text-color: ${lineColor.text};
                            --bg-color: ${lineColor.background};
                            --text-border-color: ${lineColor.text_border};
                            --bg-border-color: ${lineColor.background_border};
                        `
                        : `background-color: ${lineColor || '#666'}`;
                    
                    const metadata = lineData._metadata || {};
                    delete lineData._metadata;
                    
                    for (const [destination, times] of Object.entries(lineData)) {
                        if (!times || times.length === 0) continue;
                        
                        lineContainer.innerHTML = `
                            <div class="line-info">
                                <span class="${(provider === 'delijn' || provider === 'bkk') ? 'delijn-line-number' : 'line-number'}" 
                                      style="${style}">
                                    ${metadata.route_short_name || line}
                                </span>
                                <span class="direction">→ ${destination}</span>
                            </div>
                            <div class="times-container">
                                ${times.map(time => {
                                    if (time.message) {
                                        // Handle translated messages
                                        const message = typeof time.message === 'object' ?
                                            (time.message.en || time.message.hu || Object.values(time.message)[0]) :
                                            time.message;
                                        return `<span class="service-message end-service">${message}</span>`;
                                    } else if (provider === 'delijn' || provider === 'bkk') {
                                        if (time.is_realtime) {
                                            const delay = time.delay || 0;
                                            const delayClass = delay < 0 ? 'early' : delay > 0 ? 'late' : 'on-time';
                                            
                                            const sameTime = time.realtime_time === time.scheduled_time;
                                            
                                            return `
                                                <span class="time-display ${provider}">
                                                    <span class="minutes ${delayClass}">${time.realtime_minutes}</span>
                                                    <span class="actual-time">
                                                        ${sameTime ? 
                                                            `(⚡/ ${time.realtime_time})` : 
                                                            `(⚡${time.realtime_time} - 🕒${time.scheduled_time})`}
                                                    </span>
                                                </span>
                                            `;
                                        } else {
                                            return `
                                                <span class="time-display ${provider}">
                                                    <span class="minutes">${time.scheduled_minutes}</span>
                                                    <span class="actual-time">(🕒 ${time.scheduled_time})</span>
                                                </span>
                                            `;
                                        }
                                    } else {
                                        const minutes = time.minutes;
                                        const displayTime = time.formatted_time;
                                        
                                        if (minutes === undefined || !displayTime) {
                                            console.debug('Missing time data:', time);
                                            return '';
                                        }

                                        return `
                                            <span class="time-display">
                                                <span class="minutes ${parseInt(minutes) < 0 ? 'late' : ''}">${minutes}'</span>
                                                <span class="actual-time"> (${displayTime})</span>
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
        const isDelijn = DELIJN_STOP_IDS.has(stopId);
        const isBkk = transitApp.bkkModule.BKK_STOP_IDS.has(stopId);
        
        if (stopInfo && stopInfo.lines) {
            let popupContent = `<strong>${properTitle(stopInfo.name)}</strong><br>`;
            
            for (const [line, lineData] of Object.entries(stopInfo.lines)) {
                const metadata = lineData._metadata || {};
                delete lineData._metadata;
                
                for (const [destination, times] of Object.entries(lineData)) {
                    if (!times || times.length === 0) continue;
                    
                    const lineColor = transitApp.lineColors[line];
                    const style = (isDelijn || isBkk) && typeof lineColor === 'object'
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
                            <span class="${(isDelijn || isBkk) ? 'delijn-line-number' : 'line-number'}" 
                                  style="${style}">
                                ${metadata.route_short_name || line}
                            </span>
                            → ${destination}
                        </div>
                    `;
                    
                    // Add next arrival times (limit to 2 for popup)
                    const nextArrivals = times.slice(0, 2).map(time => {
                        if ((isDelijn || isBkk) && time.is_realtime) {
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

async function updateServiceMessages(messages) {
    const primaryContainer = document.getElementById('primary-messages-container');
    const secondaryContainer = document.getElementById('secondary-messages-container');
    
    if (!messages || !messages.messages) {
        primaryContainer.innerHTML = '';
        secondaryContainer.innerHTML = '';
        return;
    }

    // Collect all STIB lines from messages and fetch their colors if not already in transitApp.lineColors
    const stibLines = new Set();
    messages.messages.forEach(message => {
        const lines = message.lines || message.affected_lines || [];
        // Only collect lines that don't have colors yet and don't have line_info or line_colors (which would indicate BKK or De Lijn)
        lines.forEach(line => {
            if (!transitApp.lineColors[line] && !message.line_info && !message.line_colors) {
                stibLines.add(line);
            }
        });
    });

    // Fetch colors for STIB lines
    for (const line of stibLines) {
        try {
            const colorResponse = await fetch(`/api/stib/colors/${line}`);
            if (colorResponse.ok) {
                const color = await colorResponse.json();
                transitApp.lineColors[line] = color;
            }
        } catch (error) {
            console.warn(`Error fetching color for STIB line ${line}:`, error);
        }
    }
    
    const primaryMessages = messages.messages.filter(m => m.is_monitored);
    const secondaryMessages = messages.messages.filter(m => !m.is_monitored);
    
    // Update primary messages
    if (primaryMessages.length > 0) {
        primaryContainer.innerHTML = `
            <div class="primary-messages">
                <h2>Important Service Messages</h2>
                ${renderMessages(primaryMessages, false)}
            </div>`;
    } else {
        primaryContainer.innerHTML = '';
    }
    
    // Update secondary messages
    if (secondaryMessages.length > 0) {
        secondaryContainer.innerHTML = `
            <div class="secondary-messages">
                <h2>Other Service Messages</h2>
                ${renderMessages(secondaryMessages, true)}
            </div>`;
    } else {
        secondaryContainer.innerHTML = '';
    }
}

function renderMessages(messages, isSecondary) {
    return messages.map(message => {
        // Get title and description, handling translations
        const title = typeof message.title === 'object' ? 
            (message.title.en || message.title.hu || Object.values(message.title)[0]) : 
            message.title || '';
            
        const description = typeof message.description === 'object' ? 
            (message.description.en || message.description.hu || Object.values(message.description)[0]) : 
            message.description || message.text || '';
            
        const messageContent = title ? `<strong>${title}</strong><br>${description}` : description;

        // Get the lines array
        const lines = message.lines || message.affected_lines || [];
        
        // Render affected lines with proper styling
        const lineElements = lines.map(line => {
            // Check if this is a BKK message with line_info
            if (message.line_info) {
                const lineInfo = message.line_info.find(info => info.id === line);
                if (lineInfo) {
                    return `
                        <span class="delijn-line-number" style="
                            --text-color: ${lineInfo.colors.text};
                            --bg-color: ${lineInfo.colors.background};
                            --text-border-color: ${lineInfo.colors.text_border};
                            --bg-border-color: ${lineInfo.colors.background_border};
                        ">${lineInfo.display_name}</span>
                    `;
                }
            }
            // Check if this message has line_colors data (De Lijn)
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
                const lineColor = transitApp.lineColors[line];
                let style;
                
                // Check if the color is an object with the specific keys for De Lijn/BKK format
                if (lineColor && typeof lineColor === 'object' && 
                    'background' in lineColor && 'text' in lineColor) {
                    style = `
                        --text-color: ${lineColor.text};
                        --bg-color: ${lineColor.background};
                        --text-border-color: ${lineColor.text_border};
                        --bg-border-color: ${lineColor.background_border};
                    `;
                } else {
                    // For STIB, the color is an object with line numbers as keys
                    const stibColor = lineColor && lineColor[line];
                    style = `background-color: ${stibColor || '#666'}`;
                }

                return `
                    <span class="${lineColor && typeof lineColor === 'object' && 'background' in lineColor ? 'delijn-line-number' : 'line-number'}" 
                          style="${style}">
                        ${line}
                    </span>
                `;
            }
        }).join('');

        const stops = message.stops ? message.stops.join(', ') : 
                     message.affected_stops ? message.affected_stops.map(stop => stop.name).join(', ') : '';

        // Add BKK-specific fields if available
        let bkkInfo = '';
        if (message._metadata) {
            const startText = message._metadata.start_text?.en || message._metadata.start_text?.hu;
            const endText = message._metadata.end_text?.en || message._metadata.end_text?.hu;
            
            if (startText || endText) {
                bkkInfo = `
                    <div class="message-timing">
                        ${startText ? `<div>From: ${startText}</div>` : ''}
                        ${endText ? `<div>Until: ${endText}</div>` : ''}
                    </div>
                `;
            }
        }

        // Add URL if available
        const urlInfo = message.url ? `
            <div class="message-url">
                <a href="${message.url}" target="_blank" rel="noopener noreferrer">More information</a>
            </div>
        ` : '';

        return `
            <div class="message ${isSecondary ? 'secondary' : ''}">
                ${messageContent}
                ${bkkInfo}
                ${urlInfo}
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
    }).join('');
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
            const routeColor = transitApp.lineColors[vehicle.line] || '#666';
            
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
                if (distance < 500 && distance < minDistance) {
                    existingMarker = marker;
                    minDistance = distance;
                }
            });
            
            if (existingMarker) {
                // Update existing marker
                existingMarker.setLatLng([lat, lon]);
                
                // Update the icon's bearing
                const isDelijn = transitApp.config.delijn?.monitored_lines?.includes(vehicle.line);
                const isBkk = transitApp.config.bkk?.monitored_lines?.includes(vehicle.line);
                let markerStyle;
                
                if ((isDelijn || isBkk) && typeof routeColor === 'object') {
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
                            <div class="${(isDelijn || isBkk) ? 'delijn-line-number' : 'line-number'}">
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
                // Create new marker
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

// Helper function to create a new vehicle marker
function createVehicleMarker(vehicle, routeColor, lat, lon) {
    const isDelijn = transitApp.config.delijn?.monitored_lines?.includes(vehicle.line);
    const isBkk = transitApp.config.bkk?.monitored_lines?.includes(vehicle.line);
    let markerStyle;
    
    if ((isDelijn || isBkk) && typeof routeColor === 'object') {
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
                <div class="${(isDelijn || isBkk) ? 'delijn-line-number' : 'line-number'}">
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

// Helper functions
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

function resetMapView() {
    map.setView(
        [transitApp.map_config.center.lat, transitApp.map_config.center.lon], 
        transitApp.map_config.zoom
    );
    if (!userLocation) {
        // If we're using map center for distances, update them
        userLocation = map.getCenter();
        updateDistances(userLocation);
    }
}

function useMapCenter() {
    userLocation = map.getCenter();
    updateDistances(userLocation);
    
    // Update distances when map is moved
    map.on('moveend', () => {
        userLocation = map.getCenter();
        updateDistances(userLocation);
    });
}

// Add this function to calculate walking time
function calculateWalkingTime(meters) {
    const seconds = meters / transitApp.WALKING_SPEED;
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

// Initialize everything when the DOM is loaded
document.addEventListener('DOMContentLoaded', async () => {
    try {
        console.log("Starting initialization...");
        
        // First fetch De Lijn config
        const delijnConfigResponse = await fetch('/api/delijn/config');
        if (!delijnConfigResponse.ok) {
            throw new Error('Error fetching De Lijn configuration');
        }
        transitApp.config.delijn = await delijnConfigResponse.json();
        console.log('De Lijn config:', transitApp.config.delijn);

        // Populate DELIJN_STOP_IDS
        if (transitApp.config.delijn && transitApp.config.delijn.stops) {
            DELIJN_STOP_IDS = new Set(transitApp.config.delijn.stops.map(stop => stop.id));
        }

        // Fetch BKK config if enabled
        const bkkEnabled = await transitApp.bkkModule.isBkkEnabled();
        if (bkkEnabled) {
            transitApp.config.bkk = await transitApp.bkkModule.fetchBkkConfig();
            console.log('BKK config:', transitApp.config.bkk);
            
            // BKK_STOP_IDS is handled by the bkkModule

            // Add BKK stops to the page
            if (transitApp.config.bkk.stops && transitApp.config.bkk.stops.length > 0) {
                const stopsContainer = document.getElementById('stops-container');
                
                transitApp.config.bkk.stops.forEach(stop => {
                    const stopSection = document.createElement('div');
                    stopSection.className = 'stop-section';
                    stopSection.dataset.stopName = stop.name;
                    
                    stopSection.innerHTML = `
                        <h2>${properTitle(stop.name)}</h2>
                        <div class="stop-content">
                            <div class="physical-stop" data-stop-id="${stop.id}" data-provider="bkk">
                                <div class="loading">Loading real-time data...</div>
                            </div>
                        </div>
                    `;
                    
                    stopsContainer.appendChild(stopSection);
                });
            }
        }

        // Add De Lijn stops to the page
        if (transitApp.config.delijn?.stops && transitApp.config.delijn.stops.length > 0) {
            const stopsContainer = document.getElementById('stops-container');
            
            transitApp.config.delijn.stops.forEach(stop => {
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

        // Initialize map
        map = L.map('map', {
            center: [
                transitApp.map_config.center.lat, 
                transitApp.map_config.center.lon
            ],
            zoom: transitApp.map_config.zoom,
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

        // Initial fetch
        await fetchAndUpdateData();
        
        // Update every 60 seconds
        setInterval(fetchAndUpdateData, transitApp.REFRESH_INTERVAL);

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
                            if (Date.now() - lastLocationUpdate >= transitApp.LOCATION_UPDATE_INTERVAL) {
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
                            maximumAge: transitApp.LOCATION_UPDATE_INTERVAL,
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

