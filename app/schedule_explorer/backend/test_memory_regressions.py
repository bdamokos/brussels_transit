"""Offline regressions for compact timetables and provider retention."""

import gc
import json
import weakref
from dataclasses import asdict
from pathlib import Path

import msgpack
import pytest
from fastapi.testclient import TestClient

from . import gtfs_loader as loader
from . import main


def write_feed(path, provider):
    """Small complete feeds exercising the supported GTFS schema variations."""
    path.mkdir()
    parent = "P" if provider == "sncb" else ""
    prefix = "gt:sncb:" if provider == "sncb" else ""
    trip = prefix + "000123"
    files = {
        "agency.txt": "agency_id,agency_name,agency_url,agency_timezone\nA,Agency,https://example.test,Europe/Brussels\n",
        "stops.txt": "stop_id,stop_name,stop_lat,stop_lon,location_type,parent_station\n"
        + ("P,Parent,50.84,4.36,1,\n" if parent else "")
        + f"001,First,50.84,4.36,0,{parent}\n002,Second,50.85,4.37,0,{parent}\n003,Last,50.86,4.38,0,\n",
        "routes.txt": "route_id,agency_id,route_short_name,route_long_name,route_type,route_color,route_text_color\nR,A,56,Test route,3,FF0000,FFFFFF\n",
        "trips.txt": "route_id,service_id,trip_id,trip_headsign,direction_id\n"
        + f"R,S,{trip},Last,0\nR,S,{trip}-return,First,1\n",
        "stop_times.txt": "trip_id,arrival_time,departure_time,stop_id,stop_sequence\n"
        + f"{trip},23:55:00,23:55:00,001,1\n{trip},24:05:00,24:06:00,002,2\n{trip},25:00:00,25:00:00,003,3\n"
        + f"{trip}-return,25:01:00,25:01:00,003,1\n{trip}-return,25:10:00,25:10:00,002,2\n{trip}-return,25:20:00,25:20:00,001,3\n",
        "calendar_dates.txt": "service_id,date,exception_type\nS,20250115,1\nS,20250116,2\n",
    }
    if provider != "volanbusz":
        files["calendar.txt"] = "service_id,monday,tuesday,wednesday,thursday,friday,saturday,sunday,start_date,end_date\nS,1,1,1,1,1,1,1,20250101,20251231\n"
    if provider == "stib":
        files["translations.txt"] = "trans_id,translation,lang\nFirst,Premier,fr\nFirst,Eerste,nl\n"
    for name, contents in files.items():
        (path / name).write_text(contents)
    return trip


@pytest.mark.parametrize("provider", ["stib", "sncb", "bkk", "volanbusz"])
def test_cold_cache_and_old_reader_equivalence(tmp_path, provider):
    path = tmp_path / provider
    trip_id = write_feed(path, provider)
    cold = loader.load_feed(path)
    warm = loader.load_feed(path)
    assert len(cold.trips) == len(warm.trips) == 2
    assert sum(map(len, warm.stop_times_dict.values())) == 6
    assert isinstance(cold.stop_times_dict[trip_id][0], loader.StopTime)
    assert cold.stop_times_dict[trip_id] == warm.stop_times_dict[trip_id]
    assert warm.stop_times_dict[trip_id][1]["departure_time"] == "24:06:00"
    assert dict(warm.stop_times_dict[trip_id][0]) == {
        "trip_id": trip_id, "stop_id": "001", "arrival_time": "23:55:00",
        "departure_time": "23:55:00", "stop_sequence": 1,
    }
    # Wire format stays a map with the same fields, usable by existing readers.
    raw = msgpack.unpackb(loader.serialize_gtfs_data(warm), raw=False)
    assert raw == msgpack.unpackb(loader.serialize_gtfs_data(cold), raw=False)
    assert raw["stop_times_dict"][trip_id][0] == dict(warm.stop_times_dict[trip_id][0])
    assert loader.deserialize_gtfs_data(msgpack.packb(raw)).stop_times_dict == warm.stop_times_dict
    # Routes, directions, overnight times, translated stops and calendars survive.
    for start, end in [("001", "003"), ("003", "001")]:
        before = cold.find_trips_between_stations(start, end)
        after = warm.find_trips_between_stations(start, end)
        assert len(before) == len(after) == 2
        assert [[asdict(s) for s in r.stops] for r in before] == [[asdict(s) for s in r.stops] for r in after]
    assert warm.get_stop_name("001", "fr") == cold.get_stop_name("001", "fr")
    assert warm.calendars == cold.calendars
    assert warm.calendar_dates == cold.calendar_dates


