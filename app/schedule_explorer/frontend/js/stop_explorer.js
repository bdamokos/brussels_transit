// Global variables
let map = null;
let stopMarker = null;
let routeLines = [];
let selectedLanguage = null;
const API_BASE_URL = 'http://localhost:8000';

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
}

// Load available providers
async function loadProviders() {
    try {
        const response = await fetch(`${API_BASE_URL}/providers`);
        const providers = await response.json();
        console.log('Providers response:', providers);  // Debug log
        
        const select = document.getElementById('providerSelect');
        if (!Array.isArray(providers)) {
            console.error('Expected array of providers, got:', typeof providers);
            return;
        }
        
        // Add a disabled default option
        select.innerHTML = '<option value="" selected disabled>Select a provider</option>';
        // Add the providers
        select.innerHTML += providers.map(provider => 
            `<option value="${provider}">${provider}</option>`
        ).join('');
        
        // Reset and disable the language select
        const languageSelect = document.getElementById('languageSelect');
        languageSelect.innerHTML = '<option value="" selected disabled>Select provider first</option>';
        languageSelect.disabled = true;
        
        // Enable the provider select
        select.disabled = false;
    } catch (error) {
        console.error('Error loading providers:', error);
        showError('Failed to load providers');
    }
}

// Load a specific provider
async function loadProvider(provider) {
    showLoading('Loading GTFS data...');
    try {
        const response = await fetch(`${API_BASE_URL}/provider/${provider}`, { method: 'POST' });
        const result = await response.json();
        
        if (result.status === 'success') {
            document.getElementById('stopSearch').disabled = false;
            showSuccess('GTFS data loaded successfully');
            await loadLanguages();
        } else {
            showError('Failed to load GTFS data');
        }
    } catch (error) {
        console.error('Error loading provider:', error);
        showError('Failed to load GTFS data');
    }
}

// Load available languages
async function loadLanguages() {
    try {
        // Get a sample of stations to detect available languages
        const response = await fetch(`${API_BASE_URL}/stations/search?query=a`);
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
            resultsDiv.innerHTML = '<div class="no-results">No stops found</div>';
            return;
        }
        
        resultsDiv.innerHTML = stops.map(stop => `
            <a class="dropdown-item" href="#" onclick="selectStop('${stop.id}', '${stop.name}', ${stop.location.lat}, ${stop.location.lon}); return false;">
                ${stop.name}
                <br>
                <small class="text-muted">${stop.id}</small>
            </a>
        `).join('');
    } catch (error) {
        console.error('Error searching stops:', error);
    }
}

// Select a stop and show its details
async function selectStop(stopId, stopName, lat, lon) {
    // Update stop details
    document.getElementById('selectedStopName').textContent = stopName;
    document.getElementById('selectedStopId').textContent = `Stop ID: ${stopId}`;
    document.getElementById('stopDetails').style.display = 'block';
    
    // Clear search results
    document.getElementById('stopSearchResults').classList.remove('show');
    document.getElementById('stopSearch').value = '';
    
    // Update map
    if (stopMarker) {
        map.removeLayer(stopMarker);
    }
    routeLines.forEach(line => map.removeLayer(line));
    routeLines = [];
    
    stopMarker = L.marker([lat, lon]).addTo(map);
    map.setView([lat, lon], 15);
    
    // Load routes for this stop
    await loadStopRoutes(stopId);
}

// Load routes operating from a stop
async function loadStopRoutes(stopId) {
    try {
        const response = await fetch(`${API_BASE_URL}/stations/${stopId}/routes?language=${selectedLanguage}`);
        const routes = await response.json();
        
        const routesList = document.getElementById('routesList');
        
        if (!routes || routes.length === 0) {
            routesList.innerHTML = '<div class="alert alert-info">No routes found for this stop.</div>';
            return;
        }
        
        routesList.innerHTML = routes.map(route => `
            <div class="route-line" style="border-left-color: #${route.color || '000000'}">
                <div class="row">
                    <div class="col-md-2">
                        <span class="badge bg-${route.color ? '' : 'secondary'}" 
                              style="${route.color ? `background-color: #${route.color}!important` : ''}">
                            ${route.short_name || route.route_id}
                        </span>
                    </div>
                    <div class="col-md-10">
                        <div class="route-terminus">
                            ${route.headsign || route.last_stop}
                        </div>
                        <div class="route-details">
                            <small class="text-muted">
                                ${route.route_name}
                                <br>
                                From: ${route.first_stop}
                                <br>
                                To: ${route.last_stop}
                                <br>
                                Service days: ${route.service_days.map(day => 
                                    day.charAt(0).toUpperCase() + day.slice(1)
                                ).join(', ')}
                            </small>
                        </div>
                    </div>
                </div>
            </div>
        `).join('');
        
        // Clear existing route lines
        routeLines.forEach(line => map.removeLayer(line));
        routeLines = [];
        
        // Draw route lines on map if we have shape data
        // Note: We'll need to add shape data to the endpoint if we want to show route lines
        
    } catch (error) {
        console.error('Error loading stop routes:', error);
        document.getElementById('routesList').innerHTML = 
            '<div class="alert alert-danger">Failed to load routes for this stop.</div>';
    }
}

// Setup event listeners
function setupEventListeners() {
    // Provider selection
    document.getElementById('providerSelect').addEventListener('change', async (e) => {
        await loadProvider(e.target.value);
    });
    
    // Language selection
    document.getElementById('languageSelect').addEventListener('change', (e) => {
        selectedLanguage = e.target.value;
    });
    
    // Stop search
    let searchTimeout;
    document.getElementById('stopSearch').addEventListener('input', (e) => {
        clearTimeout(searchTimeout);
        searchTimeout = setTimeout(() => searchStops(e.target.value), 300);
    });
    
    // Close search results when clicking outside
    document.addEventListener('click', (e) => {
        if (!e.target.closest('.dropdown')) {
            document.getElementById('stopSearchResults').classList.remove('show');
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

// Initialize when the page loads
document.addEventListener('DOMContentLoaded', init); 