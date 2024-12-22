// Global variables
let map = null;
let stopMarkers = new Map();
let routeLines = [];
let selectedLanguage = 'default';
const API_BASE_URL = 'http://localhost:8000';
const MARKER_COLORS = ['#e41a1c', '#377eb8', '#4daf4a', '#984ea3', '#ff7f00'];
let colorIndex = 0;

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
    map = L.map('map').setView([50.8503, 4.3517], 13);  // Brussels center
    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
        maxZoom: 19,
        attribution: '© OpenStreetMap contributors'
    }).addTo(map);
}

// Initialize the page
async function init() {
    initMap();
    await loadProviders();
    setupEventListeners();
    // Initial search moved to after provider loading
}

// Load available providers
async function loadProviders() {
    try {
        const response = await fetch(`${API_BASE_URL}/providers`);
        const providers = await response.json();
        
        const select = document.getElementById('providerSelect');
        select.innerHTML = '<option value="" selected disabled>Select a provider</option>' +
            providers.map(provider => `<option value="${provider}">${provider}</option>`).join('');
        
        const languageSelect = document.getElementById('languageSelect');
        languageSelect.innerHTML = '<option value="" selected disabled>Select provider first</option>';
        languageSelect.disabled = true;
        
        select.disabled = false;
    } catch (error) {
        console.error('Error loading providers:', error);
        showError('Failed to load providers');
    }
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
            <div class="search-result-item" onclick="addStop('${stop.id}', '${stop.name}', ${stop.location.lat}, ${stop.location.lon})">
                <div class="stop-name">${stop.name}</div>
                <small class="text-muted">${stop.id}</small>
            </div>
        `).join('');
    } catch (error) {
        console.error('Error searching stops:', error);
    }
}

// Add a stop to the selection
function addStop(stopId, stopName, lat, lon) {
    if (stopMarkers.has(stopId)) {
        return; // Stop already added
    }
    
    const color = MARKER_COLORS[colorIndex % MARKER_COLORS.length];
    colorIndex++;
    
    // Add marker to map
    const marker = L.marker([lat, lon], {
        icon: L.divIcon({
            className: 'custom-div-icon',
            html: `<div style="background-color: ${color};" class="marker-pin"></div>`,
            iconSize: [30, 42],
            iconAnchor: [15, 42]
        })
    }).addTo(map);
    stopMarkers.set(stopId, { marker, color });
    
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
        const routePromises = Array.from(stopMarkers.keys()).map(stopId => 
            fetch(`${API_BASE_URL}/stations/${stopId}/routes?language=${selectedLanguage}`)
                .then(response => response.json())
                .then(routes => ({ stopId, routes }))
        );
        
        const results = await Promise.all(routePromises);
        
        // Group routes by stop
        routesContainer.innerHTML = results.map(({ stopId, routes }) => {
            const { color } = stopMarkers.get(stopId);
            const stopName = document.querySelector(`#stop-row-${stopId} .stop-name`).textContent;
            
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