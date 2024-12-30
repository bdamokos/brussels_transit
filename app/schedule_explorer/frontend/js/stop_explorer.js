// Import colors
import { colors } from './colors.js';

// Global variables
let map = null;
let mapMarkers = new Map(); // For all stops visible on the map
let selectedStops = new Map(); // For stops that are selected
let routeLines = [];
let selectedLanguage = 'default';
// Get the current server's URL and port
window.API_BASE_URL = `${window.location.protocol}//${window.location.hostname}:8000`;
const API_BASE_URL = window.API_BASE_URL;

// Function to get a consistent color for a stop ID
function getStopColor(stopId) {
    // More chaotic hash function that spreads consecutive IDs across the color space
    let hash = 0;
    for (let i = 0; i < stopId.length; i++) {
        // Use prime numbers and bit operations for more chaos
        hash = Math.imul(hash ^ stopId.charCodeAt(i), 1597); // Prime number
        hash = hash ^ (hash >>> 7);  // Right shift and XOR
        hash = Math.imul(hash, 367); // Another prime
    }
    // Make sure hash is positive and well-distributed
    hash = Math.abs(hash ^ (hash >>> 16));
    return `rgb(${colors[hash % colors.length].join(', ')})`;
}

// Function to escape HTML special characters
function escapeHtml(unsafe) {
    return unsafe
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#039;");
}

// Backend status handling
const backendStatus = document.getElementById('backendStatus');
const providerSelect = document.getElementById('providerSelect');
const languageSelect = document.getElementById('languageSelect');
const searchInput = document.getElementById('searchInput');

// Function to update backend status
function updateBackendStatus(status, message) {
    backendStatus.className = 'backend-status ' + status;
    backendStatus.querySelector('.status-text').textContent = message;

    // Enable/disable inputs based on status
    const inputs = [searchInput];
    inputs.forEach(input => {
        input.disabled = status !== 'ready';
    });

    // Initialize dropdowns when backend is ready
    if (status === 'ready') {
        setTimeout(() => {
            backendStatus.classList.add('fade-out');
            setTimeout(() => {
                backendStatus.style.display = 'none';
            }, 2000);
        }, 3000);
    }
}

// Initialize the map
function initMap() {
    if (!map) {  // Only initialize if not already initialized
        map = L.map('map').setView([50.8503, 4.3517], 13);  // Brussels center
        L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
            maxZoom: 19,
            attribution: '© OpenStreetMap contributors'
        }).addTo(map);

        // Add locate control
        L.control.locate({
            position: 'topleft',
            strings: {
                title: "Show me where I am"
            }
        }).addTo(map);

        // Add event listeners for map movement
        map.on('moveend', debounceLoadStops);
        map.on('zoomend', debounceLoadStops);
    }
    return map;
}

// Initialize the page
async function init() {
    initMap();
    await loadProviders();
    setupEventListeners();
    // Initial search moved to after provider loading
}

// Function to setup provider selection
export function setupProviderSelection() {
    const providerSelect = document.getElementById('providerSelect');
    const languageSelect = document.getElementById('languageSelect');
    const stopSearch = document.getElementById('stopSearch');
    const backendStatus = document.getElementById('backendStatus');
    const statusText = backendStatus.querySelector('.status-text');

    // Load available providers
    loadProviders();

    // Handle provider selection
    providerSelect.addEventListener('change', async () => {
        const providerId = providerSelect.value;
        if (!providerId) return;

        try {
            // Show loading status
            backendStatus.className = 'backend-status loading';
            statusText.textContent = 'Loading provider data...';

            // Load the provider
            await loadProvider(providerId);

            // Show success status
            backendStatus.className = 'backend-status ready';
            statusText.textContent = 'Provider loaded successfully';

            // Enable language selection and stop search
            languageSelect.disabled = false;
            stopSearch.disabled = false;

            // Load languages
            await loadLanguages();

            // Load initial stops based on current map bounds
            await loadStopsInView();

            // Fade out success message after 2 seconds
            setTimeout(() => {
                backendStatus.classList.add('fade-out');
                setTimeout(() => {
                    backendStatus.style.display = 'none';
                    backendStatus.classList.remove('fade-out');
                }, 2000);
            }, 2000);

        } catch (error) {
            console.error('Error loading provider:', error);
            backendStatus.className = 'backend-status error';
            statusText.textContent = 'Failed to load provider';
        }
    });
}

