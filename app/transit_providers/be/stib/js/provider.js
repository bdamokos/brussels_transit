import { TransitProvider } from '/js/core/provider.js';
import { getLineColor, getSettingsToken } from '/js/core/utils.js';

/**
 * STIB Transit Provider
 * Interfaces with our backend API endpoints to provide STIB transit data
 */
export class StibProvider extends TransitProvider {
    constructor(providerInfo) {
        super('stib');  // Call parent constructor with provider name
        this.id = 'stib';  // Explicitly set ID
        this.displayName = 'STIB-MIVB';
        this.region = 'be';
        this.settings = null;
        this.config = null;
        this.monitoredLines = new Set();
        this.stopIds = new Set();
        this.lineColors = {};
        
        // Bind methods to instance
        this.formatStopPopup = this.formatStopPopup.bind(this);
        this.getLineColor = this.getLineColor.bind(this);
    }

    /**
     * Initialize the provider
     */
    async initialize() {
        try {
            console.log('Initializing STIB provider...');
            
            // Check if provider is enabled
            if (!await this.isEnabled()) {
                throw new Error('STIB provider is not enabled');
            }

            // Get config first
            this.config = await this.getConfig();
            
            // Extract monitored lines and stop IDs from config
            if (this.config.monitored_lines) {
                this.monitoredLines = new Set(this.config.monitored_lines.map(l => l.toString()));
            }
            
            if (this.config.stops) {
                this.stopIds = new Set(this.config.stops.map(stop => stop.id.toString()));
            }
            
            // Get line colors for each monitored line
            this.lineColors = {};
            if (this.monitoredLines.size > 0) {
                for (const line of this.monitoredLines) {
                    try {
                        const colorResponse = await fetch(`/api/stib/colors/${line}`);
                        if (colorResponse.ok) {
                            const colors = await colorResponse.json();
                            Object.assign(this.lineColors, colors);
                        }
                    } catch (error) {
                        console.warn(`Failed to fetch colors for line ${line}:`, error);
                    }
                }
            }
            
            console.log('STIB Provider initialized with:', {
                monitoredLines: Array.from(this.monitoredLines),
                stopIds: Array.from(this.stopIds),
                config: this.config,
                lineColors: this.lineColors
            });
        } catch (error) {
            console.error('Failed to initialize STIB provider:', error);
            throw error;
        }
    }

    async isEnabled() {
        return true;  // For initial testing
    }

    async getConfig() {
        const response = await fetch('/api/stib/config');
        if (!response.ok) throw new Error('Failed to get STIB config');
        const config = await response.json();
        return config;
    }

    async getWaitingTimes(stopId) {
        try {
            const response = await fetch(`/api/stib/stop/${stopId}/waiting_times`);
            if (!response.ok) {
                console.error(`Failed to get waiting times for stop ${stopId}, status: ${response.status}`);
                return null;
            }
            const data = await response.json();
            
            console.log(`Raw waiting times for stop ${stopId}:`, data);
            
            // Check if we got waiting times array or stop metadata
            if (data._metadata) {
                // We got stop metadata instead of waiting times
                console.warn(`Received metadata instead of waiting times for stop ${stopId}`);
                return null;
            }
            
            // Process waiting times into the expected format
            const lines = {};
            if (Array.isArray(data?.waiting_times)) {
                data.waiting_times.forEach(time => {
                    if (!time.line || !time.destination) {
                        console.warn('Invalid waiting time entry:', time);
                        return;
                    }
                    
                    if (!lines[time.line]) {
                        lines[time.line] = {};
                    }
                    
                    if (!lines[time.line][time.destination]) {
                        lines[time.line][time.destination] = [];
                    }
                    
                    // Add the waiting time entry
                    if (time.message) {
                        lines[time.line][time.destination].push({
                            message: time.message
                        });
                    } else {
                        lines[time.line][time.destination].push({
                            minutes: time.minutes,
                            formatted_time: time.time,
                            is_realtime: time.is_realtime
                        });
                    }
                });
            }
            
            console.log(`Processed waiting times for stop ${stopId}:`, lines);
            return lines;
        } catch (error) {
            console.error(`Error getting waiting times for stop ${stopId}:`, error);
            return null;
        }
    }

