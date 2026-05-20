import os
from pathlib import Path

import pytest
from fastapi import HTTPException

os.environ.setdefault("PROJECT_ROOT", str(Path(__file__).resolve().parents[4]))
os.environ.setdefault("CACHE_DIR", str(Path(os.environ["PROJECT_ROOT"]) / "cache"))
os.environ.setdefault("DOWNLOADS_DIR", str(Path(os.environ["PROJECT_ROOT"]) / "downloads"))
os.environ.setdefault("LOGS_DIR", str(Path(os.environ["PROJECT_ROOT"]) / "logs"))

from ..main import check_client_connected


class ConnectedRequest:
    async def is_disconnected(self):
        return False


@pytest.mark.asyncio
async def test_check_client_connected_preserves_http_exceptions():
    with pytest.raises(HTTPException) as exc_info:
        async with check_client_connected(ConnectedRequest(), "test operation"):
            raise HTTPException(status_code=404, detail="not found")

    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == "not found"