// Load available providers
async function loadProviders() {
    const providerSelect = document.getElementById('providerSelect');
    const backendStatus = document.getElementById('backendStatus');
    const statusText = backendStatus.querySelector('.status-text');

    try {
        backendStatus.className = 'backend-status loading';
        statusText.textContent = 'Loading providers...';

        const response = await fetch('http://localhost:8000/providers_info');
        if (!response.ok) throw new Error('Failed to fetch providers');
        
        const providers = await response.json();
        
        // Clear existing options except the placeholder
        while (providerSelect.options.length > 1) {
            providerSelect.remove(1);
        }
        
        // Add provider options
        for (const provider of providers) {
            const option = document.createElement('option');
            option.value = provider.id;
            option.textContent = provider.name || provider.id;
            providerSelect.appendChild(option);
        }

        // Enable provider selection
        providerSelect.disabled = false;

        // Show success status briefly
        backendStatus.className = 'backend-status ready';
        statusText.textContent = 'Providers loaded successfully';
        setTimeout(() => {
            backendStatus.classList.add('fade-out');
            setTimeout(() => {
                backendStatus.style.display = 'none';
                backendStatus.classList.remove('fade-out');
            }, 2000);
        }, 2000);

    } catch (error) {
        console.error('Error loading providers:', error);
        backendStatus.className = 'backend-status error';
        statusText.textContent = 'Failed to load providers';
    }
}

// Load a specific provider
async function loadProvider(providerId) {
    const response = await fetch(`http://localhost:8000/provider/${providerId}`, {
        method: 'POST'
    });
    
    if (!response.ok) {
        throw new Error('Failed to load provider');
    }
    
    return response.json();
}

// Search for stops
async function searchStops(query) {
    if (!query) {
        document.getElementById('stopSearchResults').innerHTML = '';
        return;
    }

    try {
        const response = await fetch(`${API_BASE_URL}/stations/search?query=${encodeURIComponent(query)}&provider_id=${providerSelect.value}`);
        const stops = await response.json();
        
        const resultsDiv = document.getElementById('stopSearchResults');
        resultsDiv.classList.add('show');

        if (!Array.isArray(stops) || stops.length === 0) {
            resultsDiv.innerHTML = '<div class="search-result-item">No stops found</div>';
            return;
        }

        resultsDiv.innerHTML = stops.map(stop => `
            <div class="search-result-item" onclick="window.addStop('${stop.id}', '${escapeHtml(stop.name)}', ${stop.location.lat}, ${stop.location.lon})">
                <div class="stop-name">${escapeHtml(stop.name)}</div>
                <small class="text-muted">${stop.id}</small>
            </div>
        `).join('');
    } catch (error) {
        console.error('Error searching stops:', error);
        const resultsDiv = document.getElementById('stopSearchResults');
        resultsDiv.classList.add('show');
        resultsDiv.innerHTML = '<div class="search-result-item text-danger">Error searching stops</div>';
    }
}

// Make addStop available globally
window.addStop = addStop;

// Add a stop to the selection
function addStop(stopId, stopName, lat, lon) {
    if (selectedStops.has(stopId)) {
        return; // Stop already added
    }

    const color = getStopColor(stopId);

    // Remove from map markers if it exists
    if (mapMarkers.has(stopId)) {
        const { marker } = mapMarkers.get(stopId);
        map.removeLayer(marker);
        mapMarkers.delete(stopId);
    }

    // Add marker to map for the selected stop
    const marker = L.marker([lat, lon], {
        icon: L.divIcon({
            className: 'custom-div-icon',
            html: `<div style="background-color: ${color};" class="marker-pin"></div>`,
            iconSize: [30, 42],
            iconAnchor: [15, 42]
        })
    }).addTo(map);
    selectedStops.set(stopId, { marker, color, name: stopName });

    // Update map bounds to include all selected stops
    const bounds = L.latLngBounds(Array.from(selectedStops.values()).map(m => m.marker.getLatLng()));
    map.fitBounds(bounds, { padding: [50, 50] });

    // Hide search results
    document.getElementById('stopSearchResults').classList.remove('show');
    document.getElementById('stopSearch').value = '';

    // Load routes
    loadAllRoutes();
}

