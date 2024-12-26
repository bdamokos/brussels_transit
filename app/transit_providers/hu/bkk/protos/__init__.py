"""BKK protobuf definitions"""

from .gtfs_realtime_pb2 import FeedMessage, FeedHeader, FeedEntity, TripUpdate, VehiclePosition, Alert
from .gtfs_realtime_realcity_pb2 import VehicleDescriptor, StopTimeUpdate, RouteDetail, Alert as RealCityAlert

__all__ = [
    'FeedMessage',
    'FeedHeader',
    'FeedEntity',
    'TripUpdate',
    'VehiclePosition',
    'Alert',
    'VehicleDescriptor',
    'StopTimeUpdate',
    'RouteDetail',
    'RealCityAlert'
] 