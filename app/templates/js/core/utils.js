/**
 * Utility functions for the transit display system
 */

// List of words that should remain uppercase
const UPPERCASE_WORDS = new Set(['uz', 'vub', 'ulb']);

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
    const seconds = meters / WALKING_SPEED;
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

/**
 * Get a settings token from the server
 * @returns {Promise<string|null>} - The token or null if failed
 */
export async function getSettingsToken() {
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