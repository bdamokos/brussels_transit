import { properTitle } from './utils.js';

export class StopManager {
    constructor(mapManager) {
        this.container = document.getElementById('stops-container');
        this.stopSections = new Map();  // name -> DOM element
        this.mapManager = mapManager;  // Store reference to map manager
        this.providers = new Map();  // provider name -> instance
    }

    /**
     * Register a transit provider
     * @param {Object} provider - Provider instance
     */
    registerProvider(provider) {
        this.providers.set(provider.name, provider);
    }

    /**
     * Update or create a stop section
     * @param {Object} stop - Stop data
     * @param {Object} provider - Transit provider instance
     */
    updateStop(stop, provider) {
        let section = this.stopSections.get(stop.name);
        
        // Create section if it doesn't exist
        if (!section) {
            section = this.createStopSection(stop.name);
            this.stopSections.set(stop.name, section);
            this.container.appendChild(section);
        }

        // Find or create physical stop element
        let stopElement = section.querySelector(`[data-stop-id="${stop.id}"]`);
        if (!stopElement) {
            stopElement = this.createPhysicalStop(stop.id, provider.name);
            const content = section.querySelector('.stop-content');
            
            // Add divider if not first stop in section
            const existingStops = content.querySelectorAll('.physical-stop');
            if (existingStops.length > 0) {
                stopElement.insertBefore(
                    this.createDivider(),
                    stopElement.firstChild
                );
            }
            
            content.appendChild(stopElement);
        }

        // Update stop content
        this.updateStopContent(stopElement, stop, provider);
    }

    /**
     * Update stop content with real-time data
     */
    async updateStopContent(element, stop, provider) {
        return this.safeExecute('updateStopContent', async () => {
            if (!stop.lines || Object.keys(stop.lines).length === 0) {
                element.innerHTML = '<div class="no-data">No real-time data available</div>';
                return;
            }

            element.innerHTML = '';
            Object.entries(stop.lines).forEach(([line, destinations]) => {
                Object.entries(destinations).forEach(([destination, times]) => {
                    if (!times || times.length === 0) return;

                    const lineContainer = document.createElement('div');
                    lineContainer.className = 'line-container';
                    lineContainer.innerHTML = provider.formatLineContainer(line, destination, times, provider);
                    element.appendChild(lineContainer);
                });
            });
        }, { stopId: element.dataset.stopId });
    }

    /**
     * Create a new stop section
     * @param {string} name - Stop name
     * @returns {HTMLElement} The created section
     */
    createStopSection(name) {
        const section = document.createElement('div');
        section.className = 'stop-section';
        section.dataset.stopName = name;
        
        section.innerHTML = `
            <h2>${properTitle(name)}</h2>
            <div class="stop-content"></div>
        `;
        
        return section;
    }

    /**
     * Create a distance element
     * @returns {HTMLElement} The created element
     */
    createDistanceElement() {
        const element = document.createElement('div');
        element.className = 'stop-distance';
        return element;
    }

    /**
     * Create a physical stop element
     * @param {string} stopId - Stop ID
     * @param {string} providerName - Provider name
     * @returns {HTMLElement} The created element
     */
    createPhysicalStop(stopId, providerName) {
        const element = document.createElement('div');
        element.className = 'physical-stop';
        element.dataset.stopId = stopId;
        element.dataset.provider = providerName;
        element.innerHTML = '<div class="loading">Loading real-time data...</div>';
        return element;
    }

    /**
     * Sort stops by distance
     * @param {Map<string, number>} distances - Map of stop IDs to distances
     */
    sortByDistance(distances) {
        const sections = Array.from(this.container.children);
        sections.sort((a, b) => {
            const aStopId = a.querySelector('.physical-stop')?.dataset.stopId;
            const bStopId = b.querySelector('.physical-stop')?.dataset.stopId;
            return (distances.get(aStopId) || Infinity) - (distances.get(bStopId) || Infinity);
        });
        
        sections.forEach(section => this.container.appendChild(section));
    }

