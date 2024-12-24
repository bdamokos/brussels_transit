// messages.js - Handles service message display and updates

import { settings } from './utils.js';

/**
 * Updates the service messages displayed on the UI.
 * @param {Object} messages - The combined service messages data.
 */
export function updateServiceMessages(messages) {
    const primaryContainer = document.getElementById('primary-messages-container');
    const secondaryContainer = document.getElementById('secondary-messages-container');
    
    if (!messages || !Array.isArray(messages)) {
        primaryContainer.innerHTML = '';
        secondaryContainer.innerHTML = '';
        return;
    }
    
    // Filter messages for monitored lines
    const primaryMessages = messages.filter(m => m.is_monitored);
    const secondaryMessages = messages.filter(m => !m.is_monitored);
    
    // Update primary messages
    if (primaryMessages.length > 0) {
        primaryContainer.innerHTML = `
            <div class="primary-messages">
                ${renderMessages(primaryMessages, false)}
            </div>`;
    } else {
        primaryContainer.innerHTML = '';
    }
    
    // Update secondary messages
    if (secondaryMessages.length > 0) {
        secondaryContainer.innerHTML = `
            <div class="secondary-messages">
                ${renderMessages(secondaryMessages, true)}
            </div>`;
    } else {
        secondaryContainer.innerHTML = '';
    }
}

/**
 * Renders the service messages into HTML.
 * @param {Array} messages - Array of message objects.
 * @param {boolean} isSecondary - Flag to determine message type.
 * @returns {string} - HTML string of rendered messages.
 */
function renderMessages(messages, isSecondary) {
    return messages.map(message => {
        const title = message.title?.fr || message.title?.nl || '';
        const content = message.content?.fr || message.content?.nl || '';
        
        // Get affected lines and stops
        const lines = message.lines || [];
        const stops = message.stops || message.points || [];  // Use stop names if available, fall back to IDs
        
        return `
            <div class="message ${isSecondary ? 'secondary' : ''}">
                ${title ? `<strong>${title}</strong><br>` : ''}
                ${content}
                ${lines.length > 0 ? `
                    <div class="affected-lines">
                        Lines: ${lines.map(line => {
                            const color = settings.lineColors[line] || '#666';
                            return `<span class="line-number" style="background-color: ${color}; color: white;">
                                ${line}
                            </span>`;
                        }).join('')}
                    </div>
                ` : ''}
                ${stops.length > 0 ? `
                    <div class="affected-stops">
                        Stops: ${stops.join(', ')}
                    </div>
                ` : ''}
            </div>
        `;
    }).join('\n');
} 