// Remove a stop from the selection
function removeStop(stopId) {
    const { marker } = selectedStops.get(stopId);
    map.removeLayer(marker);
    selectedStops.delete(stopId);
    loadAllRoutes();
    
    // Refresh map markers to show the removed stop if it's in the current view
    loadStopsInView();
}

// Load routes for all selected stops
async function loadAllRoutes() {
    const routesContainer = document.getElementById('routesContainer');

    if (selectedStops.size === 0) {
        routesContainer.innerHTML = '<div class="alert alert-info">Select stops to see their routes.</div>';
        return;
    }

    try {
        // Get routes for each stop, reusing data if available
        const results = Array.from(selectedStops.entries()).map(([stopId, stopData]) => {
            return {
                stopId,
                stopName: stopData.name,
                routes: stopData.routes || [] // Use existing routes if available
            };
        });

        // Only fetch routes if we don't have them yet
        const fetchPromises = results.map(async (result) => {
            if (result.routes.length === 0) {
                try {
                    const response = await fetch(`${API_BASE_URL}/stations/${result.stopId}/routes?language=${selectedLanguage}`);
                    result.routes = await response.json();
                    // Store the routes in the selectedStops Map for future use
                    selectedStops.get(result.stopId).routes = result.routes;
                } catch (error) {
                    console.error(`Error fetching routes for stop ${result.stopId}:`, error);
                    result.routes = [];
                }
            }
            return result;
        });

        await Promise.all(fetchPromises);

        // Group routes by stop
        routesContainer.innerHTML = results.map(({ stopId, stopName, routes }) => {
            const { color } = selectedStops.get(stopId);

            return `
                <div class="stop-routes-group">
                    <div class="stop-routes-header">
                        <div class="d-flex align-items-center justify-content-between">
                            <div class="d-flex align-items-center">
                                <div class="stop-color-indicator" style="background-color: ${color};"></div>
                                <div class="ms-2">
                                    <strong>${stopName}</strong>
                                    <div class="d-flex align-items-center">
                                        <span class="text-muted">Stop ID: ${stopId}</span>
                                        <button class="copy-button ms-2" onclick="copyToClipboard('${stopId}')" title="Copy stop ID">
                                            📋
                                        </button>
                                    </div>
                                </div>
                            </div>
                            <button class="btn btn-sm btn-outline-danger" onclick="removeStop('${stopId}')">Remove</button>
                        </div>
                    </div>
                    <div class="stop-routes-content">
                        ${routes.length === 0 ?
                            '<div class="p-3">No routes found for this stop.</div>' :
                            routes.map(route => `
                                <div class="route-line" style="border-left-color: #${route.color || '000000'}">
                                    <div class="d-flex align-items-start">
                                        <div class="route-badge" style="background-color: #${route.color || '6c757d'}">
                                            ${route.short_name || route.route_id}
                                            <button class="copy-button ms-1" onclick="copyToClipboard('${route.route_id}')" title="Copy route ID">
                                                📋
                                            </button>
                                        </div>
                                        <div class="ms-3">
                                            <div class="fw-bold">${route.headsign || route.last_stop}</div>
                                            <div class="text-muted">
                                                ${route.route_name}<br>
                                                From: ${route.first_stop}<br>
                                                To: ${route.last_stop}<br>
                                                Service days: ${route.service_days.map(day =>
                                                    day.charAt(0).toUpperCase() + day.slice(1)
                                                ).join(', ')}
                                            </div>
                                            <div class="mt-2">
                                                <a href="${API_BASE_URL}/api/${providerSelect.value}/stops/${stopId}/waiting_times?route_id=${route.route_id}&limit=10"
                                                   target="_blank" class="btn btn-sm btn-outline-primary me-2">
                                                    View waiting times (json)
                                                </a>
                                                <a href="index.html?from=${stopId}&to=${route.terminus_stop_id}&provider=${providerSelect.value}&condensed_view=true&show_stop_ids=true"
                                                   target="_blank" class="btn btn-sm btn-outline-secondary">
                                                    View full route
                                                </a>
                                            </div>
                                        </div>
                                    </div>
                                </div>
                            `).join('')
                        }
                    </div>
                </div>
            `;
        }).join('');

    } catch (error) {
        console.error('Error loading routes:', error);
        routesContainer.innerHTML = '<div class="alert alert-danger">Failed to load routes.</div>';
    }
}

