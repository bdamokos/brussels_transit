import { TransitProvider } from '/js/core/provider.js';
import { colors } from './colors.js';
import { formatLineNumber, formatDestination, formatWaitingTime, formatStopName, formatMessage } from './formatters.js';

/**
 * STIB Transit Provider
 * Interfaces with our backend API endpoints to provide STIB transit data
 */
export class STIBProvider extends TransitProvider {
    constructor(providerInfo) {
        super('stib');
        this.displayName = 'STIB-MIVB';
        this.region = 'be';
        this.settings = null;
    }

    async isEnabled() {
        if (this.settings) return true;

        try {
            const response = await fetch('/api/settings', {
                headers: {
                    'X-Settings-Token': await getSettingsToken()
                }
            });
            if (!response.ok) return false;
            
            this.settings = await response.json();
            return this.settings.providers.includes('stib');
        } catch (error) {
            console.error('Error checking if STIB is enabled:', error);
            return false;
        }
    }

    async getConfig() {
        const response = await fetch('/api/stib/config');
        if (!response.ok) throw new Error('Failed to get STIB config');
        return await response.json();
    }

    async getStops() {
        const response = await fetch('/api/stib/stops');
        if (!response.ok) throw new Error('Failed to get STIB stops');
        return await response.json();
    }

    async getWaitingTimes(stopId) {
        const response = await fetch(`/api/stib/waiting_times/${stopId}`);
        if (!response.ok) throw new Error('Failed to get STIB waiting times');
        return await response.json();
    }

    async getVehicles() {
        const response = await fetch('/api/stib/vehicles');
        if (!response.ok) throw new Error('Failed to get STIB vehicles');
        return await response.json();
    }

    async getMessages() {
        const response = await fetch('/api/stib/messages');
        if (!response.ok) throw new Error('Failed to get STIB messages');
        return await response.json();
    }

    async getRoutes() {
        const response = await fetch('/api/stib/routes');
        if (!response.ok) throw new Error('Failed to get STIB routes');
        return await response.json();
    }

    getColors() {
        return colors;
    }

    customizeStopDisplay(stop, element) {
        // Add STIB-specific styling to stop markers
        element.classList.add('stib-stop-marker');
        
        // Format the stop name
        const nameElement = element.querySelector('.stop-name');
        if (nameElement) {
            nameElement.textContent = formatStopName(nameElement.textContent);
        }

        // Format waiting times
        const timeElements = element.querySelectorAll('.waiting-time');
        timeElements.forEach(el => {
            const minutes = parseInt(el.dataset.minutes);
            el.textContent = formatWaitingTime(minutes);
            el.classList.add('stib-waiting-time');
        });

        // Add line badges
        const lineElements = element.querySelectorAll('.line-number');
        lineElements.forEach(el => {
            const lineId = el.textContent;
            el.textContent = formatLineNumber(lineId);
            el.classList.add('stib-line-badge');
            el.style.backgroundColor = colors.lines[lineId] || '#666';
        });
    }

    customizeMessageDisplay(message, element) {
        // Add STIB-specific styling to messages
        element.classList.add('stib-message');
        
        if (message.severity) {
            element.classList.add(`stib-message-${message.severity.toLowerCase()}`);
        }

        // Format the message text
        element.textContent = formatMessage(message);
    }
}