/**
 * Map management module
 */

import * as L from 'https://unpkg.com/leaflet@1.9.4/dist/leaflet-src.esm.js';
import { settings, handleError } from './utils.js';

export { L };

export class MapManager {
    constructor() {
        this.map = null;
        this.initialConfig = null;  // Store initial config
        this.layers = {
            routes: null,
            stops: null,
            vehicles: null
        };
        this.vehicleMarkers = new Map();
    }

    async loadLeafletCSS() {
        return new Promise((resolve, reject) => {
            const link = document.createElement('link');
            link.rel = 'stylesheet';
            link.href = 'https://unpkg.com/leaflet@1.9.4/dist/leaflet.css';
            link.onload = resolve;
            link.onerror = reject;
            document.head.appendChild(link);
        });
    }

    /**
     * Initialize the map and its layers
     */
    async initialize(mapConfig = null) {
        try {
            // Store initial config
            this.initialConfig = mapConfig || settings.map_config;
            
            // Load Leaflet CSS first
            await this.loadLeafletCSS();
            
            // Create map
            this.map = L.map('map', {
                center: [this.initialConfig.center.lat, this.initialConfig.center.lon],
                zoom: this.initialConfig.zoom,
                zoomControl: true
            });

            // Add tile layer
            L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
                maxZoom: 19,
                minZoom: 11,
                attribution: ' OpenStreetMap contributors'
            }).addTo(this.map);

            // Create panes with z-index
            this.map.createPane('routesPane').style.zIndex = 400;
            this.map.createPane('stopsPane').style.zIndex = 450;
            this.map.createPane('vehiclesPane').style.zIndex = 500;

            // Initialize layers
            this.layers = {
                routes: L.featureGroup([], { pane: 'routesPane' }).addTo(this.map),
                stops: L.featureGroup([], { pane: 'stopsPane' }).addTo(this.map),
                vehicles: L.featureGroup([], { pane: 'vehiclesPane' }).addTo(this.map)
            };

