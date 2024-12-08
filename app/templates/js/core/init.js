/**
 * @fileoverview Transit display initialization
 */

import { TransitProvider } from './provider.js';
import { getSettingsToken } from './utils.js';
import { isGeolocationAvailable, handleError } from './utils.js';
import L from 'https://unpkg.com/leaflet@1.9.4/dist/leaflet-src.esm.js';

/**
 * Main transit display controller
 */
class TransitDisplay {
    constructor() {
        this.providers = new Map();
        this.map = null;
        this.refreshInterval = null;  // Will be set from settings
        this.refreshTimer = null;
    }

    /**
     * Load CSS dynamically
     * @param {string} url - URL of the CSS file
     * @returns {Promise} Resolves when CSS is loaded
     */
    loadCSS(url) {
        return new Promise((resolve, reject) => {
            const link = document.createElement('link');
            link.rel = 'stylesheet';
            link.href = url;
            
            link.onload = () => resolve();
            link.onerror = () => reject(new Error(`Failed to load CSS: ${url}`));
            
            document.head.appendChild(link);
        });
    }

    /**
     * Initialize the transit display
     */
    async initialize() {
        try {
            console.log("Starting initialization...");
            
            // Get settings first
            const settings = await this.getEnabledProviders();
            this.refreshInterval = settings.refresh_interval;
            
            // Initialize providers
            await this.initializeProviders();
            
            // Initialize map
            await this.initializeMap();
            
            // Start data refresh cycle
            this.startRefreshCycle();
            
            // Initialize geolocation if available
            if (isGeolocationAvailable()) {
                this.initializeGeolocation();
            } else {
                console.log('Geolocation not available, using map center');
                this.useMapCenter();
            }
            
        } catch (error) {
            handleError('Error during initialization', error);
        }
    }

    /**
     * Get enabled providers from settings
     */
    async getEnabledProviders() {
        const token = await getSettingsToken();
        if (!token) throw new Error('No token available');

        const response = await fetch('/api/settings', {
            headers: {
                'X-Settings-Token': token
            }
        });
        if (!response.ok) throw new Error('Failed to get settings');
        
        const settings = await response.json();
        return settings.providers || [];
    }

    /**
     * Initialize transit providers
     */
    async initializeProviders() {
        try {
            // Get enabled providers from settings
            const enabledProviders = await this.getEnabledProviders();
            console.log('Enabled providers:', enabledProviders);
            
            // Load each provider
            for (const providerInfo of enabledProviders) {
                try {
                    // Load provider assets and get provider class
                    const ProviderClass = await TransitProvider.loadProviderAssets(providerInfo.name);
                    if (!ProviderClass) {
                        console.error(`No provider class found for ${providerInfo.name}`);
                        continue;
                    }
                    
                    // Create provider instance
                    const provider = new ProviderClass(providerInfo);
                    
                    // Initialize provider
                    await provider.initialize();
                    
                    // Store provider
                    this.providers.set(provider.name, provider);
                    console.log(`${provider.name} provider initialized`);
                    
                } catch (error) {
                    console.error(`Failed to initialize provider ${providerInfo.name}:`, error);
                    // Continue with other providers
                }
            }
            
            if (this.providers.size === 0) {
                throw new Error('No providers were successfully initialized');
            }
            
        } catch (error) {
            console.error('Failed to initialize providers:', error);
            throw error;
        }
    }

    /**
     * Initialize the map
     */
    async initializeMap() {
        try {
            // Load Leaflet CSS
            await this.loadCSS('https://unpkg.com/leaflet@1.9.4/dist/leaflet.css');
            
            // Get map config from settings
            const settings = await this.getEnabledProviders();
            const mapConfig = settings.map_config;

            // Initialize map with configuration
            this.map = L.map('map', {
                center: [mapConfig.center.lat, mapConfig.center.lon],
                zoom: mapConfig.zoom,
                zoomControl: true
            });
            
            // Add tile layer
            L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
                maxZoom: 19,
                minZoom: 11,
                attribution: '© OpenStreetMap contributors'
            }).addTo(this.map);
            
            // Create map panes
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
     * Start the data refresh cycle
     */
    startRefreshCycle() {
        // Initial refresh
        this.refreshData();
        
        // Set up periodic refresh
        this.refreshTimer = setInterval(() => this.refreshData(), this.refreshInterval);
        
        // Clean up on page hide
        document.addEventListener('visibilitychange', () => {
            if (document.hidden && this.refreshTimer) {
                clearInterval(this.refreshTimer);
                this.refreshTimer = null;
            } else if (!document.hidden && !this.refreshTimer) {
                this.refreshData();
                this.refreshTimer = setInterval(() => this.refreshData(), this.refreshInterval);
            }
        });
    }

    /**
     * Refresh all transit data
     */
    async refreshData() {
        try {
            console.log("Starting data refresh...");
            
            const allData = {
                stops: {},
                vehicles: [],
                messages: [],
                routes: {}
            };
            
            // Gather data from all providers
            for (const provider of this.providers.values()) {
                const [stops, vehicles, messages, routes] = await Promise.all([
                    provider.getStops(),
                    provider.getVehicles(),
                    provider.getMessages(),
                    provider.getRoutes()
                ]);
                
                // Merge data
                Object.assign(allData.stops, stops);
                allData.vehicles.push(...vehicles);
                allData.messages.push(...messages);
                Object.assign(allData.routes, routes);
            }
            
            // Update displays
            await this.updateDisplays(allData);
            
        } catch (error) {
            handleError('Error refreshing data', error);
        }
    }

    /**
     * Update all displays with new data
     */
    async updateDisplays(data) {
        // Update stops
        await this.updateStops(data.stops);
        
        // Update vehicles
        await this.updateVehicles(data.vehicles);
        
        // Update messages
        await this.updateMessages(data.messages);
    }
}

// Initialize when DOM is loaded
document.addEventListener('DOMContentLoaded', () => {
    const display = new TransitDisplay();
    display.initialize();
}); 