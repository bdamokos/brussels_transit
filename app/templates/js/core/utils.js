/**
 * Utility functions for the transit display system
 */

// List of words that should remain uppercase
const UPPERCASE_WORDS = new Set(['uz', 'vub', 'ulb']);

// Settings constants with defaults
export const settings = {
    WALKING_SPEED: 1.4,  // m/s
    REFRESH_INTERVAL: 30000,  // ms
    LOCATION_UPDATE_INTERVAL: 10000,  // ms
    map_config: {
        center: { lat: 50.8465, lon: 4.3517 },  // Brussels default
        zoom: 13
    },
    lineColors: {}  // Will be populated from provider data
};

/**
 * Update settings from server response
 * @param {Object} serverSettings - Settings from server
 */
export function updateSettings(serverSettings) {
    Object.assign(settings, {
        WALKING_SPEED: serverSettings.walking_speed || settings.WALKING_SPEED,
        REFRESH_INTERVAL: (serverSettings.refresh_interval || 30) * 1000,
        LOCATION_UPDATE_INTERVAL: (serverSettings.location_update_interval || 10) * 1000,
        map_config: serverSettings.map_config || settings.map_config
    });
}

/**
 * Format a title with proper capitalization rules
 * @param {string} text - The text to format
 * @returns {string} - The formatted text
 */
export function properTitle(text) {
    // Handle undefined, null, or non-string input
    if (!text) {
        return '';
    }
    
    // Convert to string if it isn't already
    text = String(text);
    
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
                p && UPPERCASE_WORDS.has(p.toLowerCase()) ? 
                    p.toUpperCase() : 
                    p ? p.charAt(0).toUpperCase() + p.slice(1).toLowerCase() : ''
            ).join('.');
        } else if (UPPERCASE_WORDS.has(word)) {
            return word.toUpperCase();
        } else {
            return word.charAt(0).toUpperCase() + word.slice(1);
        }
    }).filter(Boolean).join(' ') || 'Unknown';  // Return 'Unknown' if result is empty
}

/**
 * Calculate walking time based on distance
 * @param {number} meters - Distance in meters
 * @returns {number} - Walking time in minutes
 */
export function calculateWalkingTime(meters) {
    const seconds = meters / settings.WALKING_SPEED;
    return Math.round(seconds / 60);
}

/**
 * Format distance in a human-readable way
 * @param {number} meters - Distance in meters
 * @returns {string} - Formatted distance
 */
export function formatDistance(meters) {
    if (meters < 1000) {
        return `${Math.round(meters)}m`;
    }
    return `${(meters / 1000).toFixed(1)}km`;
}

// Replace localStorage with a session variable
let _currentToken = null;

/**
 * Get a settings token from the server
 * @returns {Promise<string|null>} - The token or null if failed
 */
export async function getSettingsToken() {
    try {
        // If we already have a token for this session, use it
        if (_currentToken) {
            return _currentToken;
        }

        // If not, request a new one
        const response = await fetch('/api/auth/token');
        if (!response.ok) {
            throw new Error(`Failed to get token: ${response.status}`);
        }
        const data = await response.json();
        
        // Store token for this session only
        _currentToken = data.token;
        return _currentToken;
    } catch (error) {
        console.error('Error getting settings token:', error);
        return null;
    }
}

/**
 * Fetch application settings from the server
 * @returns {Promise<object|null>} - The settings object or null if failed
 */
export async function getSettings() {
    try {
        const token = await getSettingsToken();
        if (!token) throw new Error('No token available');

        const response = await fetch('/api/settings', {
            headers: {
                'X-Settings-Token': token
            }
        });
        if (!response.ok) throw new Error('Failed to get settings');
        return await response.json();
    } catch (error) {
        console.error('Error fetching settings:', error);
        return null;
    }
}

/**
 * Check if geolocation is available
 * @returns {boolean} True if geolocation is available
 */
export function isGeolocationAvailable() {
    return 'geolocation' in navigator && 
           (window.isSecureContext || location.protocol === 'https:' || location.hostname === 'localhost');
}

/**
 * Handle and display an error
 * @param {string} message - Error message
 * @param {Error} error - Error object
 */
export function handleError(message, error) {
    console.error(`${message}:`, error);
    const errorsContainer = document.getElementById('errors-container');
    if (errorsContainer) {
        errorsContainer.innerHTML = `
            <div class="error-message">
                ${message}: ${error.message}
            </div>
        `;
    }
}

/**
 * utils.js - Shared utility functions and configurations
 */

export const lineColors = {};

/**
 * Returns the CSS style string for a given line based on its color.
 * Providers can override or extend this function for custom styling.
 * @param {string} line - The line identifier.
 * @returns {string} - CSS style string.
 */
export function getLineColor(line) {
    // Check if a custom color handler exists for the line
    if (lineColors[line]) {
        // If lineColors[line] is an object, assume it contains detailed styling
        if (typeof lineColors[line] === 'object') {
            return `
                --text-color: ${lineColors[line].text};
                --bg-color: ${lineColors[line].background};
                --text-border-color: ${lineColors[line].text_border};
                --bg-border-color: ${lineColors[line].background_border};
            `;
        }
        // If lineColors[line] is a string, use it as the background color
        // Calculate contrasting text color based on background color brightness
        const bgColor = lineColors[line];
        const rgb = bgColor.match(/^#?([a-f\d]{2})([a-f\d]{2})([a-f\d]{2})$/i);
        if (rgb) {
            const r = parseInt(rgb[1], 16);
            const g = parseInt(rgb[2], 16);
            const b = parseInt(rgb[3], 16);
            // Calculate relative luminance using W3C formula
            const luminance = (0.299 * r + 0.587 * g + 0.114 * b) / 255;
            const textColor = luminance > 0.5 ? 'black' : 'white';
            return `background-color: ${bgColor}; --text-color: ${textColor};`;
        }
        return `background-color: ${bgColor}; --text-color: white;`;
    }
    // Fallback to default color
    return `background-color: #666; --text-color: white;`;
}

/**
 * Add this to the existing exports in utils.js
 * @param {Object} coord - The coordinate object to check
 * @returns {boolean} True if the coordinate is valid
 */
export function isValidCoordinate(coord) {
    return coord && 
           !isNaN(coord.lat) && 
           !isNaN(coord.lon) &&
           coord.lat >= -90 && 
           coord.lat <= 90 &&
           coord.lon >= -180 && 
           coord.lon <= 180;
}