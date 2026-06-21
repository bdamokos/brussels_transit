import csv
import importlib.util
from pathlib import Path

_MODULE_PATH = Path(__file__).with_name("sncb_ids.py")
_SPEC = importlib.util.spec_from_file_location("sncb_ids_under_test", _MODULE_PATH)
sncb_ids = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(sncb_ids)

normalize_sncb_stop_id = sncb_ids.normalize_sncb_stop_id
normalize_static_gtfs_dir = sncb_ids.normalize_static_gtfs_dir
strip_sncb_id_prefix = sncb_ids.strip_sncb_id_prefix
unwrap_gtfs_json_ints = sncb_ids.unwrap_gtfs_json_ints


def test_strip_sncb_id_prefix_keeps_legacy_ids():
    assert strip_sncb_id_prefix("gt:nmbssncb:88____:007") == "88____:007"
    assert strip_sncb_id_prefix("gs:nmbssncb:8813003_3") == "8813003_3"
    assert strip_sncb_id_prefix("gr:nmbssncb:60") == "60"
    assert strip_sncb_id_prefix("8813003") == "8813003"


def test_normalize_sncb_stop_id_can_collapse_platform_suffix():
    assert normalize_sncb_stop_id("gs:nmbssncb:8813003_3") == "8813003_3"
    assert (
        normalize_sncb_stop_id("gs:nmbssncb:8813003_3", collapse_platform=True)
        == "8813003"
    )


def test_unwrap_gtfs_json_ints_converts_protobufjs_long_objects():
    payload = {
        "header": {"timestamp": {"low": 1782048998, "high": 0, "unsigned": True}},
        "entity": [{"timestamp": {"low": 1, "high": 1, "unsigned": True}}],
    }

    assert unwrap_gtfs_json_ints(payload) == {
        "header": {"timestamp": 1782048998},
        "entity": [{"timestamp": 4294967297}],
    }


def test_normalize_static_gtfs_dir_rewrites_belgian_mobility_ids(tmp_path):
    _write_csv(
        tmp_path / "stops.txt",
        ["stop_id", "parent_station", "stop_name"],
        [["gs:nmbssncb:8813003_3", "gs:nmbssncb:S8813003", "Bruxelles-Central"]],
    )
    _write_csv(
        tmp_path / "trips.txt",
        ["route_id", "service_id", "trip_id"],
        [
            [
                "gr:nmbssncb:60",
                "gc:nmbssncb:000071",
                "gt:nmbssncb:88____:046::8833001:8833209:3:2242:20260918",
            ]
        ],
    )
    _write_csv(
        tmp_path / "stop_times.txt",
        ["trip_id", "stop_id", "stop_sequence"],
        [
            [
                "gt:nmbssncb:88____:046::8833001:8833209:3:2242:20260918",
                "gs:nmbssncb:8813003_3",
                "1",
            ]
        ],
    )

    normalize_static_gtfs_dir(tmp_path)

    assert _read_csv(tmp_path / "stops.txt")[0] == {
        "stop_id": "8813003_3",
        "parent_station": "S8813003",
        "stop_name": "Bruxelles-Central",
    }
    assert _read_csv(tmp_path / "trips.txt")[0] == {
        "route_id": "60",
        "service_id": "000071",
        "trip_id": "88____:046::8833001:8833209:3:2242:20260918",
    }
    assert _read_csv(tmp_path / "stop_times.txt")[0] == {
        "trip_id": "88____:046::8833001:8833209:3:2242:20260918",
        "stop_id": "8813003_3",
        "stop_sequence": "1",
    }


def _write_csv(path, fieldnames, rows):
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(fieldnames)
        writer.writerows(rows)


def _read_csv(path):
    with path.open("r", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))