    /**
     * Format a line container with default styling
     * @param {string} line - Line number/name
     * @param {string} destination - Destination name
     * @param {Array} times - Array of time objects
     * @param {Object} provider - Transit provider instance
     * @returns {string} HTML string
     */
    formatLineContainer(line, destination, times, provider) {
        const style = provider.getLineStyle?.(line) || 'background-color: #666; color: white;';
        const lineClass = provider.getLineClass?.(line) || 'line-number';
        
        return `
            <div class="line-info">
                <span class="${lineClass}" style="${style}">
                    ${line}
                </span>
                <span class="direction">→ ${properTitle(destination)}</span>
            </div>
            <div class="times-container">
                ${this.formatTimes(times, provider)}
            </div>
        `;
    }

    /**
     * Format time entries with provider-specific handling
     * @param {Array} times - Array of time objects
     * @param {Object} provider - Transit provider instance
     * @returns {string} HTML string
     */
    formatTimes(times, provider) {
        return times.map(time => {
            // Let provider override if it wants to
            if (provider.formatTime) {
                const customFormat = provider.formatTime(time);
                if (customFormat) return customFormat;
            }

            // Handle message-only entries
            if (time.message) {
                return `<span class="service-message">${time.message}</span>`;
            }

            // Default formatting with fallbacks
            const minutes = time.realtime_minutes || time.minutes || time.scheduled_minutes;
            const displayTime = time.realtime_time || time.formatted_time || time.scheduled_time;
            
            if (!minutes || !displayTime) return '';

            // Default delay handling
            const delayClass = this.getDelayClass(time);
            
            // Default realtime indicator
            const timeIndicator = time.is_realtime ? '⚡' : 
                                time.scheduled_time ? '🕒' : '';

            return `
                <span class="time-display">
                    <span class="minutes ${delayClass}">${minutes}'</span>
                    <span class="actual-time">(${timeIndicator} ${displayTime})</span>
                </span>
            `;
        }).filter(Boolean).join('');
    }

    /**
     * Get delay class based on time data
     * @param {Object} time - Time entry
     * @returns {string} CSS class
     */
    getDelayClass(time) {
        if (!time.delay) return '';
        return time.delay < 0 ? 'early' : time.delay > 0 ? 'late' : 'on-time';
    }

    /**
     * Update multiple stops at once
     * @param {Object} stopsData - Map of stop data by ID
     * @param {Object} provider - Transit provider instance
     */
    updateStops(stopsData, provider) {
        Object.entries(stopsData).forEach(([stopId, stopData]) => {
            // Ensure stop ID is set in the data
            this.updateStop({
                ...stopData,
                id: stopId
            }, provider);
        });
    }

    /**
     * Update distances for all stops
     * @param {Object} point - {lat, lng} coordinates
     */
    updateAllDistances(point) {
        const distances = new Map();
        this.stopSections.forEach((section, name) => {
            const stopId = section.querySelector('.physical-stop')?.dataset.stopId;
            if (stopId) {
                const distance = this.calculateDistance(point, stopId);
                if (distance !== null) {
                    distances.set(stopId, distance);
                    this.updateStop({ id: stopId, name }, null, distance);
                }
            }
        });
        this.sortByDistance(distances);
    }

    /**
     * Clear all distances
     */
    clearDistances() {
        this.stopSections.forEach(section => {
            const distanceElement = section.querySelector('.stop-distance');
            if (distanceElement) {
                distanceElement.remove();
            }
        });
    }

    /**
     * Reset all stops to loading state
     */
    reset() {
        this.stopSections.forEach(section => {
            const stopElements = section.querySelectorAll('.physical-stop');
            stopElements.forEach(element => {
                element.innerHTML = '<div class="loading">Loading real-time data...</div>';
            });
        });
    }

