from .. import register_provider
from .api import (
    bkk_config as bkk_config,
    bkk_waiting_times as get_waiting_times,
    bkk_service_alerts as get_service_alerts,
    bkk_vehicle_positions as get_vehicle_positions,
    bkk_static_data as get_static_data
)

# Register BKK provider endpoints
register_provider('bkk', {
    'config': bkk_config,
    'waiting_times': get_waiting_times,
    'service_messages': get_service_alerts,
    'vehicles': get_vehicle_positions,
    'static_data': get_static_data
})
