/**
 * Base transit provider interface
 * All transit providers must extend this class and implement its methods
 */
export class TransitProvider {
    /**
     * Create a new transit provider from provider info
     * @param {Object} providerInfo - Provider information from the server
     */
    constructor(name) {
        this.name = name;
    }

    /**
     * Check if this provider is enabled in configuration
     * @returns {Promise<boolean>}
     */
    async isEnabled() {
        throw new Error('isEnabled() must be implemented');
    }

    /**
     * Get provider configuration
     * @returns {Promise<Object>}
     */
    async getConfig() {
        throw new Error('getConfig() must be implemented');
    }

    /**
     * Get list of stops
     * @returns {Promise<Object>} Dictionary of stop data
     */
    async getStops() {
        throw new Error('getStops() must be implemented');
    }

    /**
     * Get real-time waiting times
     * @param {string} _stopId - ID of the stop to get waiting times for
     * @returns {Promise<Object>} Dictionary of waiting times by stop
     */
    // eslint-disable-next-line no-unused-vars
    async getWaitingTimes(_stopId) {
        throw new Error('getWaitingTimes() must be implemented');
    }

    /**
     * Get vehicle positions
     * @returns {Promise<Array>} List of vehicle positions
     */
    async getVehicles() {
        throw new Error('getVehicles() must be implemented');
    }

    /**
     * Get service messages
     * @returns {Promise<Array>} List of service messages
     */
    async getMessages() {
        throw new Error('getMessages() must be implemented');
    }

    /**
     * Get route shapes
     * @returns {Promise<Object>} Dictionary of route shapes
     */
    async getRoutes() {
        throw new Error('getRoutes() must be implemented');
    }

    /**
     * Get provider-specific colors
     * @returns {Promise<Object>} Dictionary of colors by line
     */
    getColors() {
        return {
            primary: '#000000',
            secondary: '#FFFFFF'
        };
    }

    /**
     * Customize stop display
     * @param {HTMLElement} element - Stop element
     * @param {Object} _stopData - Stop data
     * @returns {boolean} True if custom display was used
     */
    // eslint-disable-next-line no-unused-vars
    customizeStopDisplay(element, _stopData) {
        // Default implementation does nothing
        return element;
    }

    /**
     * Customize message display
     * @param {HTMLElement} element - Message element
     * @param {Object} _messageData - Message data
     * @returns {boolean} True if custom display was used
     */
    // eslint-disable-next-line no-unused-vars
    customizeMessageDisplay(element, _messageData) {
        // Default implementation does nothing
        return element;
    }
} 