    /**
     * Calculate distance to a stop
     * @param {Object} point - {lat, lng} coordinates
     * @param {string} stopId - Stop ID
     * @returns {number|null} Distance in meters or null if stop not found
     */
    calculateDistance(point, stopId) {
        const section = Array.from(this.stopSections.values())
            .find(s => s.querySelector(`[data-stop-id="${stopId}"]`));
            
        if (!section) return null;

        const stopElement = section.querySelector('.physical-stop');
        const provider = this.providers.get(stopElement.dataset.provider);
        if (!provider) return null;

        const stopData = provider.getStopCoordinates(stopId);
        if (!stopData?.coordinates) return null;

        return this.mapManager.calculateDistance(point, [stopData.coordinates.lat, stopData.coordinates.lon]);
    }

    /**
     * Add divider between stops
     * @param {HTMLElement} element - Stop element
     * @param {boolean} isFirst - Whether this is the first stop
     */
    addStopDivider(element, isFirst) {
        if (!isFirst) {
            const divider = document.createElement('div');
            divider.className = 'stop-divider';
            element.insertBefore(divider, element.firstChild);
        }
    }

    /**
     * Initialize stop sections from static data
     */
    async initializeStops(stops, provider) {
        return this.safeExecute('initializeStops', async () => {
            this.logDebug('initializeStops', `Initializing ${stops.length} stops for ${provider.name}`);
            
            // Group stops by name
            const groupedStops = new Map();
            stops.forEach(stop => {
                if (!groupedStops.has(stop.name)) {
                    groupedStops.set(stop.name, []);
                }
                groupedStops.get(stop.name).push(stop);
            });

            // Create sections for each group
            groupedStops.forEach((stops, name) => {
                this.logDebug('initializeStops', `Creating section for ${name} with ${stops.length} stops`);
                const section = this.createStopSection(name);
                this.stopSections.set(name, section);
                
                // Add each physical stop
                stops.forEach((stop, index) => {
                    const stopElement = this.createPhysicalStop(stop.id, provider.name);
                    const content = section.querySelector('.stop-content');
                    
                    // Add divider if not first stop
                    if (index > 0) {
                        stopElement.insertBefore(this.createDivider(), stopElement.firstChild);
                    }
                    
                    content.appendChild(stopElement);
                });
                
                this.container.appendChild(section);
            });
        }, { provider: provider.name });
    }

    /**
     * Update stop times
     * @param {Object} stopsData - Map of stop data by ID
     * @param {Object} provider - Transit provider instance
     */
    updateTimes(stopsData, provider) {
        Object.entries(stopsData).forEach(([stopId, stopData]) => {
            const stopElement = this.container.querySelector(`[data-stop-id="${stopId}"]`);
            if (stopElement) {
                this.updateStopContent(stopElement, stopData, provider);
            }
        });
    }

    /**
     * Update stop distance display
     * @param {HTMLElement} section - Stop section element
     * @param {number} distance - Distance in meters
     */
    updateStopDistance(section, distance) {
        const walkingTime = this.mapManager.calculateWalkingTime(distance);
        const distanceElement = section.querySelector('.stop-distance') || 
            this.createDistanceElement();
        
        distanceElement.innerHTML = `
            <span class="walking-time"> ${walkingTime} min</span>
            <span class="distance">(${this.mapManager.formatDistance(distance)})</span>
        `;
        
        section.querySelector('h2').appendChild(distanceElement);
    }

    /**
     * Update distances from a point
     * @param {Object} point - {lat, lng} coordinates
     */
    updateDistances(point) {
        this.stopSections.forEach((section) => {
            const stopElement = section.querySelector('.physical-stop');
            if (!stopElement) return;

            const provider = this.providers.get(stopElement.dataset.provider);
            if (!provider) return;

            const stopId = stopElement.dataset.stopId;
            const distance = this.mapManager.calculateDistance(
                point,
                provider.getStopCoordinates(stopId)
            );

            if (distance !== null) {
                this.updateStopDistance(section, distance);
            }
        });
    }

    /**
     * Create a divider element
     * @returns {HTMLElement}
     */
    createDivider() {
        const divider = document.createElement('div');
        divider.className = 'stop-divider';
        return divider;
    }

