/**
 * Utility functions for transit display
 */

/**
 * Format a title with proper capitalization rules
 * @param {string} text - The text to format
 * @returns {string} Properly formatted title
 */
export function properTitle(text) {
    if (!text) {
        return '';
    }
    
    text = String(text);
    const uppercaseWords = new Set(['uz', 'vub', 'ulb']);
    const words = text.toLowerCase().replace('-', ' - ').split(' ');
    
    return words.map(word => {
        if (!word) return '';
        
        if (word.includes('.')) {
            const parts = word.split('.');
            return parts.map(p => 
                p && uppercaseWords.has(p.toLowerCase()) ? 
                    p.toUpperCase() : 
                    p ? p.charAt(0).toUpperCase() + p.slice(1).toLowerCase() : ''
            ).join('.');
        } else if (uppercaseWords.has(word)) {
            return word.toUpperCase();
        } else {
            return word.charAt(0).toUpperCase() + word.slice(1);
        }
    }).filter(Boolean).join(' ') || 'Unknown';
}

/**
 * Calculate walking time based on distance
 * @param {number} meters - Distance in meters
 * @returns {number} Walking time in minutes
 */
export function calculateWalkingTime(meters) {
    const seconds = meters / WALKING_SPEED;
    return Math.round(seconds / 60);
}

/**
 * Format distance for display
 * @param {number} meters - Distance in meters
 * @returns {string} Formatted distance string
 */
export function formatDistance(meters) {
    if (meters < 1000) {
        return `${Math.round(meters)}m`;
    }
    return `${(meters / 1000).toFixed(1)}km`;
}

/**
 * Log an error and display it to the user
 * @param {string} message - Error message
 * @param {Error} [error] - Optional error object
 */
export function handleError(message, error = null) {
    console.error(message, error);
    const errorsContainer = document.getElementById('errors-container');
    if (errorsContainer) {
        errorsContainer.innerHTML = `
            <div class="error-section">
                <div class="error-message">
                    ${message}
                    ${error ? `<br>${error.message}` : ''}
                </div>
            </div>
        `;
    }
}

/**
 * Check if geolocation is available in this context
 * @returns {boolean} Whether geolocation is available
 */
export function isGeolocationAvailable() {
    return 'geolocation' in navigator && 
           (window.isSecureContext || location.protocol === 'https:' || location.hostname === 'localhost');
} 