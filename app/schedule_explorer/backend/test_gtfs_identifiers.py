"""Identifier joins and optional parent stations survive CSV and cache loading."""

import csv
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from . import gtfs_loader, main


def write_table(directory, name, rows):
    with (directory / f"{name}.txt").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def write_feed(directory, trip_id="t1", stop_id="s1", parent_station="0007"):
    # Reuse the trip identifier across linked tables to catch coercion at any join.
    write_table(
        directory,
        "agency",
        [
            {
                "agency_id": trip_id,
                "agency_name": "Example",
                "agency_url": "https://example.test",
                "agency_timezone": "Europe/Brussels",
                "agency_lang": "",
            }
        ],
    )
    stops = [
        {"stop_id": stop_id, "stop_name": "Origin", "stop_lat": 50, "stop_lon": 4},
        {
            "stop_id": "destination",
            "stop_name": "Destination",
            "stop_lat": 50.1,
            "stop_lon": 4.1,
        },
    ]
    if parent_station is not None:
        stops[0]["parent_station"] = parent_station
        stops[1]["parent_station"] = ""
        if parent_station:
            stops.append(
                {
                    "stop_id": parent_station,
                    "stop_name": "Station",
                    "stop_lat": 50,
                    "stop_lon": 4,
                    "parent_station": "",
                }
            )
    write_table(directory, "stops", stops)
    write_table(
        directory,
        "routes",
        [
            {
                "route_id": trip_id,
                "agency_id": trip_id,
                "route_short_name": "14",
                "route_long_name": "Origin - Destination",
                "route_type": 3,
                "route_sort_order": "",
                "route_desc": "",
                "continuous_pickup": "",
                "continuous_drop_off": "",
            }
        ],
    )
    write_table(
        directory,
        "trips",
        [
            {
                "route_id": trip_id,
                "service_id": trip_id,
                "trip_id": trip_id,
                "trip_headsign": "Destination",
                "direction_id": 0,
                "shape_id": trip_id,
                "wheelchair_accessible": "",
                "bikes_allowed": "",
            }
        ],
    )
    write_table(
        directory,
        "stop_times",
        [
            {
                "trip_id": trip_id,
                "stop_id": stop_id,
                "arrival_time": "08:00:00",
                "departure_time": "08:00:00",
                "stop_sequence": 1,
            },
            {
                "trip_id": trip_id,
                "stop_id": "destination",
                "arrival_time": "08:10:00",
                "departure_time": "08:10:00",
                "stop_sequence": 2,
            },
        ],
    )
    write_table(
        directory,
        "shapes",
        [
            {
                "shape_id": trip_id,
                "shape_pt_lat": 50,
                "shape_pt_lon": 4,
                "shape_pt_sequence": 1,
                "shape_dist_traveled": "",
            },
            {
                "shape_id": trip_id,
                "shape_pt_lat": 50.1,
                "shape_pt_lon": 4.1,
                "shape_pt_sequence": 2,
                "shape_dist_traveled": "",
            },
        ],
    )
    write_table(
        directory,
        "calendar",
        [
            {
                "service_id": trip_id,
                **{
                    day: 1
                    for day in (
                        "monday",
                        "tuesday",
                        "wednesday",
                        "thursday",
                        "friday",
                        "saturday",
                        "sunday",
                    )
                },
                "start_date": "20260101",
                "end_date": "20261231",
            }
        ],
    )
    write_table(
        directory,
        "calendar_dates",
        [{"service_id": trip_id, "date": "20261011", "exception_type": 1}],
    )
    write_table(
        directory,
        "translations",
        [{"trans_id": "Origin", "translation": "Origine", "lang": "fr"}],
    )


@pytest.fixture(params=[False, True], ids=["python", "native"])
def loader_path(request, tmp_path, monkeypatch):
    native = request.param
    directory = (
        request.getfixturevalue("native_converter").parent if native else tmp_path
    )
    monkeypatch.setattr(gtfs_loader, "__file__", str(directory / "gtfs_loader.py"))
    read_csv = gtfs_loader.pd.read_csv

    def checked_read_csv(path, *args, **kwargs):
        if native:
            assert (
                str(path).split("/")[-1] != "stop_times.txt"
            ), "Native conversion must not fall back"
        return read_csv(path, *args, **kwargs)

    monkeypatch.setattr(gtfs_loader.pd, "read_csv", checked_read_csv)