    /**
     * Sort sections by name
     */
    sortByName() {
        const sections = Array.from(this.container.children);
        sections.sort((a, b) => {
            const aName = a.dataset.stopName;
            const bName = b.dataset.stopName;
            return aName.localeCompare(bName);
        });
        sections.forEach(section => this.container.appendChild(section));
    }

    /**
     * Get all stop IDs
     * @returns {Array<string>} Array of stop IDs
     */
    getAllStopIds() {
        const ids = [];
        this.stopSections.forEach(section => {
            const stopElements = section.querySelectorAll('.physical-stop');
            stopElements.forEach(element => {
                ids.push(element.dataset.stopId);
            });
        });
        return ids;
    }

    /**
     * Show error for a stop
     * @param {string} stopId - Stop ID
     * @param {string} message - Error message
     */
    showStopError(stopId, message) {
        const stopElement = this.container.querySelector(`[data-stop-id="${stopId}"]`);
        if (stopElement) {
            stopElement.innerHTML = `<div class="error">${message}</div>`;
        }
    }

    /**
     * Remove all stop sections
     */
    clear() {
        this.stopSections.clear();
        this.container.innerHTML = '';
    }

    /**
     * Remove stops for a specific provider
     * @param {string} providerName - Provider name
     */
    removeProviderStops(providerName) {
        this.stopSections.forEach((section, name) => {
            const stopElements = section.querySelectorAll(
                `.physical-stop[data-provider="${providerName}"]`
            );
            stopElements.forEach(el => el.remove());
            
            // Remove section if empty
            if (section.querySelector('.physical-stop') === null) {
                section.remove();
                this.stopSections.delete(name);
            }
        });
    }

    /**
     * Log an error with context
     * @param {string} method - Method name where error occurred
     * @param {Error} error - Error object
     * @param {Object} context - Additional context
     */
    logError(method, error, context = {}) {
        console.error(`StopManager.${method} error:`, error, context);
    }

    /**
     * Log debug information
     * @param {string} method - Method name
     * @param {string} message - Debug message
     * @param {Object} data - Debug data
     */
    logDebug(method, message, data = {}) {
        console.debug(`StopManager.${method}: ${message}`, data);
    }

    /**
     * Safely execute a method with error handling
     * @param {string} method - Method name
     * @param {Function} fn - Function to execute
     * @param {Object} context - Error context
     */
    async safeExecute(method, fn, context = {}) {
        try {
            return await fn();
        } catch (error) {
            this.logError(method, error, context);
            throw error;
        }
    }

    /**
     * Get line style with fallbacks
     * @param {string} line - Line number/name
     * @param {Object} provider - Transit provider instance
     * @returns {string} CSS style string
     */
    getLineStyle(line, provider) {
        // Let provider override if it wants to
        if (provider.getLineStyle) {
            const customStyle = provider.getLineStyle(line);
            if (customStyle) return customStyle;
        }

        // Default style with fallback color
        return `background-color: #666; color: white;`;
    }

    /**
     * Update the stops list in the UI
     * @param {Object} stops - The stops data
     */
    updateStopsList(stops) {
        this.container.innerHTML = '';  // Clear existing stops
        this.stopSections.clear();  // Clear the sections map

        // Group stops by name
        const stopsByName = new Map();
        Object.values(stops).forEach(stop => {
            if (!stopsByName.has(stop.name)) {
                stopsByName.set(stop.name, []);
            }
            stopsByName.get(stop.name).push(stop);
        });

        // Create sections for each stop name
        for (const [name, stopsAtLocation] of stopsByName) {
            const section = this.createStopSection(name);
            this.stopSections.set(name, section);
            this.container.appendChild(section);

            stopsAtLocation.forEach(stop => {
                const stopElement = this.createPhysicalStop(stop.id, stop.provider);
                section.querySelector('.stop-content').appendChild(stopElement);
            });
        }
    }
}