import { L } from './map.js';
import { isValidCoordinate, handleError } from './utils.js';

export class VehicleManager {
    constructor(mapManager) {
        this.mapManager = mapManager;
        this.vehicles = new Map(); // vehicleId -> marker
        this.layer = L.layerGroup().addTo(mapManager.map);
    }

    updateVehicles(vehiclesData, provider) {
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
                    // Update rotation via CSS
                    const icon = marker.getElement();
                    if (icon) {
                        const vehicleIcon = icon.querySelector('.vehicle-icon');
                        if (vehicleIcon) {
                            vehicleIcon.style.transform = `rotate(${vehicle.bearing || 0}deg)`;
                        }
                    }
                    this.updateVehiclePopup(marker, vehicle, provider);
                } else {
                    // Add new vehicle
                    const marker = this.createVehicleMarker(vehicle, provider);
                    this.vehicles.set(vehicle.id, marker);
                    marker.addTo(this.layer);
                }
            });
        } catch (error) {
            handleError(error, 'VehicleManager.updateVehicles');
        }
    }

    createVehicleMarker(vehicle, provider) {
        const color = provider.getLineColor(vehicle.line);
        const marker = L.marker([vehicle.coordinates.lat, vehicle.coordinates.lon], {
            icon: L.divIcon({
                className: 'vehicle-marker',
                html: `<div class="vehicle-icon" style="background-color: ${color}; transform: rotate(${vehicle.bearing || 0}deg)">
                        <span class="line-number">${vehicle.line}</span>
                      </div>`
            })
        });

        this.updateVehiclePopup(marker, vehicle, provider);
        return marker;
    }

    updateVehiclePopup(marker, vehicle, provider) {
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