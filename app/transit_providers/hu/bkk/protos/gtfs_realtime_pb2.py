"""Compatibility imports backed by the shared GTFS-realtime descriptor.

Use the installed bindings so providers and RealCity extensions share the same
message classes regardless of import order.
"""

from google.transit.gtfs_realtime_pb2 import *  # noqa: F401,F403
