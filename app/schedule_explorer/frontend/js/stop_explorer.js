// Import colors
import { colors } from './colors.js';

// Global variables
let map = null;
let stopMarkers = new Map();
let routeLines = [];
let selectedLanguage = 'default';
// Get the current server's URL and port
window.API_BASE_URL = `${window.location.protocol}//${window.location.hostname}:8000`;
const API_BASE_URL = window.API_BASE_URL;

// Function to get a consistent color for a stop ID
function getStopColor(stopId) {
    // Simple hash function
    let hash = 0;
    for (let i = 0; i < stopId.length; i++) {
        hash = ((hash << 5) - hash) + stopId.charCodeAt(i);
        hash = hash & hash; // Convert to 32-bit integer
    }
    // Make sure hash is positive
    hash = Math.abs(hash);
    // Get color from predefined list
    const colorRGB = colors[hash % colors.length];
    return `rgb(${colorRGB[0]}, ${colorRGB[1]}, ${colorRGB[2]})`;
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
        const response = await fetch(`${API_BASE_URL}/stations/search?query=${encodeURIComponent(query)}`);
        const stops = await response.json();

        const resultsDiv = document.getElementById('stopSearchResults');
        resultsDiv.classList.add('show');

        if (stops.length === 0) {
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
    }
}

// Make addStop available globally
window.addStop = addStop;

// Add a stop to the selection
function addStop(stopId, stopName, lat, lon) {
    if (stopMarkers.has(stopId)) {
        return; // Stop already added
    }

    const color = getStopColor(stopId);

    // Add marker to map
    const marker = L.marker([lat, lon], {
        icon: L.divIcon({
            className: 'custom-div-icon',
            html: `<div style="background-color: ${color};" class="marker-pin"></div>`,
            iconSize: [30, 42],
            iconAnchor: [15, 42]
        })
    }).addTo(map);
    stopMarkers.set(stopId, { marker, color, name: stopName });

    // Add to selected stops table
    const table = document.getElementById('selectedStopsTable');
    const row = document.createElement('div');
    row.className = 'selected-stop-row';
    row.id = `stop-row-${stopId}`;
    row.innerHTML = `
        <div class="stop-color-indicator" style="background-color: ${color};"></div>
        <div class="stop-info">
            <div class="stop-name">${stopName}</div>
            <div class="stop-id">${stopId}</div>
        </div>
        <button class="remove-stop" onclick="removeStop('${stopId}')">&times;</button>
    `;
    table.appendChild(row);

    // Update map bounds
    const bounds = L.latLngBounds(Array.from(stopMarkers.values()).map(m => m.marker.getLatLng()));
    map.fitBounds(bounds, { padding: [50, 50] });

    // Hide search results
    document.getElementById('stopSearchResults').classList.remove('show');
    document.getElementById('stopSearch').value = '';

    // Load routes
    loadAllRoutes();
}

// Remove a stop from the selection
function removeStop(stopId) {
    if (!stopMarkers.has(stopId)) {
        return;
    }

    // Remove marker from map
    const { marker } = stopMarkers.get(stopId);
    map.removeLayer(marker);
    stopMarkers.delete(stopId);

    // Remove from table
    const row = document.getElementById(`stop-row-${stopId}`);
    row.remove();

    // Update map bounds if there are still markers
    if (stopMarkers.size > 0) {
        const bounds = L.latLngBounds(Array.from(stopMarkers.values()).map(m => m.marker.getLatLng()));
        map.fitBounds(bounds, { padding: [50, 50] });
    }

    // Reload routes
    loadAllRoutes();
}

// Load routes for all selected stops
async function loadAllRoutes() {
    const routesContainer = document.getElementById('routesContainer');

    if (stopMarkers.size === 0) {
        routesContainer.innerHTML = '<div class="alert alert-info">Select stops to see their routes.</div>';
        return;
    }

    try {
        // Load routes for each stop
        const routePromises = Array.from(stopMarkers.keys()).map(stopId => {
            const stopName = stopMarkers.get(stopId).name || '';
            
            return fetch(`${API_BASE_URL}/stations/${stopId}/routes?language=${selectedLanguage}`)
                .then(response => response.json())
                .then(routes => ({ stopId, stopName, routes }));
        });

        const results = await Promise.all(routePromises);

        // Group routes by stop
        routesContainer.innerHTML = results.map(({ stopId, stopName, routes }) => {
            const { color } = stopMarkers.get(stopId);

            return `
                <div class="stop-routes-group">
                    <div class="stop-routes-header">
                        <div class="d-flex align-items-center">
                            <div class="stop-color-indicator" style="background-color: ${color};"></div>
                            <div class="ms-2">
                                <strong>${stopName}</strong>
                                <div class="text-muted">Stop ID: ${stopId}</div>
                            </div>
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
        showLoading('Loading GTFS data...');
        try {
            const response = await fetch(`${API_BASE_URL}/provider/${provider}`, { method: 'POST' });
            const result = await response.json();

            if (result.status === 'success') {
                document.getElementById('stopSearch').disabled = false;
                showSuccess('GTFS data loaded successfully');
                await loadLanguages();
                // Do initial search after provider is loaded
                await searchStops('ab');
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
        if (stopMarkers.size > 0) {
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
async function loadStopsInView() {
    const bounds = map.getBounds();
    const providerId = providerSelect.value;
    if (!providerId) return;

    try {
        const response = await fetch(
            `${API_BASE_URL}/api/${providerId}/stops/bbox?` + 
            `min_lat=${bounds.getSouth()}&max_lat=${bounds.getNorth()}&` +
            `min_lon=${bounds.getWest()}&max_lon=${bounds.getEast()}`
        );
        
        if (!response.ok) throw new Error('Failed to fetch stops');
        
        const stops = await response.json();
        updateStopsOnMap(stops);
    } catch (error) {
        console.error('Error loading stops:', error);
    }
}

// Update stops displayed on the map
function updateStopsOnMap(stops) {
    // Clear existing markers
    stopMarkers.forEach(marker => map.removeLayer(marker));
    stopMarkers.clear();

    // Add new markers
    stops.forEach(stop => {
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
        popupContent.innerHTML = `
            <h5>${escapeHtml(stop.name)}</h5>
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
            <button class="btn btn-sm btn-primary mt-2" onclick="window.addStop('${stop.id}', '${escapeHtml(stop.name)}', ${stop.location.lat}, ${stop.location.lon})">
                Add to selection
            </button>
        `;

        marker.bindPopup(popupContent);
        marker.addTo(map);
        stopMarkers.set(stop.id, { marker, color, name: stop.name });
    });
}

// Debounce the loadStopsInView function
let debounceTimer = null;
function debounceLoadStops() {
    if (debounceTimer) {
        clearTimeout(debounceTimer);
    }
    debounceTimer = setTimeout(loadStopsInView, 300);
}
