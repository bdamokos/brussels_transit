"""Belgian Mobility Open Data Portal (Azure API Management) helpers."""

import os
from typing import Dict

from transit_providers.config import get_provider_config

_DEFAULT_APIM = "https://api-management-opendata-production.azure-api.net"


def mobility_apim_base_url() -> str:
    return os.getenv("MOBILITY_APIM_BASE_URL", _DEFAULT_APIM).rstrip("/")


def mobility_subscription_headers() -> Dict[str, str]:
    """Subscription key from env, then merged STIB provider config (e.g. local.py)."""
    key = (
        os.getenv("MOBILITY_API_PRIMARY_KEY")
        or os.getenv("MOBILITY_API_SECONDARY_KEY")
        or os.getenv("STIB_API_KEY")
    )
    if not key:
        pc = get_provider_config("stib")
        key = (
            (pc.get("MOBILITY_API_PRIMARY_KEY") or "")
            or (pc.get("MOBILITY_API_SECONDARY_KEY") or "")
            or (pc.get("API_KEY") or "")
        )
    if not key:
        return {}
    return {"Ocp-Apim-Subscription-Key": key}


def mobility_url(path: str) -> str:
    """Join base URL with an absolute path (e.g. /api/datasets/stibmivb/rt/WaitingTimes)."""
    if not path.startswith("/"):
        path = "/" + path
    return f"{mobility_apim_base_url()}{path}"
