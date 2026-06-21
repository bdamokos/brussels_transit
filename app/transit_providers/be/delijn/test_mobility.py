import os
import sys
import csv
from pathlib import Path

_APP_DIR = Path(__file__).resolve().parents[3]
os.environ.setdefault("PROJECT_ROOT", str(_APP_DIR))
if str(_APP_DIR) not in sys.path:
    sys.path.insert(0, str(_APP_DIR))

from transit_providers.be.delijn import api as delijn_api
from transit_providers.be.delijn import ids as delijn_ids


def test_strip_delijn_id_prefix():
    assert delijn_ids.strip_delijn_id_prefix("gs:delijn:307250") == "307250"
    assert delijn_ids.strip_delijn_id_prefix("gr:delijn:10010") == "10010"
    assert delijn_ids.strip_delijn_id_prefix("gt:delijn:trip-1") == "trip-1"
    assert delijn_ids.strip_delijn_id_prefix("307250") == "307250"


def test_normalize_static_gtfs_dir(tmp_path):
    stops = tmp_path / "stops.txt"
    with stops.open("w", encoding="utf-8", newline="") as out_file:
        writer = csv.DictWriter(out_file, fieldnames=["stop_id", "parent_station"])
        writer.writeheader()
        writer.writerow(
            {"stop_id": "gs:delijn:307250", "parent_station": "gs:delijn:parent"}
        )

    routes = tmp_path / "routes.txt"
    with routes.open("w", encoding="utf-8", newline="") as out_file:
        writer = csv.DictWriter(out_file, fieldnames=["agency_id", "route_id"])
        writer.writeheader()
        writer.writerow({"agency_id": "delijn", "route_id": "gr:delijn:10010"})

    delijn_ids.normalize_static_gtfs_dir(tmp_path)

    assert list(csv.DictReader(stops.open(encoding="utf-8"))) == [
        {"stop_id": "307250", "parent_station": "parent"}
    ]
    assert list(csv.DictReader(routes.open(encoding="utf-8"))) == [
        {"agency_id": "delijn", "route_id": "10010"}
    ]


def test_format_belgian_mobility_alerts_maps_entities_to_legacy_shape():
    feed = {
        "entity": [
            {
                "id": "alert-1",
                "alert": {
                    "activePeriod": [{"start": "1766602800", "end": "1766606400"}],
                    "effect": "DETOUR",
                    "headerText": {
                        "translation": [
                            {"language": "nl", "text": "Omleiding op lijn 1"}
                        ]
                    },
                    "descriptionText": {
                        "translation": [
                            {"language": "nl", "text": "Halte tijdelijk niet bediend"}
                        ]
                    },
                    "informedEntity": [
                        {"routeId": "gr:delijn:10010", "stopId": "gs:delijn:307250"}
                    ],
                },
            }
        ]
    }

    messages = delijn_api._format_belgian_mobility_alerts(
        feed,
        route_map={"10010": "1"},
        stop_map={"307250": "Brussel Zuid perron 10"},
        monitored_lines={"1"},
        monitored_stops=set(),
    )

    assert messages == [
        {
            "title": "Omleiding op lijn 1",
            "description": "Halte tijdelijk niet bediend",
            "period": {
                "start": "2025-12-24T20:00:00+01:00",
                "end": "2025-12-24T21:00:00+01:00",
            },
            "type": "DETOUR",
            "reference": "alert-1",
            "affected_lines": ["1"],
            "line_colors": {},
            "affected_stops": [
                {
                    "id": "307250",
                    "name": "Brussel Zuid perron 10",
                    "long_name": "Brussel Zuid perron 10",
                }
            ],
            "affected_days": [],
            "is_monitored": True,
            "source": "belgian_mobility",
        }
    ]