// Function to generate distinct colors
function generateDistinctColors(count) {
    // Generate a palette of RGB colors
    const colors = [];
    for (let r = 0; r <= 255; r += 32) {
        for (let g = 0; g <= 255; g += 32) {
            for (let b = 0; b <= 255; b += 32) {
                colors.push([r, g, b]);
            }
        }
    }

    // Use simulated annealing to select distinct colors
    const result = simulatedAnnealing(colors, count);
    return result.colors.map(rgb => rgbToHex(rgb));
}

// Setup event listeners
function setupEventListeners() {
    // Provider selection
    document.getElementById('providerSelect').addEventListener('change', async (e) => {
        const provider = e.target.value;
        try {
            const response = await fetch(`${API_BASE_URL}/provider/${provider}`, { method: 'POST' });
            const result = await response.json();

            if (result.status === 'success') {
                document.getElementById('stopSearch').disabled = false;
                await loadLanguages();
                // Load initial stops in current view
                await loadStopsInView(true);
            } else {
                showError('Failed to load GTFS data');
            }
        } catch (error) {
            console.error('Error loading provider:', error);
            showError('Failed to load GTFS data');
        }
    });

    // Language selection
    document.getElementById('languageSelect').addEventListener('change', (e) => {
        selectedLanguage = e.target.value;
        if (selectedStops.size > 0) {
            loadAllRoutes();
        }
    });

    // Stop search
    let searchTimeout;
    document.getElementById('stopSearch').addEventListener('input', (e) => {
        clearTimeout(searchTimeout);
        searchTimeout = setTimeout(() => searchStops(e.target.value), 300);
    });

    // Close search results when clicking outside
    document.addEventListener('click', (e) => {
        const searchResults = document.getElementById('stopSearchResults');
        const searchInput = document.getElementById('stopSearch');
        if (!searchResults.contains(e.target) && e.target !== searchInput) {
            searchResults.classList.remove('show');
        }
    });

    // Show/hide unselected stops checkbox
    document.getElementById('showUnselectedStops').addEventListener('change', () => {
        loadStopsInView();
    });
}

// Status indicator functions
function showLoading(message) {
    const status = document.getElementById('backendStatus');
    status.className = 'backend-status loading';
    status.querySelector('.status-text').textContent = message;
}

function showError(message) {
    const status = document.getElementById('backendStatus');
    status.className = 'backend-status error';
    status.querySelector('.status-text').textContent = message;
}

function showSuccess(message) {
    const status = document.getElementById('backendStatus');
    status.className = 'backend-status ready';
    status.querySelector('.status-text').textContent = message;
    setTimeout(() => {
        status.classList.add('fade-out');
        setTimeout(() => {
            status.className = 'backend-status';
        }, 2000);
    }, 2000);
}

// Load available languages
async function loadLanguages() {
    try {
        // Get a sample of stations to detect available languages
        const response = await fetch(`${API_BASE_URL}/stations/search?query=ab`);
        const data = await response.json();

        // Extract unique languages from station translations
        const languages = new Set();

        // Add default language
        languages.add('default');

        // Check if we have stations and they have translations
        if (Array.isArray(data)) {
            data.forEach(station => {
                if (station.translations) {
                    Object.keys(station.translations).forEach(lang => languages.add(lang));
                }
            });
        }

        const select = document.getElementById('languageSelect');
        select.innerHTML = Array.from(languages).sort().map(lang =>
            lang === 'default'
                ? '<option value="default">Default (Original)</option>'
                : `<option value="${lang}">${lang.toUpperCase()}</option>`
        ).join('');

        // Enable the select and set default
        select.disabled = false;
        selectedLanguage = 'default';
    } catch (error) {
        console.error('Error loading languages:', error);
        // If there's an error, just show default language
        const select = document.getElementById('languageSelect');
        select.innerHTML = '<option value="default">Default (Original)</option>';
        select.disabled = false;
        selectedLanguage = 'default';
    }
}

// Initialize when the page loads
document.addEventListener('DOMContentLoaded', init);

// Make functions available globally
window.addStop = addStop;
window.removeStop = removeStop;

