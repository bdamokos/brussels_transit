"""Build the native converter in a private directory for offline tests."""

from pathlib import Path
import shutil
import subprocess

import pytest


@pytest.fixture(scope="session")
def native_converter(tmp_path_factory):
    build = tmp_path_factory.mktemp("native-converter")
    source = Path(__file__).parent
    for name in ("gtfs_precache.c", "gtfs_precache_version.h", "Makefile"):
        shutil.copyfile(source / name, build / name)
    subprocess.run(
        ["make", "-C", str(build)], check=True, capture_output=True, text=True
    )
    return build / "gtfs_precache"
