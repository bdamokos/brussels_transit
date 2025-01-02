"""SNCB protobuf definitions"""

from .gtfs_realtime_pb2 import (
    FeedMessage,
    FeedHeader,
    FeedEntity,
    TripUpdate,
    VehiclePosition,
    Alert,
)

__all__ = [
    "FeedMessage",
    "FeedHeader",
    "FeedEntity",
    "TripUpdate",
    "VehiclePosition",
    "Alert",
]
