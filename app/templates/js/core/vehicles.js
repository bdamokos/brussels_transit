import { L } from './map.js';
import { isValidCoordinate, handleError } from './utils.js';

export class VehicleManager {
    constructor(mapManager, stopManager) {
        this.mapManager = mapManager;
        this.stopManager = stopManager;
        this.vehicles = new Map(); // vehicleId -> marker
        this.layer = L.layerGroup().addTo(mapManager.map);
        this.monitoredLines = new Set(['59', '92', '64', '12', '55', '56']); // Ensure this is correctly initialized
    }

    updateVehicles(vehiclesData, provider) {
        try {
            console.log('Updating vehicles with:', vehiclesData);

            vehiclesData.forEach(vehicle => {
                console.log('Checking vehicle:', vehicle);

                if (!vehicle.id) {
                    console.log('Missing vehicle ID. Assigning a random ID.');
                    vehicle.id = `vehicle-${Math.random().toString(36).substr(2, 9)}`;
                }

                if (!vehicle.coordinates) {
                    console.log('Missing vehicle.coordinates:', vehicle);
                }

                if (!isValidCoordinate(vehicle.coordinates)) {
                    console.log('Invalid coordinates for vehicle:', vehicle);
                    console.warn('Invalid vehicle data:', vehicle);
                    return;
                }
                
                const position = [vehicle.coordinates.lat, vehicle.coordinates.lon];
                
                if (this.vehicles.has(vehicle.id)) {
                    const marker = this.vehicles.get(vehicle.id);
                    marker.setLatLng(position);
                    this.updateVehiclePopup(marker, vehicle, provider);
                } else {
                    const marker = this.createVehicleMarker(vehicle, provider);
                    this.vehicles.set(vehicle.id, marker);
                    marker.addTo(this.layer);
                }
            });

            console.log('Current vehicles:', this.vehicles);
        } catch (error) {
            handleError(error, 'VehicleManager.updateVehicles');
        }
    }

    createVehicleMarker(vehicle, provider) {
        const color = provider.getLineColor(vehicle.line);
        
        const marker = L.marker([vehicle.coordinates.lat, vehicle.coordinates.lon], {
            icon: L.divIcon({
                className: 'vehicle-marker',
                html: `
                    <div class="vehicle-marker-content" style="
                        --bearing: ${vehicle.bearing}deg;
                        --bg-color: ${color}; --text-color: white;
                    ">
                        <div class="line-number">
                            ${vehicle.line}
                        </div>
                        <div class="vehicle-arrow"></div>
                    </div>
                `,
                iconSize: [20, 20],
                iconAnchor: [10, 10]
            })
        });

        this.updateVehiclePopup(marker, vehicle, provider);
        return marker;
    }

    updateVehiclePopup(marker, vehicle, provider) {
        let segmentInfo = '';
        if (vehicle.current_segment) {
            const [stop1Id, stop2Id] = vehicle.current_segment;
            const stop1Name = this.stopManager.getStopName(stop1Id) || stop1Id;
            const stop2Name = this.stopManager.getStopName(stop2Id) || stop2Id;
            segmentInfo = `Between ${stop1Name} and ${stop2Name}`;
        }

        const content = `
            <strong>Line ${vehicle.line}</strong><br>
            To: ${vehicle.direction}<br>
            ${segmentInfo}
        `;
        marker.bindPopup(content);
    }

    clear() {
        this.layer.clearLayers();
        this.vehicles.clear();
    }

    async getVehicles() {
        try {
            const response = await fetch('/api/stib/vehicles');
            if (!response.ok) throw new Error('Failed to fetch vehicle data');
            const data = await response.json();
            
            const vehicles = data.vehicles
                .filter(vehicle => this.monitoredLines.has(vehicle.line?.toString()))
                .map(vehicle => {
                    const vehicleId = vehicle.id || `vehicle-${Math.random().toString(36).substr(2, 9)}`;
                    
                    const processedVehicle = {
                        id: vehicleId,
                        line: vehicle.line,
                        direction: vehicle.direction,
                        coordinates: {
                            lat: vehicle.interpolated_position[0],
                            lon: vehicle.interpolated_position[1]
                        },
                        bearing: vehicle.bearing,
                        is_realtime: vehicle.is_valid,
                        delay: vehicle.raw_data?.delay || 0,
                        current_segment: vehicle.current_segment
                    };

                    console.log('Created vehicle:', processedVehicle);
                    
                    return processedVehicle;
                });

            console.log('Processed vehicles with IDs:', vehicles.map(v => v.id));
            return vehicles;
        } catch (error) {
            console.error('Error fetching STIB vehicles:', error);
            return [];
        }
    }
} 