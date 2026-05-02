"""Pytest: PROJECT_ROOT must match runtime (see start.py / app layout)."""

import os
from pathlib import Path

_REPO = Path(__file__).resolve().parent
_APP = _REPO / "app"
os.environ.setdefault("PROJECT_ROOT", str(_APP))
# Logging handlers in config/default.py expect this directory
(_APP / "logs").mkdir(parents=True, exist_ok=True)