@pytest.fixture
def client(monkeypatch):
    async def provider_request(*args, **kwargs):
        return True, "OK", SimpleNamespace(raw_id="test")

    monkeypatch.setattr(main, "handle_provider_request", provider_request)
    monkeypatch.setattr(main, "ensure_provider_loaded", provider_request)
    result = TestClient(main.app)
    yield result
    result.close()


@pytest.mark.parametrize(
    "trip_id,stop_id", [("t1", "s1"), ("NA", "NULL"), ("NULL", "NA"), ("0001", "0002")]
)
@pytest.mark.parametrize("calendar_only_exceptions", [False, True])
@pytest.mark.parametrize("table_translations", [False, True])
def test_linked_identifiers_cold_and_warm(
    tmp_path,
    monkeypatch,
    loader_path,
    client,
    trip_id,
    stop_id,
    calendar_only_exceptions,
    table_translations,
):
    write_feed(tmp_path, trip_id, stop_id)
    if calendar_only_exceptions:
        (tmp_path / "calendar.txt").unlink()
    if table_translations:
        write_table(
            tmp_path,
            "translations",
            [
                {
                    "table_name": "stops",
                    "field_name": "stop_name",
                    "language": "fr",
                    "translation": "Origine",
                    "field_value": "Origin",
                }
            ],
        )
    cold = gtfs_loader.load_feed(tmp_path)
    with monkeypatch.context() as warm_patch:
        warm_patch.setattr(
            gtfs_loader.pd,
            "read_csv",
            Mock(side_effect=AssertionError("Warm load must use cache")),
        )
        warm = gtfs_loader.load_feed(tmp_path)
    assert gtfs_loader.serialize_gtfs_data(cold) == gtfs_loader.serialize_gtfs_data(
        warm
    )
    for feed in (cold, warm):
        assert set(feed.trips) == {trip_id}
        assert set(feed.stop_times_dict) == {trip_id}
        assert set(feed.stops) == {stop_id, "destination", "0007"}
        assert set(feed.agencies) == {trip_id}
        assert feed.agencies[trip_id].agency_lang is None
        assert feed.stops[stop_id].translations == {"fr": "Origine"}
        assert feed.stops[stop_id].parent_station == "0007"
        assert feed.stops["destination"].parent_station is None
        assert [entry["stop_id"] for entry in feed.stop_times_dict[trip_id]] == [
            stop_id,
            "destination",
        ]
        assert len(feed.routes) == 1
        route = feed.routes[0]
        assert (route.route_id, route.trip_id, route.agency_id) == (
            trip_id,
            trip_id,
            trip_id,
        )
        assert route.service_ids == [trip_id]
        assert [entry.service_id for entry in feed.calendar_dates] == [trip_id]
        assert set(feed.calendars) == (set() if calendar_only_exceptions else {trip_id})
        assert route.shape.shape_id == trip_id
        assert [entry.stop.id for entry in route.stops] == [stop_id, "destination"]
        assert route.route_sort_order is None
        assert route.route_desc is None
        assert route.continuous_pickup is None
        assert route.continuous_drop_off is None
        monkeypatch.setattr(main, "feed", feed)
        stations = client.get(
            "/api/test/stations/search", params={"query": "Origine", "language": "fr"}
        )
        assert stations.status_code == 200, stations.text
        assert [station["id"] for station in stations.json()] == [stop_id]
        routes = client.get(
            "/api/test/routes",
            params={
                "from_station": stop_id,
                "to_station": "destination",
                "date": "2026-10-11",
            },
        )
        assert routes.status_code == 200, routes.text
        assert routes.json()["total_routes"] == 1
        result = routes.json()["routes"][0]
        assert result["route_id"] == trip_id
        assert result["duration_minutes"] == 10
        assert [stop["id"] for stop in result["stops"]] == [stop_id, "destination"]
        matches = client.get(
            "/api/test/routes/find", params={"route_name": "Origin - Destination"}
        )
        assert matches.status_code == 200, matches.text
        assert [match["route_id"] for match in matches.json()] == [trip_id]


