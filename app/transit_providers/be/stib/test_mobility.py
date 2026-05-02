"""Unit tests for Belgian Mobility APIM URL helpers (no network)."""

import pytest

from .mobility import mobility_apim_base_url, mobility_url


def test_mobility_url_joins_base(monkeypatch):
    monkeypatch.delenv("MOBILITY_APIM_BASE_URL", raising=False)
    assert mobility_apim_base_url().endswith("azure-api.net")
    assert mobility_url("/api/datasets/stibmivb/rt/WaitingTimes").endswith(
        "/api/datasets/stibmivb/rt/WaitingTimes"
    )


def test_mobility_apim_base_override(monkeypatch):
    monkeypatch.setenv("MOBILITY_APIM_BASE_URL", "https://example.com/")
    assert mobility_apim_base_url() == "https://example.com"
    assert mobility_url("/x") == "https://example.com/x"


def test_mobility_url_accepts_path_without_leading_slash(monkeypatch):
    monkeypatch.setenv("MOBILITY_APIM_BASE_URL", "https://example.com")
    assert mobility_url("api/v") == "https://example.com/api/v"