def test_pool_shares_values_without_retaining_previous_feeds(tmp_path):
    path = tmp_path / "stib"
    trip = write_feed(path, "stib")
    loader.load_feed(path)
    refs = []
    for _ in range(8):
        feed = loader.load_feed(path)
        rows = feed.stop_times_dict[trip]
        assert rows[0].trip_id is rows[1].trip_id
        assert rows[0].arrival_time is rows[0].departure_time
        assert rows[1].stop_id is feed.stop_times_dict[trip + "-return"][1].stop_id
        refs.append(weakref.ref(feed))
        del rows, feed
    gc.collect()
    assert all(ref() is None for ref in refs)


def test_mapping_and_unrecognized_fields():
    row = {"trip_id": "T", "stop_id": "001", "arrival_time": "26:00:00",
           "departure_time": "26:00:00", "stop_sequence": 300}
    builder = loader._StopTimeBuilder()
    compact = builder(row)
    assert dict(compact) == row
    assert compact.get("missing", "fallback") == "fallback"
    with pytest.raises(KeyError):
        compact["_fields"]
    extended = dict(row, pickup_type=2)
    assert builder(extended) is extended


def test_c_and_python_stop_times_match(tmp_path, monkeypatch):
    if not Path(loader.__file__).with_name("gtfs_precache").exists():
        pytest.skip("Build gtfs_precache to compare both loading paths")
    path = tmp_path / "stib"
    write_feed(path, "stib")
    native = loader.load_stop_times(path)
    # Use an executable-free directory to force the documented Python fallback.
    monkeypatch.setattr(loader, "__file__", str(tmp_path / "gtfs_loader.py"))
    fallback = loader.load_stop_times(path)
    assert native == fallback
    assert isinstance(next(iter(native.values()))[0], loader.StopTime)


def test_trip_embedded_stop_times_and_precache(tmp_path, monkeypatch):
    from . import precache_gtfs

    path = tmp_path / "stib"
    trip_id = write_feed(path, "stib")
    feed = loader.load_feed(path)
    feed.trips[trip_id].stop_times = list(feed.stop_times_dict[trip_id])
    restored = loader.deserialize_gtfs_data(loader.serialize_gtfs_data(feed))
    assert restored.trips[trip_id].stop_times == feed.trips[trip_id].stop_times
    monkeypatch.setattr(precache_gtfs, "create_cpu_limiter", lambda *args: lambda: None)
    precache_gtfs.precache_gtfs(path)
    assert loader.load_feed(path).stop_times_dict == feed.stop_times_dict


def test_provider_aliases_and_selection_do_not_reload(tmp_path, monkeypatch):
    path = tmp_path / "stib"
    write_feed(path, "stib")
    metadata = {"dataset": {"provider_id": "mdb-1088", "provider_name": "STIB",
        "dataset_id": "dataset", "download_path": str(path), "download_date": "2025-01-09",
        "file_hash": "test", "source_url": "https://example.test/feed.zip"}}
    (tmp_path / "datasets_metadata.json").write_text(json.dumps(metadata))
    monkeypatch.setattr(main, "DOWNLOAD_DIR", tmp_path)
    monkeypatch.setattr(main, "available_providers", [])
    monkeypatch.setattr(main, "feed", None)
    monkeypatch.setattr(main, "current_provider", None)
    loads = []

    def load(data_dir):
        result = loader.load_feed(data_dir)
        loads.append(weakref.ref(result))
        return result

    monkeypatch.setattr(main, "load_feed", load)
    client = TestClient(main.app)
    aliases = ["mdb-1088", main.find_gtfs_directories()[0].id]
    for alias in aliases * 3:
        assert client.post(f"/provider/{alias}").status_code == 200
        response = client.get(f"/api/{alias}/stations/search", params={"query": "First"})
        assert response.status_code == 200
        assert response.json()[0]["id"] == "001"
    assert len(loads) == 1