@pytest.mark.parametrize("parent_station", ["0007", "NA", "NULL", "", None])
def test_optional_parent_station(tmp_path, monkeypatch, loader_path, parent_station):
    write_feed(tmp_path, parent_station=parent_station)
    cold = gtfs_loader.load_feed(tmp_path)
    monkeypatch.setattr(
        gtfs_loader.pd,
        "read_csv",
        Mock(side_effect=AssertionError("Warm load must use cache")),
    )
    warm = gtfs_loader.load_feed(tmp_path)
    for feed in (cold, warm):
        assert feed.stops["s1"].parent_station == (parent_station or None)
        assert feed.routes[0].stops[0].stop.parent_station == (parent_station or None)
        assert feed.stops["destination"].parent_station is None


@pytest.mark.parametrize("previous_version", ["4.0.0.1", "4.0.0.2"])
def test_old_identifier_and_parent_caches_are_rebuilt(
    tmp_path, loader_path, previous_version
):
    write_feed(tmp_path, trip_id="NA", stop_id="NULL")
    feed = gtfs_loader.load_feed(tmp_path)
    # These versions could cache missing parent IDs and routes lost at ID joins.
    feed.stops["NULL"].parent_station = None
    feed.routes.clear()
    (tmp_path / ".gtfs_cache").write_bytes(gtfs_loader.serialize_gtfs_data(feed))
    source_hash = gtfs_loader.calculate_gtfs_hash(tmp_path)
    (tmp_path / ".gtfs_cache_hash").write_text(f"{previous_version}_{source_hash}")
    rebuilt = gtfs_loader.load_feed(tmp_path)
    assert rebuilt.stops["NULL"].parent_station == "0007"
    assert len(rebuilt.routes) == 1
    assert rebuilt.routes[0].trip_id == "NA"
    assert (
        tmp_path / ".gtfs_cache_hash"
    ).read_text().strip() == f"{gtfs_loader.CACHE_VERSION}_{source_hash}"


def test_parent_source_change_invalidates_cache(tmp_path, loader_path):
    write_feed(tmp_path)
    gtfs_loader.load_feed(tmp_path)
    previous_hash = (tmp_path / ".gtfs_cache_hash").read_text()
    stops = tmp_path / "stops.txt"
    stops.write_text(stops.read_text().replace("0007", "0008"))
    feed = gtfs_loader.load_feed(tmp_path)
    assert feed.stops["s1"].parent_station == "0008"
    assert "0008" in feed.stops
    assert (tmp_path / ".gtfs_cache_hash").read_text() != previous_hash


@pytest.mark.parametrize("missing_column", [False, True])
def test_optional_linked_ids(tmp_path, monkeypatch, loader_path, missing_column):
    write_feed(tmp_path)
    for name, column in (("routes", "agency_id"), ("trips", "shape_id")):
        with (tmp_path / f"{name}.txt").open(newline="") as stream:
            rows = list(csv.DictReader(stream))
        if missing_column:
            rows[0].pop(column)
        else:
            rows[0][column] = ""
        write_table(tmp_path, name, rows)
    cold = gtfs_loader.load_feed(tmp_path)
    monkeypatch.setattr(
        gtfs_loader.pd,
        "read_csv",
        Mock(side_effect=AssertionError("Warm load must use cache")),
    )
    warm = gtfs_loader.load_feed(tmp_path)
    for feed in (cold, warm):
        assert feed.routes[0].agency_id is None
        assert feed.routes[0].shape is None
        assert feed.trips["t1"].shape_id is None


@pytest.mark.parametrize(
    "table,old,new",
    [
        ("agency", "Example", "Updated agency"),
        ("translations", "Origine", "Updated translation"),
        ("calendar_dates", "20261011", "20261012"),
    ],
)
def test_optional_source_change_invalidates_cache(
    tmp_path, loader_path, table, old, new
):
    write_feed(tmp_path)
    gtfs_loader.load_feed(tmp_path)
    previous_hash = (tmp_path / ".gtfs_cache_hash").read_text()
    path = tmp_path / f"{table}.txt"
    path.write_text(path.read_text().replace(old, new))
    feed = gtfs_loader.load_feed(tmp_path)
    assert (tmp_path / ".gtfs_cache_hash").read_text() != previous_hash
    if table == "agency":
        assert feed.agencies["t1"].agency_name == new
    elif table == "translations":
        assert feed.stops["s1"].translations == {"fr": new}
    else:
        assert feed.calendar_dates[0].date.strftime("%Y%m%d") == new
