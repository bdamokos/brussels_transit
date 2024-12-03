/**
 * Base transit provider interface
 * All transit providers must extend this class and implement its methods
 */
export class TransitProvider {
    /**
     * Create a new transit provider from provider info
     * @param {Object} providerInfo - Provider information from the server
     */
    constructor(providerInfo) {
        this.name = providerInfo.name;
        this.displayName = providerInfo.display_name;
        this.version = providerInfo.version;
        this.isInitialized = false;
    }

    /**
     * Load provider assets (JS, CSS)
     * @returns {Promise<void>}
     */
    static async loadProviderAssets(providerName) {
        try {
            const token = await getSettingsToken();
            if (!token) throw new Error('No token available');

            // Get provider assets information
            const response = await fetch(`/api/${providerName}/assets`, {
                headers: {
                    'X-Settings-Token': token
                }
            });
            if (!response.ok) throw new Error(`Failed to get ${providerName} assets`);
            
            const assets = await response.json();
            
            // Load CSS files
            if (assets.css) {
                for (const cssFile of assets.css) {
                    await loadCSS(cssFile);
                }
            }
            
            // Load JS files
            if (assets.js) {
                for (const jsFile of assets.js) {
                    await loadScript(jsFile);
                }
            }
            
            return assets.provider_class || null;
        } catch (error) {
            console.error(`Failed to load ${providerName} assets:`, error);
            throw error;
        }
    }

    /**
     * Check if this provider is enabled in configuration
     * @returns {Promise<boolean>}
     */
    async isEnabled() {
        try {
            const token = await getSettingsToken();
            if (!token) return false;

            const response = await fetch('/api/settings', {
                headers: {
                    'X-Settings-Token': token
                }
            });
            if (!response.ok) return false;
            
            const settings = await response.json();
            return settings.providers?.some(p => p.name === this.name) || false;
            
        } catch (error) {
            console.log(`${this.name} provider not enabled:`, error);
            return false;
        }
    }

    /**
     * Get provider configuration
     * @returns {Promise<Object>}
     */
    async getConfig() {
        const response = await fetch(`/api/${this.name}/config`);
        if (!response.ok) throw new Error(`Failed to get ${this.name} configuration`);
        return response.json();
    }

    /**
     * Initialize the provider
     * Must be called before using other methods
     * @returns {Promise<void>}
     */
    async initialize() {
        if (this.isInitialized) return;
        
        try {
            const config = await this.getConfig();
            await this.handleConfig(config);
            this.isInitialized = true;
        } catch (error) {
            console.error(`Failed to initialize ${this.name} provider:`, error);
            throw error;
        }
    }

    /**
     * Handle provider configuration
     * Override this to handle provider-specific configuration
     * @param {Object} config - Provider configuration
     * @returns {Promise<void>}
     */
    async handleConfig(config) {
        // Default implementation does nothing
    }

    /**
     * Get list of stops
     * @returns {Promise<Object>} Dictionary of stop data
     */
    async getStops() {
        throw new Error('Not implemented');
    }

    /**
     * Get real-time waiting times
     * @returns {Promise<Object>} Dictionary of waiting times by stop
     */
    async getWaitingTimes() {
        throw new Error('Not implemented');
    }

    /**
     * Get vehicle positions
     * @returns {Promise<Array>} List of vehicle positions
     */
    async getVehicles() {
        throw new Error('Not implemented');
    }

    /**
     * Get service messages
     * @returns {Promise<Array>} List of service messages
     */
    async getMessages() {
        throw new Error('Not implemented');
    }

    /**
     * Get route shapes
     * @returns {Promise<Object>} Dictionary of route shapes
     */
    async getRoutes() {
        throw new Error('Not implemented');
    }

    /**
     * Get provider-specific colors
     * @returns {Promise<Object>} Dictionary of colors by line
     */
    async getColors() {
        return {};
    }

    /**
     * Customize stop display
     * @param {HTMLElement} element - Stop element
     * @param {Object} stopData - Stop data
     * @returns {boolean} True if custom display was used
     */
    customizeStopDisplay(element, stopData) {
        return false;
    }

    /**
     * Customize message display
     * @param {HTMLElement} element - Message element
     * @param {Object} messageData - Message data
     * @returns {boolean} True if custom display was used
     */
    customizeMessageDisplay(element, messageData) {
        return false;
    }
}

/**
 * Load a CSS file dynamically
 * @param {string} url - URL of the CSS file
 * @returns {Promise<void>}
 */
function loadCSS(url) {
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
 * Load a JavaScript file dynamically
 * @param {string} url - URL of the JavaScript file
 * @returns {Promise<void>}
 */
function loadScript(url) {
    return new Promise((resolve, reject) => {
        const script = document.createElement('script');
        script.type = 'module';
        script.src = url;
        script.onload = () => resolve();
        script.onerror = () => reject(new Error(`Failed to load script: ${url}`));
        document.head.appendChild(script);
    });
}

/**
 * Get settings token
 * @returns {Promise<string>} Authentication token
 */
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

export { getSettingsToken }; 