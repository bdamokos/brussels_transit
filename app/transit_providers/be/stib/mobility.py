"""Belgian Mobility Open Data Portal (Azure API Management) helpers."""

import os
from typing import Dict

_DEFAULT_APIM = "https://api-management-opendata-production.azure-api.net"


def mobility_apim_base_url() -> str:
    return os.getenv("MOBILITY_APIM_BASE_URL", _DEFAULT_APIM).rstrip("/")


def mobility_subscription_headers() -> Dict[str, str]:
    """Subscription key: primary, secondary (rotation), then legacy STIB_API_KEY."""
    key = (
        os.getenv("MOBILITY_API_PRIMARY_KEY")
        or os.getenv("MOBILITY_API_SECONDARY_KEY")
        or os.getenv("STIB_API_KEY")
    )
    if not key:
        return {}
    return {"Ocp-Apim-Subscription-Key": key}


def mobility_url(path: str) -> str:
    """Join base URL with an absolute path (e.g. /api/datasets/stibmivb/rt/WaitingTimes)."""
    if not path.startswith("/"):
        path = "/" + path
    return f"{mobility_apim_base_url()}{path}"
