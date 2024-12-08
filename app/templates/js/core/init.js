/**
 * @fileoverview Transit display initialization
 */

import { MapManager } from './map.js';
import { getSettingsToken } from './utils.js';
import { isGeolocationAvailable, handleError } from './utils.js';
import { TransitProvider } from './provider.js';

/**
 * Main transit display controller
 */
class TransitDisplay {
    constructor() {
        this.providers = new Map();
        this.map = null;
        this.refreshInterval = null;
        this.settings = null;
    }

    /**
     * Initialize the transit display
     */
    async initialize() {
        try {
            console.log("Starting initialization...");
            
            // Get settings first
            const response = await fetch('/api/settings', {
                headers: {
                    'X-Settings-Token': await getSettingsToken()
                }
            });
            
            if (response.ok) {
                this.settings = await response.json();
            } else {
                throw new Error('Failed to get settings');
            }
            
            // Initialize map with settings
            await this.initializeMap();
            
            // Then try to initialize providers
            try {
                await this.initializeProviders();
            } catch (error) {
                console.error('Provider initialization failed:', error);
                handleError('Provider initialization failed', error);
                // Continue execution - we still have a map
            }
            
            // Start refresh cycle if we have any providers
            if (this.providers.size > 0) {
                this.startRefreshCycle();
            }
            
            // Initialize geolocation if available
            if (isGeolocationAvailable()) {
                this.initializeGeolocation();
            }
            
        } catch (error) {
            handleError('Error during initialization', error);
        }
    }

    /**
     * Initialize the map
     */
    async initializeMap() {
        try {
            // Get basic map config from settings
            const response = await fetch('/api/settings', {
                headers: {
                    'X-Settings-Token': await getSettingsToken()
                }
            });
            
            let mapConfig;
            if (response.ok) {
                const settings = await response.json();
                mapConfig = settings.map_config;
            } else {
                // Use default config if settings request fails
                mapConfig = {
                    center: { lat: 50.8465, lon: 4.3517 },  // Brussels
                    zoom: 13
                };
            }

            // Initialize map with configuration
            this.map = new MapManager();
            await this.map.initialize(mapConfig);
            
        } catch (error) {
            handleError('Failed to initialize map', error);
            throw error;
        }
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

    /**
     * Initialize geolocation if available
     */
    initializeGeolocation() {
        if (!this.map || !this.settings) return;

        const updateDistances = (position) => {
            const point = {
                lat: position.coords.latitude,
                lon: position.coords.longitude
            };
            this.map.updateStopDistances(point);
        };

        if (isGeolocationAvailable()) {
            // Get initial position
            navigator.geolocation.getCurrentPosition(
                updateDistances,
                (error) => {
                    console.warn('Geolocation error:', error);
                    this.useMapCenter();
                }
            );

            // Watch for position updates with the configured interval
            navigator.geolocation.watchPosition(
                (() => {
                    let lastUpdate = 0;
                    return (position) => {
                        const now = Date.now();
                        if (now - lastUpdate >= this.settings.location_update_interval * 1000) {
                            lastUpdate = now;
                            updateDistances(position);
                        }
                    };
                })(),
                null,
                { 
                    enableHighAccuracy: true,
                    timeout: this.settings.location_update_interval * 1000
                }
            );
        } else {
            this.useMapCenter();
        }
    }

    /**
     * Use map center for distance calculations
     */
    useMapCenter() {
        if (this.map) {
            this.map.useMapCenterForDistances();
        }
    }
}

// Store instance globally for reset function
window.transitDisplay = new TransitDisplay();
document.addEventListener('DOMContentLoaded', () => {
    window.transitDisplay.initialize();
}); 