// messages.js - Handles service message display and updates

import { getLineColor } from '../utils.js';

/**
 * Updates the service messages displayed on the UI.
 * @param {Object} messages - The combined service messages data.
 */
export function updateServiceMessages(messages) {
    const primaryContainer = document.getElementById('primary-messages-container');
    const secondaryContainer = document.getElementById('secondary-messages-container');
    
    if (!messages || !messages.messages) {
        primaryContainer.innerHTML = '';
        secondaryContainer.innerHTML = '';
        return;
    }
    
    const primaryMessages = messages.messages.filter(m => m.is_monitored);
    const secondaryMessages = messages.messages.filter(m => !m.is_monitored);
    
    // Make this function async and await the renderMessages
    (async () => {
        // Update primary messages
        if (primaryMessages.length > 0) {
            primaryContainer.innerHTML = `
                <div class="primary-messages">
                    <h2>Important Service Messages</h2>
                    ${await renderMessages(primaryMessages, false)}
                </div>`;
        } else {
            primaryContainer.innerHTML = '';
        }
        
        // Update secondary messages
        if (secondaryMessages.length > 0) {
            secondaryContainer.innerHTML = `
                <div class="secondary-messages">
                    <h2>Other Service Messages</h2>
                    ${await renderMessages(secondaryMessages, true)}
                </div>`;
        } else {
            secondaryContainer.innerHTML = '';
        }
    })();
}

/**
 * Renders the service messages into HTML.
 * @param {Array} messages - Array of message objects.
 * @param {boolean} isSecondary - Flag to determine message type.
 * @returns {string} - HTML string of rendered messages.
 */
export async function renderMessages(messages, isSecondary) {
    const messageElements = messages.map(message => {
        console.log('Message object:', message);

        const title = message.title || '';
        const text = message.text || message.description || '';
        const messageContent = title ? `<strong>${title}</strong><br>${text}` : text;

        // Get the lines array
        const lines = message.lines || message.affected_lines || [];
        
        // Render affected lines with proper styling
        const lineElements = lines.map(line => {
            const colorStyle = getLineColor(line);
            return `
                <span class="line-number" style="${colorStyle}">
                    ${line}
                </span>
            `;
        }).join('');

        // Rest of the message rendering...
        const stops = message.stops ? message.stops.join(', ') : 
                     message.affected_stops ? message.affected_stops.map(stop => stop.name).join(', ') : '';

        return `
            <div class="message ${isSecondary ? 'secondary' : ''}">
                ${messageContent}
                <div class="affected-details">
                    <div class="affected-lines">
                        Lines: ${lineElements}
                    </div>
                    ${stops ? `
                        <div class="affected-stops">
                            Stops: ${stops}
                        </div>
                    ` : ''}
                </div>
            </div>
        `;
    });

    return messageElements.join('');
} 