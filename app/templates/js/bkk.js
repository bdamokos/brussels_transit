// BKK-specific utility functions and data handling

// Store BKK configuration
let bkkConfig = null;

// Function to check if BKK provider is enabled
async function isBkkEnabled() {
    try {
        const response = await fetch('/api/bkk/config');
        return response.ok;
    } catch (error) {
        console.log('BKK provider not enabled');
        return false;
    }
}

// Function to fetch BKK configuration
async function fetchBkkConfig() {
    try {
        const response = await fetch('/api/bkk/config');
        if (!response.ok) throw new Error('Failed to fetch BKK config');
        bkkConfig = await response.json();
        
        // Initialize stop IDs set if not already set by server
        if (!transitApp.bkkModule.BKK_STOP_IDS && bkkConfig && bkkConfig.stops) {
            transitApp.bkkModule.BKK_STOP_IDS = new Set(bkkConfig.stops.map(stop => stop.id));
        }
        
        return bkkConfig;
    } catch (error) {
        console.error('Error fetching BKK config:', error);
        return null;
    }
}

// Function to fetch BKK routes
async function fetchBkkRoutes(lines) {
    const routes = {};
    for (const line of lines) {
        try {
            const response = await fetch(`/api/bkk/lines/${line}/route`);
            if (response.ok) {
                routes[line] = await response.json();
                console.log(`Fetched BKK route for line ${line}:`, routes[line]);
            }
        } catch (e) {
            console.error(`Error fetching route for BKK line ${line}:`, e);
        }
    }
    return routes;
}

// Function to fetch BKK line colors
async function fetchBkkColors(lines) {
    const colors = {};
    for (const line of lines) {
        try {
            const response = await fetch(`/api/bkk/lines/${line}/colors`);
            if (response.ok) {
                colors[line] = await response.json();
            }
        } catch (e) {
            console.error(`Error fetching colors for BKK line ${line}:`, e);
        }
    }
    return colors;
}

// Function to fetch BKK data (waiting times, vehicles)
async function fetchBkkData() {
    try {
        const response = await fetch('/api/bkk/data');
        if (!response.ok) throw new Error('Failed to fetch BKK data');
        return await response.json();
    } catch (error) {
        console.error('Error fetching BKK data:', error);
        return {
            stops_data: {},
            messages: [],
            processed_vehicles: []
        };
    }
}

// Function to fetch and process BKK service messages
async function fetchBkkMessages() {
    try {
        const response = await fetch('/api/bkk/messages');
        if (!response.ok) throw new Error('Failed to fetch BKK messages');
        const data = await response.json();
        return processMessages(data);
    } catch (error) {
        console.error('Error fetching BKK messages:', error);
        return [];
    }
}

// Function to process BKK messages
function processMessages(data) {
    if (!data || !data.messages) {
        return [];
    }
    return data.messages;
}

// Function to fetch BKK waiting times
async function fetchBkkWaitingTimes() {
    try {
        const response = await fetch('/api/bkk/waiting_times');
        if (!response.ok) throw new Error('Failed to fetch BKK waiting times');
        return await response.json();
    } catch (error) {
        console.error('Error fetching BKK waiting times:', error);
        return {
            stops: {},
            colors: {}
        };
    }
}

// Initialize BKK module
if (!transitApp.bkkModule.BKK_STOP_IDS) {
    transitApp.bkkModule.BKK_STOP_IDS = new Set();
}

// Export functions and variables for use in main script
Object.assign(transitApp.bkkModule, {
    isBkkEnabled,
    fetchBkkConfig,
    fetchBkkRoutes,
    fetchBkkColors,
    fetchBkkData,
    fetchBkkMessages,
    fetchBkkWaitingTimes,
    processMessages,
    BKK_STOP_IDS: transitApp.bkkModule.BKK_STOP_IDS
}); 