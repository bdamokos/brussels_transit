"""BKK transit provider"""

from .api import (
    bkk_config,
    get_waiting_times,
    get_service_alerts,
    get_vehicle_positions,
    get_static_data
)

def register_bkk_provider(register_func):
    """Register BKK provider endpoints"""
    register_func('bkk', {
        'config': bkk_config,
        'waiting_times': get_waiting_times,
        'service_messages': get_service_alerts,
        'vehicles': get_vehicle_positions,
        'static_data': get_static_data
    })

__all__ = [
    'bkk_config',
    'get_waiting_times',
    'get_service_alerts',
    'get_vehicle_positions',
    'get_static_data',
    'register_bkk_provider'
]