    async getStops() {
        try {
            const response = await fetch('/api/stib/stops');
            if (!response.ok) throw new Error('Failed to get stops');
            const data = await response.json();
            
            const stops = {};
            
            // Only process monitored stops
            for (const stopConfig of this.config.stops) {
                const stopId = stopConfig.id.toString();
                
                // Get stop data from API
                const stopResponse = await fetch(`/api/stib/stop/${stopId}`);
                if (!stopResponse.ok) continue;
                
                const stopData = await stopResponse.json();
                if (!stopData?.coordinates) continue;
                
                stops[stopId] = {
                    id: stopId,
                    name: stopConfig.name,
                    coordinates: {
                        lat: stopData.coordinates.lat,
                        lon: stopData.coordinates.lon
                    },
                    provider: this.id
                };
                
                // Get waiting times
                try {
                    const waitingTimes = await this.getWaitingTimes(stopId);
                    if (waitingTimes) {
                        stops[stopId].lines = waitingTimes;
                    }
                } catch (error) {
                    console.warn(`Failed to get data for stop ${stopId}:`, error);
                }
            }
            
            console.log('Processed stops:', stops);
            return stops;
        } catch (error) {
            console.error('Error getting stops:', error);
            return {};
        }
    }

    /**
     * Get vehicle positions
     * @returns {Promise<Array>} Array of vehicle positions
     */
    async getVehicles() {
        try {
            const response = await fetch('/api/stib/vehicles');
            if (!response.ok) throw new Error('Failed to fetch vehicle data');
            const data = await response.json();
            
            // Fetch stop names for all segments
            const stopIds = new Set();
            data.vehicles.forEach(vehicle => {
                if (vehicle.current_segment) {
                    stopIds.add(vehicle.current_segment[0]);
                    stopIds.add(vehicle.current_segment[1]);
                }
            });
            
            // Build stops data structure
            const stops = {};
            for (const stopId of stopIds) {
                try {
                    const nameResponse = await fetch(`/api/stib/stop/${stopId}/name`);
                    if (nameResponse.ok) {
                        const nameData = await nameResponse.json();
                        stops[stopId] = {
                            id: stopId,
                            name: nameData.name
                        };
                    }
                } catch (error) {
                    console.warn(`Failed to get name for stop ${stopId}:`, error);
                }
            }
            
            // Update stops in StopManager
            if (this.stopManager) {
                this.stopManager.updateStops(stops, this);
            }
            
            const vehicles = data.vehicles
                .filter(vehicle => this.monitoredLines.has(vehicle.line?.toString()))
                .map(vehicle => {
                    // Create a unique ID
                    const vehicleId = `${vehicle.line}-${vehicle.current_segment?.[0] || 'unknown'}-${vehicle.current_segment?.[1] || Date.now()}`;
                    
                    const processedVehicle = {
                        id: vehicleId,
                        line: vehicle.line,
                        direction: vehicle.direction,
                        coordinates: {
                            lat: vehicle.interpolated_position[0],
                            lon: vehicle.interpolated_position[1]
                        },
                        bearing: vehicle.bearing,
                        is_realtime: vehicle.is_valid,
                        delay: vehicle.raw_data?.delay || 0,
                        current_segment: vehicle.current_segment || [vehicle.pointId, vehicle.nextPointId],
                        provider: 'stib'
                    };
                    
                    return processedVehicle;
                });

            return vehicles;
        } catch (error) {
            console.error('Error fetching STIB vehicles:', error);
            return [];
        }
    }

    /**
     * Get route data for monitored lines
     * @returns {Promise<Object>} Route data by line
     */
    async getRoutes() {
        const routes = {};
        
        console.log('Fetching routes for lines:', Array.from(this.monitoredLines));
        
        for (const line of this.monitoredLines) {
            try {
                console.log(`Fetching route for line ${line}...`);
                const response = await fetch(`/api/stib/route/${line}`);
                if (!response.ok) {
                    console.warn(`Failed to fetch route data for line ${line}`);
                    continue;
                }
                
                const data = await response.json();
                console.log(`Raw route data for line ${line}:`, data);
                
                if (data[line] && Array.isArray(data[line])) {
                    routes[line] = {
                        provider: this.id,  // Add provider ID
                        variants: data[line].map(variant => ({
                            coordinates: variant.shape.map(coord => ({
                                lat: coord[1],
                                lon: coord[0]
                            })),
                            direction: variant.direction,
                            destination: variant.destination?.fr || variant.destination?.nl
                        }))
                    };
                    console.log(`Processed route for line ${line}:`, routes[line]);
                }
            } catch (error) {
                console.error(`Error fetching route for line ${line}:`, error);
            }
        }
        
        console.log('All processed routes:', routes);
        return routes;
    }

