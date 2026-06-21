"""Belgian Mobility Open Data Portal (Azure API Management) helpers."""

import os
from typing import Dict, Iterable

from config import get_config
from transit_providers.config import get_provider_config

_DEFAULT_APIM = "https://api-management-opendata-production.azure-api.net"


def mobility_apim_base_url() -> str:
    return (
        os.getenv("MOBILITY_APIM_BASE_URL")
        or get_config("MOBILITY_APIM_BASE_URL")
        or _DEFAULT_APIM
    ).rstrip("/")


def mobility_url(path: str) -> str:
    """Join the APIM base URL with an absolute path."""
    if not path.startswith("/"):
        path = "/" + path
    return f"{mobility_apim_base_url()}{path}"


def mobility_subscription_headers(
    provider_name: str | None = None,
    legacy_env_keys: Iterable[str] = (),
    legacy_config_keys: Iterable[str] = (),
) -> Dict[str, str]:
    """Return the Belgian Mobility subscription header, if a key is configured."""
    key = (
        os.getenv("MOBILITY_API_PRIMARY_KEY")
        or os.getenv("MOBILITY_API_SECONDARY_KEY")
        or get_config("MOBILITY_API_PRIMARY_KEY")
        or get_config("MOBILITY_API_SECONDARY_KEY")
    )

    if not key:
        for env_key in legacy_env_keys:
            key = os.getenv(env_key)
            if key:
                break

    if not key and provider_name:
        pc = get_provider_config(provider_name) or {}
        key = pc.get("MOBILITY_API_PRIMARY_KEY") or pc.get(
            "MOBILITY_API_SECONDARY_KEY"
        )
        if not key:
            for config_key in legacy_config_keys:
                key = pc.get(config_key)
                if key:
                    break

    if not key:
        return {}
    return {
        "Ocp-Apim-Subscription-Key": key,
        "bmc-partner-key": key,
    }
