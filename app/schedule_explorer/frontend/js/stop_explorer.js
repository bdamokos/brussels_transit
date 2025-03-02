// Import colors
import { colors } from './colors.js';

// Global variables
let map = null;
let mapMarkers = new Map(); // For all stops visible on the map
let selectedStops = new Map(); // For stops that are selected
let routeLines = [];
let selectedLanguage = 'default';
let providers = []; // Store providers data globally

// Use the API URL injected from the environment
const API_BASE_URL = window.API_BASE_URL;
console.log('Stop Explorer Frontend starting...');
console.log('API Base URL:', API_BASE_URL);

// Track the last loaded bounds
let lastLoadedBounds = null;

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
    setupProviderSelection();  // This will also load providers
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

            // Clear existing markers and selected stops
            mapMarkers.forEach(({ marker }) => map.removeLayer(marker));
            mapMarkers.clear();
            selectedStops.forEach(({ marker }) => map.removeLayer(marker));
            selectedStops.clear();

            // Find the provider's bounding box
            const provider = providers.find(p => p.raw_id === providerId);
            console.log('Selected provider:', provider);  // Debug log
            if (provider?.bounding_box) {
                console.log('Found bounding box:', provider.bounding_box);  // Debug log
                
                // Create a Leaflet bounds object from the bounding box
                // Note: Leaflet uses [lat, lon] order
                const bounds = L.latLngBounds(
                    [provider.bounding_box.min_lat, provider.bounding_box.min_lon],
                    [provider.bounding_box.max_lat, provider.bounding_box.max_lon]
                );
                console.log('Created bounds:', bounds);  // Debug log
                
                // Fit the map to the bounds with some padding
                map.fitBounds(bounds, {
                    padding: [50, 50],  // Add 50px padding on all sides
                    maxZoom: 13  // Don't zoom in too far
                });
            } else {
                console.log('No bounding box found for provider:', providerId);  // Debug log
            }

            // Show success status
            backendStatus.className = 'backend-status ready';
            statusText.textContent = 'Provider loaded successfully';

            // Enable language selection and stop search
            languageSelect.disabled = false;
            stopSearch.disabled = false;

            // Load languages
            await loadLanguages();

            // Load initial stops based on current map bounds
            await loadStopsInView(true);

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
        // Start loading providers immediately
        const response = await fetch(`${API_BASE_URL}/providers_info`);
        if (!response.ok) throw new Error('Failed to fetch providers');
        
        const providersData = await response.json();
        providers = providersData; // Store providers globally
        
        // Build options in memory first
        const fragment = document.createDocumentFragment();
        const placeholder = document.createElement('option');
        placeholder.value = '';
        placeholder.disabled = true;
        placeholder.selected = true;
        placeholder.textContent = 'Select a provider';
        fragment.appendChild(placeholder);
        
        // Group providers by name to detect duplicates
        const providersByName = {};
        providers.forEach(p => {
            if (!providersByName[p.name]) providersByName[p.name] = [];
            providersByName[p.name].push(p);
        });
        
        // Create options
        providers.forEach(provider => {
            const option = document.createElement('option');
            option.value = provider.raw_id;
            option.textContent = providersByName[provider.name].length > 1 
                ? `${provider.name} (${provider.raw_id})`
                : provider.name;
            fragment.appendChild(option);
        });
        
        // Replace all options at once
        providerSelect.innerHTML = '';
        providerSelect.appendChild(fragment);
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
    const response = await fetch(`${API_BASE_URL}/provider/${providerId}`, {
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
            <div class="search-result-item" onclick="window.addStop('${stop.id}', '${escapeHtml(stop.name)}', ${stop.location.lat}, ${stop.location.lon}, true)">
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
function addStop(stopId, stopName, lat, lon, fromSearch = false) {
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

    // Only adjust map bounds if the stop was added from search
    if (fromSearch) {
        const bounds = L.latLngBounds(Array.from(selectedStops.values()).map(m => m.marker.getLatLng()));
        map.fitBounds(bounds, { padding: [50, 50] });
    }

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
    // Provider selection is handled in setupProviderSelection()

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
    const currentBounds = map.getBounds();
    const providerId = providerSelect.value;
    if (!providerId) return;

    try {
        // Show loading indicator for all loads
        const backendStatus = document.getElementById('backendStatus');
        const statusText = backendStatus.querySelector('.status-text');
        backendStatus.className = 'backend-status loading';
        backendStatus.style.display = 'block';
        backendStatus.classList.remove('fade-out');
        statusText.textContent = initialLoad ? 'Loading stops...' : 'Loading additional stops...';

        // First get the count of stops in the area
        const countResponse = await fetch(
            `${API_BASE_URL}/api/${providerId}/stops/bbox?` + 
            `min_lat=${currentBounds.getSouth()}&max_lat=${currentBounds.getNorth()}&` +
            `min_lon=${currentBounds.getWest()}&max_lon=${currentBounds.getEast()}&` +
            `count_only=true`
        );
        
        if (!countResponse.ok) throw new Error('Failed to fetch stop count');
        const { count } = await countResponse.json();

        // If we have a reasonable number of stops, load them all at once
        if (count <= 100) {
            statusText.textContent = `Loading ${count} stops...`;
            const response = await fetch(
                `${API_BASE_URL}/api/${providerId}/stops/bbox?` + 
                `min_lat=${currentBounds.getSouth()}&max_lat=${currentBounds.getNorth()}&` +
                `min_lon=${currentBounds.getWest()}&max_lon=${currentBounds.getEast()}`
            );
            
            if (!response.ok) throw new Error('Failed to fetch stops');
            
            const stops = await response.json();
            updateStopsOnMap(stops, initialLoad);
            lastLoadedBounds = currentBounds;
            
            // Show success and fade out
            backendStatus.className = 'backend-status ready';
            statusText.textContent = 'Stops loaded successfully';
            setTimeout(() => {
                backendStatus.classList.add('fade-out');
                setTimeout(() => {
                    backendStatus.style.display = 'none';
                    backendStatus.classList.remove('fade-out');
                }, 2000);
            }, 2000);
            return;
        }

        // For larger numbers of stops, load them in batches
        const batchSize = 100;
        const totalBatches = Math.ceil(count / batchSize);
        let loadedStops = 0;
        
        for (let batch = 0; batch < totalBatches; batch++) {
            // Check if the map has moved significantly before loading next batch
            const newBounds = map.getBounds();
            if (!newBounds.equals(currentBounds)) {
                console.log('Map moved, stopping batch loading');
                statusText.textContent = 'Map moved, loading stops in new area...';
                break;
            }

            // Update loading status with progress
            statusText.textContent = `Loading stops... (${Math.min(loadedStops + batchSize, count)}/${count})`;

            const response = await fetch(
                `${API_BASE_URL}/api/${providerId}/stops/bbox?` + 
                `min_lat=${currentBounds.getSouth()}&max_lat=${currentBounds.getNorth()}&` +
                `min_lon=${currentBounds.getWest()}&max_lon=${currentBounds.getEast()}&` +
                `offset=${batch * batchSize}&limit=${batchSize}`
            );
            
            if (!response.ok) throw new Error('Failed to fetch stops');
            
            const stops = await response.json();
            updateStopsOnMap(stops, batch === 0 && initialLoad);
            loadedStops += stops.length;

            // Add a small delay between batches to allow for map interaction
            if (batch < totalBatches - 1) {
                await new Promise(resolve => setTimeout(resolve, 100));
            }
        }

        lastLoadedBounds = currentBounds;
        
        // Show success and fade out
        backendStatus.className = 'backend-status ready';
        statusText.textContent = `Loaded ${loadedStops} stops successfully`;
        setTimeout(() => {
            backendStatus.classList.add('fade-out');
            setTimeout(() => {
                backendStatus.style.display = 'none';
                backendStatus.classList.remove('fade-out');
            }, 2000);
        }, 2000);

    } catch (error) {
        console.error('Error loading stops:', error);
        const backendStatus = document.getElementById('backendStatus');
        backendStatus.className = 'backend-status error';
        backendStatus.querySelector('.status-text').textContent = 'Failed to load stops';
        backendStatus.style.display = 'block';
        backendStatus.classList.remove('fade-out');
    }
}

// Calculate new areas that need to be loaded
function getNewAreas(oldBounds, newBounds) {
    const areas = [];
    
    // Only add areas if they don't completely overlap
    if (!oldBounds.contains(newBounds)) {
        // North
        if (newBounds.getNorth() > oldBounds.getNorth()) {
            areas.push(L.latLngBounds(
                [oldBounds.getNorth(), newBounds.getWest()],
                [newBounds.getNorth(), newBounds.getEast()]
            ));
        }
        // South
        if (newBounds.getSouth() < oldBounds.getSouth()) {
            areas.push(L.latLngBounds(
                [newBounds.getSouth(), newBounds.getWest()],
                [oldBounds.getSouth(), newBounds.getEast()]
            ));
        }
        // East
        if (newBounds.getEast() > oldBounds.getEast()) {
            areas.push(L.latLngBounds(
                [newBounds.getSouth(), oldBounds.getEast()],
                [newBounds.getNorth(), newBounds.getEast()]
            ));
        }
        // West
        if (newBounds.getWest() < oldBounds.getWest()) {
            areas.push(L.latLngBounds(
                [newBounds.getSouth(), newBounds.getWest()],
                [newBounds.getNorth(), oldBounds.getWest()]
            ));
        }
    }
    
    return areas;
}

// Remove markers that are no longer visible
function unloadInvisibleStops(currentBounds) {
    const markersToRemove = [];
    mapMarkers.forEach((data, stopId) => {
        const pos = data.marker.getLatLng();
        if (!currentBounds.contains(pos)) {
            markersToRemove.push(stopId);
        }
    });

    markersToRemove.forEach(stopId => {
        const marker = mapMarkers.get(stopId);
        if (marker) {
            map.removeLayer(marker.marker);
            mapMarkers.delete(stopId);
        }
    });
}

// Update stops displayed on the map
function updateStopsOnMap(stops, clearExisting = true) {
    // Clear existing markers if requested
    if (clearExisting) {
        mapMarkers.forEach(({ marker }) => map.removeLayer(marker));
        mapMarkers.clear();
    }

    // Check if we should show unselected stops
    const showUnselected = document.getElementById('showUnselectedStops').checked;
    if (!showUnselected) return;

    // Add new markers
    stops.forEach(stop => {
        // Skip if this stop is already selected or already has a marker
        if (selectedStops.has(stop.id) || mapMarkers.has(stop.id)) return;

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
            addStop(stop.id, stop.name, stop.location.lat, stop.location.lon, false);
            marker.closePopup();
        });
        popupContent.appendChild(addButton);

        marker.bindPopup(popupContent);
        marker.addTo(map);
        mapMarkers.set(stop.id, { marker, color, name: stop.name });
    });
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
