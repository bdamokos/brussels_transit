/**
 * @fileoverview Transit display initialization
 */

import { MapManager } from './map.js';
import { getSettingsToken } from './utils.js';
import { isGeolocationAvailable, handleError } from './utils.js';
import { VehicleManager } from './vehicles.js';
import { StopManager } from './stops.js';
import { updateServiceMessages } from './messages.js';

/**
 * Main transit display controller
 */
class TransitDisplay {
    constructor() {
        this.providers = new Map();
        this.map = null;
        this.refreshInterval = null;
        this.settings = null;
        this.vehicleManager = null;  // Will initialize after map
        this.stopManager = null;  // Will initialize after getting settings
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
                // Initialize settings.lineColors if not present
                if (!this.settings.lineColors) {
                    this.settings.lineColors = {};
                }
            } else {
                throw new Error('Failed to get settings');
            }
            
            // Initialize map with settings
            await this.initializeMap();
            
            // Initialize stop manager with container element
            const stopsContainer = document.getElementById('stops-container');
            if (!stopsContainer) {
                throw new Error('Stops container element not found');
            }
            this.stopManager = new StopManager(stopsContainer);
            
            // Initialize vehicle manager after map
            this.vehicleManager = new VehicleManager(this.map, this.stopManager);
            
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
                    console.log(`Loading provider: ${providerInfo.name}`);
                    
                    // Use the provider path from settings, fallback to name if not set
                    const providerPath = providerInfo.path || providerInfo.name;
                    const modulePath = `/transit_providers/${providerPath}/js/provider.js`;
                    
                    console.log(`Loading provider module from: ${modulePath}`);
                    const module = await import(modulePath);
                    
                    // Get provider class (should be named [Name]Provider, e.g., STIBProvider)
                    const className = `${providerInfo.name.charAt(0).toUpperCase()}${providerInfo.name.slice(1)}Provider`;
                    const ProviderClass = module[className];
                    
                    if (!ProviderClass) {
                        console.error(`No provider class found for ${providerInfo.name}`);
                        continue;
                    }
                    
                    // Create provider instance without providerInfo
                    const provider = new ProviderClass();
                    
                    // Initialize provider
                    await provider.initialize();
                    
                    // Store provider
                    this.providers.set(providerInfo.name, provider);
                    
                    // Register provider with StopManager
                    this.stopManager.registerProvider(provider);
                    
                    console.log(`${providerInfo.name} provider initialized`);
                    
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
        // Don't start if already running
        if (this.refreshTimer) {
            console.log("Refresh cycle already running, skipping...");
            return;
        }
        
        // Set refresh interval from settings or use default
        this.refreshInterval = (this.settings?.refresh_interval || 30) * 1000;
        console.log(`Starting refresh cycle with interval: ${this.refreshInterval}ms`);

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
                console.log(`Fetching data from provider: ${provider.id}`);
                const [stops, vehicles, messages, routes] = await Promise.all([
                    provider.getStops(),
                    provider.getVehicles(),
                    provider.getMessages(),
                    provider.getRoutes()
                ]);
                
                console.log(`Provider ${provider.id} data:`, {
                    stops: stops,
                    vehicles: vehicles,
                    messages: messages,
                    routes: routes
                });
                
                // Merge data, adding provider ID to each item
                if (stops) {
                    Object.entries(stops).forEach(([stopId, stop]) => {
                        allData.stops[stopId] = {
                            ...stop,
                            provider: provider.id
                        };
                    });
                }
                if (vehicles) {
                    allData.vehicles.push(...vehicles.map(v => ({ ...v, provider: provider.id })));
                }
                if (messages) {
                    allData.messages.push(...messages.map(m => ({ ...m, provider: provider.id })));
                }
                if (routes) {
                    Object.assign(allData.routes, routes);
                }
            }
            
            console.log("Combined data from all providers:", allData);
            
            // Update map with new data
            if (this.map) {
                // Clear existing layers
                this.map.clearLayers();
                
                // Update routes for each provider
                for (const provider of this.providers.values()) {
                    this.map.addRoutes(provider, allData.routes);
                }
                
                // Add/update stop markers
                for (const [stopId, stop] of Object.entries(allData.stops)) {
                    const provider = this.providers.get(stop.provider);
                    if (!provider) {
                        console.warn(`No provider instance found for stop ${stopId} (provider: ${stop.provider})`);
                        continue;
                    }
                    this.map.addStopMarker(stop, provider);
                }
                
                // Update vehicle positions using VehicleManager
                if (allData.vehicles && Array.isArray(allData.vehicles)) {
                    const vehiclesByProvider = new Map();
                    allData.vehicles.forEach(vehicle => {
                        if (!vehiclesByProvider.has(vehicle.provider)) {
                            vehiclesByProvider.set(vehicle.provider, []);
                        }
                        vehiclesByProvider.get(vehicle.provider).push(vehicle);
                    });

                    for (const [providerId, vehicles] of vehiclesByProvider) {
                        const provider = this.providers.get(providerId);
                        if (provider) {
                            this.vehicleManager.updateVehicles(vehicles, provider);
                        }
                    }
                }
            }
            
            // Update service messages
            if (allData.messages) {
                updateServiceMessages(allData.messages);
            }
            
            // Update stops list using StopManager
            if (allData.stops) {
                console.log("Updating stops list with data:", allData.stops);
                this.stopManager.updateStopsList(allData.stops);
            }
            
        } catch (error) {
            handleError('Error during data refresh', error);
        }
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

// Initialize in the correct order
document.addEventListener('DOMContentLoaded', async () => {
    try {
        // Initialize transit display
        window.transitDisplay = new TransitDisplay();
        await window.transitDisplay.initialize();
    } catch (error) {
        handleError('Failed to initialize transit display', error);
    }
}); 