// Load stops in current map view
async function loadStopsInView(initialLoad = false) {
    const bounds = map.getBounds();
    const providerId = providerSelect.value;
    if (!providerId) return;

    try {
        // Show loading indicator for initial load
        if (initialLoad) {
            showLoading('Loading stops...');
        }

        // First, quickly load a limited number of stops
        const response = await fetch(
            `${API_BASE_URL}/api/${providerId}/stops/bbox?` + 
            `min_lat=${bounds.getSouth()}&max_lat=${bounds.getNorth()}&` +
            `min_lon=${bounds.getWest()}&max_lon=${bounds.getEast()}` +
            (initialLoad ? '&limit=10' : '')
        );
        
        if (!response.ok) throw new Error('Failed to fetch stops');
        
        const stops = await response.json();
        updateStopsOnMap(stops);

        // If this was the initial load with limit, load all stops
        if (initialLoad && stops.length === 10) {  // If we got exactly 10 stops, there might be more
            const fullResponse = await fetch(
                `${API_BASE_URL}/api/${providerId}/stops/bbox?` + 
                `min_lat=${bounds.getSouth()}&max_lat=${bounds.getNorth()}&` +
                `min_lon=${bounds.getWest()}&max_lon=${bounds.getEast()}`
            );
            
            if (!fullResponse.ok) throw new Error('Failed to fetch all stops');
            
            const allStops = await fullResponse.json();
            updateStopsOnMap(allStops);
        }

        if (initialLoad) {
            showSuccess('Stops loaded successfully');
        }
    } catch (error) {
        console.error('Error loading stops:', error);
        if (initialLoad) {
            showError('Failed to load stops');
        }
    }
}

// Debounce the loadStopsInView function
let debounceTimer = null;
function debounceLoadStops() {
    if (debounceTimer) {
        clearTimeout(debounceTimer);
    }
    debounceTimer = setTimeout(() => loadStopsInView(false), 300);
}

// Function to copy text to clipboard
async function copyToClipboard(text) {
    try {
        await navigator.clipboard.writeText(text);
    } catch (err) {
        console.error('Failed to copy text:', err);
    }
}

// Make copy function available globally
window.copyToClipboard = copyToClipboard;

// Update stops displayed on the map
function updateStopsOnMap(stops) {
    // Clear existing markers
    mapMarkers.forEach(marker => map.removeLayer(marker));
    mapMarkers.clear();

    // Check if we should show unselected stops
    const showUnselected = document.getElementById('showUnselectedStops').checked;
    if (!showUnselected) return;

    // Add new markers
    stops.forEach(stop => {
        // Skip if this stop is already selected
        if (selectedStops.has(stop.id)) return;

        const color = getStopColor(stop.id);

        const marker = L.marker([stop.location.lat, stop.location.lon], {
            icon: L.divIcon({
                className: 'custom-div-icon',
                html: `<div style="background-color: ${color};" class="marker-pin"></div>`,
                iconSize: [30, 42],
                iconAnchor: [15, 42]
            })
        });

        // Create popup content
        const popupContent = document.createElement('div');
        popupContent.className = 'stop-popup';
        
        // Create the content elements
        const content = document.createElement('div');
        content.innerHTML = `
            <div class="d-flex justify-content-between align-items-start">
                <h5>${escapeHtml(stop.name)}</h5>
                <button class="copy-button" onclick="copyToClipboard('${stop.id}')" title="Copy stop ID">
                    📋
                </button>
            </div>
            <div class="stop-id">${stop.id}</div>
            ${stop.routes ? `
                <div class="routes-list">
                    <h6>Routes:</h6>
                    ${stop.routes.map(route => `
                        <div class="route-item" style="border-left-color: #${route.color || '000000'}">
                            <span class="route-badge" style="background-color: #${route.color || '6c757d'}">
                                ${route.short_name || route.route_id}
                            </span>
                            <span class="route-name">${route.route_name}</span>
                        </div>
                    `).join('')}
                </div>
            ` : ''}
        `;
        popupContent.appendChild(content);

        // Create and append the button with a direct event listener
        const addButton = document.createElement('button');
        addButton.className = 'btn btn-sm btn-primary mt-2';
        addButton.textContent = 'Add to selection';
        addButton.addEventListener('click', () => {
            addStop(stop.id, stop.name, stop.location.lat, stop.location.lon);
            marker.closePopup();
        });
        popupContent.appendChild(addButton);

        marker.bindPopup(popupContent);
        marker.addTo(map);
        mapMarkers.set(stop.id, { marker, color, name: stop.name });
    });
}
