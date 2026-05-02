"""Unit tests for Belgian Mobility APIM URL helpers (no network)."""

from urllib.parse import urlparse

import pytest

from . import mobility as mobility_mod
from .mobility import mobility_apim_base_url, mobility_subscription_headers, mobility_url


def test_mobility_url_joins_base(monkeypatch):
    monkeypatch.delenv("MOBILITY_APIM_BASE_URL", raising=False)
    expected_base = "https://api-management-opendata-production.azure-api.net"
    assert mobility_apim_base_url() == expected_base
    waiting = mobility_url("/api/datasets/stibmivb/rt/WaitingTimes")
    assert waiting == f"{expected_base}/api/datasets/stibmivb/rt/WaitingTimes"
    parsed = urlparse(waiting)
    assert parsed.scheme == "https"
    assert parsed.netloc == "api-management-opendata-production.azure-api.net"
    assert parsed.path == "/api/datasets/stibmivb/rt/WaitingTimes"


def test_mobility_apim_base_override(monkeypatch):
    monkeypatch.setenv("MOBILITY_APIM_BASE_URL", "https://example.com/")
    assert mobility_apim_base_url() == "https://example.com"
    assert mobility_url("/x") == "https://example.com/x"


def test_mobility_url_accepts_path_without_leading_slash(monkeypatch):
    monkeypatch.setenv("MOBILITY_APIM_BASE_URL", "https://example.com")
    assert mobility_url("api/v") == "https://example.com/api/v"


def test_mobility_subscription_headers_from_provider_config(monkeypatch):
    monkeypatch.delenv("MOBILITY_API_PRIMARY_KEY", raising=False)
    monkeypatch.delenv("MOBILITY_API_SECONDARY_KEY", raising=False)
    monkeypatch.delenv("STIB_API_KEY", raising=False)

    def fake_pc(name: str):
        assert name == "stib"
        return {"MOBILITY_API_PRIMARY_KEY": "k-from-provider-config"}

    monkeypatch.setattr(mobility_mod, "get_provider_config", fake_pc)
    assert mobility_subscription_headers() == {
        "Ocp-Apim-Subscription-Key": "k-from-provider-config",
    }
