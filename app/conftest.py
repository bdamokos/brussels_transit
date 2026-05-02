"""Pytest: PROJECT_ROOT required by provider config modules."""

import os
from pathlib import Path

os.environ.setdefault(
    "PROJECT_ROOT",
    str(Path(__file__).resolve().parent),
)