    async getMessages() {
        try {
            const response = await fetch('/api/stib/messages');
            if (!response.ok) {
                console.warn('Failed to fetch STIB messages');
                return [];
            }
            
            const data = await response.json();
            console.log('Raw STIB messages:', data);
            
            // Process and return messages
            return (data.messages || [])
                .map(msg => ({
                    id: msg.id,
                    title: {
                        fr: msg.text,  // STIB messages are already in French
                        nl: msg.text   // Use same text for Dutch for now
                    },
                    content: {
                        fr: msg.text,
                        nl: msg.text
                    },
                    severity: msg.priority || 'info',
                    lines: msg.lines || [],
                    points: msg.points || [],
                    is_monitored: msg.lines?.some(line => this.monitoredLines.has(line)) || false
                }))
                .filter(msg => msg.lines?.length > 0);  // Only show messages with affected lines
        } catch (error) {
            console.error('Error fetching STIB messages:', error);
            return [];
        }
    }

    getLineColor(line) {
        return this.lineColors?.[line] || '#007bff';  // Default to blue if no color defined
    }

    getVehicleStyle(vehicle) {
        const color = this.getLineColor(vehicle.line);
        return `background-color: ${color}; color: white;`;
    }

    getVehicleClass(vehicle) {
        return 'vehicle-number';
    }

    formatStopPopup(stop) {
        if (!stop) return '';
        
        const lines = Object.keys(stop.lines || {}).sort((a, b) => Number(a) - Number(b));
        if (lines.length === 0) return '';

        const content = [`<strong>${stop.name}</strong>`];
        
        lines.forEach(line => {
            Object.entries(stop.lines[line]).forEach(([destination, times]) => {
                if (!times || times.length === 0) return;
                
                const style = `background-color: ${this.getLineColor(line)}; color: white; padding: 2px 6px; border-radius: 3px; margin: 2px; display: inline-block;`;
                content.push(`<div class="line-info">`);
                content.push(`<span style="${style}">${line}</span>`);
                content.push(`<span class="direction">→ ${destination}</span>`);
                
                // Add waiting times
                const timeContent = times.map(time => {
                    if (time.message) {
                        return `<span class="service-message">${time.message}</span>`;
                    } else {
                        return `<span class="time">${time.minutes}' (${time.formatted_time})</span>`;
                    }
                }).join(', ');
                
                content.push(`<div class="times">${timeContent}</div>`);
                content.push('</div>');
            });
        });
        
        return content.join('\n');
    }

    customizeStopDisplay(stop, element) {
        // Add STIB-specific styling to stop markers
        element.classList.add('stib-stop-marker');
        
        // Format the stop name
        const nameElement = element.querySelector('.stop-name');
        if (nameElement) {
            const text = nameElement.textContent || '';
            nameElement.textContent = text
                .toLowerCase()
                .split(' ')
                .map(word => word.charAt(0).toUpperCase() + word.slice(1))
                .join(' ');
        }

        // Format waiting times
        const timeElements = element.querySelectorAll('.waiting-time');
        timeElements.forEach(el => {
            const minutes = parseInt(el.dataset.minutes);
            el.textContent = minutes === 0 ? 'Now' : 
                           minutes === 1 ? '1 min' : 
                           `${minutes} mins`;
            el.classList.add('stib-waiting-time');
        });

        // Add line badges
        const lineElements = element.querySelectorAll('.line-number');
        lineElements.forEach(el => {
            const lineId = el.textContent.trim();
            el.textContent = lineId.replace(/^0+/, '');  // Remove leading zeros
            el.classList.add('stib-line-badge');
            el.style.cssText = getLineColor(lineId);
        });
    }

    customizeMessageDisplay(message, element) {
        // Add STIB-specific styling to messages
        if (message.priority > 0) {
            element.classList.add('stib-high-priority');
        }

        // Format the message text
        element.textContent = message.text;
    }

    formatLineContainer(line, destination, times, provider) {
        const color = this.getLineColor(line);
        return `
            <div class="line-container">
                <div class="line-header">
                    <span class="line-number" style="background-color: ${color}">
                        ${line}
                    </span>
                    <span class="destination">${destination}</span>
                </div>
                <div class="times">
                    ${times.map(time => {
                        if (time.message) {
                            return `<span class="service-message">${time.message}</span>`;
                        }
                        return `<span class="time">${time.minutes}' (${time.formatted_time})</span>`;
                    }).join(', ')}
                </div>
            </div>
        `;
    }
}