            // Add layer control
            L.control.layers(null, {
                "Routes": this.layers.routes,
                "Stops": this.layers.stops,
                "Vehicles": this.layers.vehicles
            }).addTo(this.map);

        } catch (error) {
            handleError('Failed to initialize map', error);
            throw error;
        }
    }

    /**
     * Create a vehicle marker
     * @param {Object} vehicle - Vehicle data
     * @param {Object} provider - Transit provider instance
     * @returns {L.Marker} Leaflet marker
     */
    createVehicleMarker(vehicle, provider) {
        const icon = L.divIcon({
            className: `vehicle-marker line-${vehicle.line}`,
            html: `<div class="vehicle-icon" style="background-color: ${provider.getLineColor(vehicle.line)}">
                    <span class="line-number">${vehicle.line}</span>
                   </div>`,
            iconSize: [24, 24],
            iconAnchor: [12, 12]
        });
        
        const marker = L.marker([vehicle.coordinates.lat, vehicle.coordinates.lon], {
            icon: icon,
            rotationAngle: vehicle.bearing || 0,
            rotationOrigin: 'center center',
            pane: 'vehiclesPane'
        });
        
        return marker;
    }

    /**
     * Add route shapes to the map
     * @param {Object} provider - Transit provider instance
     * @param {Object} shapes - Route shape data
     */
    addRoutes(provider, shapes) {
        console.log(`Adding routes for provider ${provider.id}:`, shapes);
        if (!shapes) return;
        
        this.layers.routes.clearLayers();
        
        Object.entries(shapes).forEach(([line, shapeData]) => {
            console.log(`Processing line ${line}:`, shapeData);
            shapeData.variants?.forEach(variant => {
                if (variant?.coordinates?.length > 1) {
                    const coordinates = variant.coordinates.map(coord => [coord.lat, coord.lon]);
                    console.log(`Adding polyline for line ${line}, coordinates:`, coordinates);
                    L.polyline(coordinates, {
                        color: provider.getLineColor(line),
                        weight: 3,
                        opacity: 0.7,
                        pane: 'routesPane',
                        interactive: false
                    }).addTo(this.layers.routes);
                }
            });
        });
    }

    /**
     * Add a stop marker to the map
     * @param {Object} stop - Stop data
     * @param {Object} provider - Transit provider instance
     */
    addStopMarker(stop, provider) {
        if (!stop.coordinates?.lat || !stop.coordinates?.lon) return;

        const marker = L.circleMarker(
            [stop.coordinates.lat, stop.coordinates.lon],
            {
                radius: 8,
                fillColor: '#fff',
                color: '#000',
                weight: 2,
                opacity: 1,
                fillOpacity: 0.8,
                pane: 'stopsPane'
            }
        );

        // Store stop ID and provider with marker
        marker.stopId = stop.id;
        marker.provider = provider;

        // Create initial popup content
        this.updateStopPopup(marker, stop, provider);
        
        marker.addTo(this.layers.stops);
        return marker;
    }

    /**
     * Update a stop's popup content
     * @param {Object} marker - Leaflet marker
     * @param {Object} stop - Stop data
     * @param {Object} provider - Transit provider instance
     */
    updateStopPopup(marker, stop, provider) {
        const popupContent = provider.formatStopPopup(stop);
        marker.bindPopup(popupContent);
        
        // Update if popup is open
        if (marker.isPopupOpen()) {
            marker.getPopup().setContent(popupContent);
        }
    }

    /**
     * Update vehicle positions on the map
     * @param {Array} vehicles - Array of vehicle data
     * @param {Object} provider - Transit provider instance
     */
    updateVehicles(vehicles, provider) {
        console.log(`Updating vehicles for provider ${provider.id}:`, vehicles);
        if (!Array.isArray(vehicles)) {
            console.warn('Vehicles data is not an array:', vehicles);
            return;
        }

        const newVehiclePositions = new Set();
        
        vehicles.forEach(vehicle => {
            if (!vehicle.coordinates?.lat || !vehicle.coordinates?.lon || !vehicle.isValid) {
                console.debug('Skipping invalid vehicle:', vehicle);
                return;
            }
            
            // Create a unique key for this vehicle
            const vehicleKey = `${provider.id}-${vehicle.line}-${vehicle.direction || ''}`;
            const vehiclePos = [vehicle.coordinates.lat, vehicle.coordinates.lon];
            
            console.log(`Processing vehicle ${vehicleKey} at position:`, vehiclePos);
            
            // Try to find existing marker
            let existingMarker = null;
            let minDistance = Infinity;
            
            this.vehicleMarkers.forEach((marker, key) => {
                if (!key.startsWith(vehicleKey)) return;
                
                const markerPos = marker.getLatLng();
                const distance = this.calculateDistance(
                    vehiclePos,
                    [markerPos.lat, markerPos.lng]
                );
                
                // Consider it the same vehicle if within 500m
                if (distance < 500 && distance < minDistance) {
                    existingMarker = marker;
                    minDistance = distance;
                }
            });
            
            if (existingMarker) {
                // Update existing marker
                console.log(`Updating existing marker for ${vehicleKey}`);
                existingMarker.setLatLng(vehiclePos);
                if (vehicle.bearing !== undefined) {
                    existingMarker.setRotationAngle(vehicle.bearing);
                }
                newVehiclePositions.add(vehicleKey);
            } else {
                // Create new marker
                console.log(`Creating new marker for ${vehicleKey}`);
                const marker = this.createVehicleMarker(vehicle, provider);
                const markerKey = `${vehicleKey}-${Date.now()}`;  // Use timestamp to ensure uniqueness
                this.vehicleMarkers.set(markerKey, marker);
                newVehiclePositions.add(markerKey);
                
                // Add popup
                const popupContent = `<div class="vehicle-popup">
                    <strong>Line ${vehicle.line}</strong><br>
                    Direction: ${vehicle.direction || 'Unknown'}
                </div>`;
                marker.bindPopup(popupContent);
                marker.addTo(this.layers.vehicles);
            }
        });
        
        // Remove stale markers
        this.vehicleMarkers.forEach((marker, key) => {
            if (!newVehiclePositions.has(key)) {
                console.log(`Removing stale marker: ${key}`);
                marker.remove();
                this.vehicleMarkers.delete(key);
            }
        });
    }

    /**
     * Update an existing vehicle marker
     * @param {Object} marker - Leaflet marker
     * @param {Object} vehicle - Vehicle data
     * @param {Object} provider - Transit provider instance
     */
    updateVehicleMarker(marker, vehicle, provider) {
        // Update icon
        const icon = this.createVehicleIcon(vehicle, provider);
        marker.setIcon(icon);
        
        // Update bearing
        if (vehicle.bearing !== undefined) {
            this.setVehicleBearing(marker, vehicle.bearing);
        }
        
        // Update popup if open
        if (marker.isPopupOpen()) {
            const popupContent = provider.formatVehiclePopup(vehicle);
            marker.getPopup().setContent(popupContent);
        }
    }

    /**
     * Create a vehicle icon
     * @param {Object} vehicle - Vehicle data
     * @param {Object} provider - Transit provider instance
     */
    createVehicleIcon(vehicle, provider) {
        const style = provider.getVehicleStyle(vehicle);
        return L.divIcon({
            html: `
                <div class="vehicle-marker-content" style="${style}">
                    <div class="${provider.getVehicleClass(vehicle)}">
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
     * Reset map view to default position
     */
    resetView() {
        if (this.map && this.initialConfig) {
            this.map.setView(
                [this.initialConfig.center.lat, this.initialConfig.center.lon],
                this.initialConfig.zoom
            );
        }
    }

    /**
     * Calculate distance between two points
     * @param {Array} point1 - [lat, lon]
     * @param {Array} point2 - [lat, lon]
     * @returns {number} Distance in meters
     */
    calculateDistance(point1, point2) {
        return this.map.distance(point1, point2);
    }

    /**
     * Get current map center
     * @returns {Object} {lat, lng}
     */
    getCenter() {
        return this.map.getCenter();
    }

    /**
     * Add map movement handler
     * @param {Function} callback - Function to call when map moves
     */
    onMove(callback) {
        this.map.on('moveend', callback);
    }

    /**
     * Clear all layers
     */
    clearLayers() {
        this.layers.routes.clearLayers();
        this.layers.stops.clearLayers();
        this.layers.vehicles.clearLayers();
        this.vehicleMarkers.clear();
    }

    /**
     * Update distances to stops from a point
     * @param {Object} point - {lat, lng} coordinates
     * @returns {Map<string, number>} Map of stop IDs to distances
     */
    updateStopDistances(point) {
        const distances = new Map();
        
        this.layers.stops.eachLayer(marker => {
            const markerPos = marker.getLatLng();
            const distance = this.calculateDistance(
                [point.lat, point.lng],
                [markerPos.lat, markerPos.lng]
            );
            distances.set(marker.stopId, distance);
        });
        
        return distances;
    }

    /**
     * Use map center for distance calculations
     * @param {Function} callback - Called with new distances when map moves
     */
    useMapCenterForDistances(callback) {
        // Initial calculation
        callback(this.updateStopDistances(this.getCenter()));
        
        // Update on map movement
        this.onMove(() => {
            callback(this.updateStopDistances(this.getCenter()));
        });
    }

    /**
     * Set vehicle bearing (rotation)
     * @param {Object} marker - Vehicle marker
     * @param {number} bearing - Bearing in degrees
     */
    setVehicleBearing(marker, bearing) {
        const content = marker.getElement().querySelector('.vehicle-marker-content');
        if (content) {
            content.style.setProperty('--bearing', `${bearing}deg`);
        }
    }

    /**
     * Find a stop marker by ID
     * @param {string} stopId - Stop ID to find
     * @returns {Object|null} Leaflet marker or null if not found
     */
    findStopMarker(stopId) {
        let found = null;
        this.layers.stops.eachLayer(marker => {
            if (marker.stopId === stopId) {
                found = marker;
            }
        });
        return found;
    }

    /**
     * Update all stop popups
     * @param {Object} stopsData - Map of stop data by ID
     */
    updateAllStopPopups(stopsData) {
        this.layers.stops.eachLayer(marker => {
            const stopData = stopsData[marker.stopId];
            if (stopData) {
                this.updateStopPopup(marker, stopData, marker.provider);
            }
        });
    }

    /**
     * Set the map center
     * @param {Object} center - {lat, lon} coordinates
     */
    setCenter(center) {
        if (this.map) {
            this.map.setView([center.lat, center.lon], this.map.getZoom());
        }
    }
}

// Add to window for onclick handler
window.resetMapView = () => {
    // Get the TransitDisplay instance
    const display = window.transitDisplay;
    if (display && display.map) {
        display.map.resetView();
    }
}; 