import { L } from './map.js';
import { isValidCoordinate, handleError } from './utils.js';

export class VehicleManager {
    constructor(map) {
        this.map = map;
        this.vehicles = new Map(); // vehicleId -> marker
        this.layer = L.layerGroup().addTo(map);
    }

    updateVehicles(vehiclesData) {
        try {
            // Remove old vehicles
            const currentIds = new Set(vehiclesData.map(v => v.id));
            for (const [id, marker] of this.vehicles.entries()) {
                if (!currentIds.has(id)) {
                    this.layer.removeLayer(marker);
                    this.vehicles.delete(id);
                }
            }

            // Update or add new vehicles
            vehiclesData.forEach(vehicle => {
                if (!isValidCoordinate(vehicle.coordinates)) {
                    console.warn(`Invalid coordinates for vehicle ${vehicle.id}`);
                    return;
                }

                const position = [vehicle.coordinates.lat, vehicle.coordinates.lon];
                
                if (this.vehicles.has(vehicle.id)) {
                    // Update existing vehicle
                    const marker = this.vehicles.get(vehicle.id);
                    marker.setLatLng(position);
                    marker.setRotation(vehicle.bearing || 0);
                    this.updateVehiclePopup(marker, vehicle);
                } else {
                    // Add new vehicle
                    const marker = this.createVehicleMarker(vehicle);
                    this.vehicles.set(vehicle.id, marker);
                    marker.addTo(this.layer);
                }
            });
        } catch (error) {
            handleError(error, 'VehicleManager.updateVehicles');
        }
    }

    createVehicleMarker(vehicle) {
        const marker = L.marker([vehicle.coordinates.lat, vehicle.coordinates.lon], {
            icon: L.divIcon({
                className: 'vehicle-marker',
                html: `<div class="vehicle-icon" style="transform: rotate(${vehicle.bearing || 0}deg)"></div>`
            })
        });

        this.updateVehiclePopup(marker, vehicle);
        return marker;
    }

    updateVehiclePopup(marker, vehicle) {
        const content = `
            <div class="vehicle-popup">
                <h4>Line ${vehicle.line}</h4>
                <p>Direction: ${vehicle.direction}</p>
                ${vehicle.delay ? `<p>Delay: ${Math.round(vehicle.delay / 60)} min</p>` : ''}
                <p>Status: ${vehicle.is_realtime ? 'Real-time' : 'Scheduled'}</p>
            </div>
        `;
        marker.bindPopup(content);
    }

    clear() {
        this.layer.clearLayers();
        this.vehicles.clear();
    }
} 