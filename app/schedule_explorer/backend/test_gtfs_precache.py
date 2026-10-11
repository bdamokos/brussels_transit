"""Offline regressions for the native stop-times converter."""

import csv
import itertools
import subprocess

import msgpack
import pytest

from . import gtfs_loader

FIELDS = ("trip_id", "arrival_time", "departure_time", "stop_id", "stop_sequence")
ROW = dict(zip(FIELDS, ("trip-1", "25:00:00", "25:01:00", "stop-1", 2)))


def convert(binary, directory):
    output = directory / "stop_times.msgpack"
    result = subprocess.run(
        [str(binary), str(directory / "stop_times.txt"), str(output)],
        capture_output=True,
        text=True,
        timeout=10,
    )
    return result, output


def write_rows(directory, fields, rows, **kwargs):
    with (directory / "stop_times.txt").open(
        "w", encoding="utf-8", newline=""
    ) as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, **kwargs)
        writer.writeheader()
        writer.writerows(rows)


@pytest.mark.parametrize("fields", list(itertools.permutations(FIELDS)))
def test_every_required_column_order(native_converter, tmp_path, fields):
    write_rows(tmp_path, fields, [ROW])
    result, output = convert(native_converter, tmp_path)
    assert result.returncode == 0, result.stderr
    assert msgpack.unpackb(output.read_bytes(), raw=False) == {"stop_times": [ROW]}


@pytest.mark.parametrize("quoting", [csv.QUOTE_MINIMAL, csv.QUOTE_ALL])
@pytest.mark.parametrize("bom", [False, True])
def test_native_and_python_equivalence(
    native_converter, tmp_path, monkeypatch, quoting, bom
):
    fields = [f"extra_{i}" for i in range(14)] + list(reversed(FIELDS))
    rows = [
        {
            **ROW,
            "trip_id": 'trip,"one"',
            "stop_id": 'stop,"one"',
            "extra_0": "x" * 4096,
        },
        {
            **ROW,
            "trip_id": 'trip,"one"',
            "stop_id": "árvíz",
            "stop_sequence": 1,
            "extra_1": 'a quoted\nfield with "quotes"',
        },
        {
            **ROW,
            "trip_id": "NA",
            "stop_id": "NULL",
            "arrival_time": "",
            "departure_time": "",
        },
    ]
    write_rows(tmp_path, fields, rows, quoting=quoting)
    path = tmp_path / "stop_times.txt"
    data = path.read_bytes().rstrip(b"\r\n")  # Final record need not have a newline.
    path.write_bytes((b"\xef\xbb\xbf" if bom else b"") + data)

    result, output = convert(native_converter, tmp_path)
    assert result.returncode == 0, result.stderr
    expected = [{key: row[key] for key in FIELDS} for row in rows]
    assert msgpack.unpackb(output.read_bytes(), raw=False)["stop_times"] == expected

    # Exercise the actual loader branches without renaming any shared executable.
    monkeypatch.setattr(
        gtfs_loader, "__file__", str(native_converter.parent / "gtfs_loader.py")
    )
    native = gtfs_loader.load_stop_times(tmp_path)
    monkeypatch.setattr(gtfs_loader, "__file__", str(tmp_path / "gtfs_loader.py"))
    python = gtfs_loader.load_stop_times(tmp_path)
    assert native == python
    assert [row["stop_sequence"] for row in native['trip,"one"']] == [1, 2]


@pytest.mark.parametrize(
    "content",
    [
        "",
        "trip_id,stop_id,arrival_time,departure_time\nt1,s1,08:00:00,08:00:00\n",
        "trip_id,arrival_time,departure_time,stop_id,stop_sequence\nt1,08:00:00,08:00:00,s1\n",
        "trip_id,arrival_time,departure_time,stop_id,stop_sequence\nt1,08:00:00,08:00:00,s1,\n",
        "trip_id,arrival_time,departure_time,stop_id,stop_sequence\nt1,08:00:00,08:00:00,s1,-1\n",
        "trip_id,arrival_time,departure_time,stop_id,stop_sequence\nt1,08:00:00,08:00:00,s1,99999999999999999999999\n",
        'trip_id,arrival_time,departure_time,stop_id,stop_sequence\n"unclosed,08:00:00,08:00:00,s1,1\n',
    ],
)
def test_invalid_input_does_not_write_a_cache(native_converter, tmp_path, content):
    (tmp_path / "stop_times.txt").write_text(content)
    result, output = convert(native_converter, tmp_path)
    assert result.returncode != 0
    assert not output.exists()


def test_blank_lines_and_header_only(native_converter, tmp_path):
    write_rows(tmp_path, FIELDS, [ROW])
    with (tmp_path / "stop_times.txt").open("a") as stream:
        stream.write("\n  \n\t\n")
    result, output = convert(native_converter, tmp_path)
    assert result.returncode == 0, result.stderr
    assert msgpack.unpackb(output.read_bytes(), raw=False)["stop_times"] == [ROW]
    write_rows(tmp_path, FIELDS, [])
    result, output = convert(native_converter, tmp_path)
    assert result.returncode == 0, result.stderr
    assert msgpack.unpackb(output.read_bytes(), raw=False)["stop_times"] == []
