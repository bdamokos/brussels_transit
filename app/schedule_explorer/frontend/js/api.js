// Base URL for the API
const API_BASE_URL = 'http://localhost:8000';

// Get stops within a bounding box
export async function getStopsInBbox(providerId, minLat, minLon, maxLat, maxLon, language = 'default') {
    const url = new URL(`${API_BASE_URL}/api/${providerId}/stops/bbox`);
    url.searchParams.append('min_lat', minLat);
    url.searchParams.append('min_lon', minLon);
    url.searchParams.append('max_lat', maxLat);
    url.searchParams.append('max_lon', maxLon);
    url.searchParams.append('language', language);

    const response = await fetch(url);
    if (!response.ok) {
        throw new Error(`Failed to fetch stops: ${response.statusText}`);
    }
    return response.json();
}

// Get waiting times for a stop
export async function getWaitingTimes(providerId, stopId, limit = 2) {
    const url = new URL(`${API_BASE_URL}/api/${providerId}/stops/${stopId}/waiting_times`);
    url.searchParams.append('limit', limit);

    const response = await fetch(url);
    if (!response.ok) {
        throw new Error(`Failed to fetch waiting times: ${response.statusText}`);
    }
    return response.json();
}

// Get route colors
export async function getRouteColors(providerId, routeId) {
    const url = new URL(`${API_BASE_URL}/api/${providerId}/colors/${routeId}`);

    const response = await fetch(url);
    if (!response.ok) {
        throw new Error(`Failed to fetch route colors: ${response.statusText}`);
    }
    return response.json();
} 