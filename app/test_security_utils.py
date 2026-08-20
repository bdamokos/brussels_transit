from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest

from app.security_utils import (
    build_schedule_explorer_redirect_url,
    is_safe_static_path,
    resolve_provider_asset_directory,
)


def test_schedule_explorer_redirect_keeps_configured_origin_and_encodes_input():
    url = build_schedule_explorer_redirect_url(
        "schedule-explorer",
        8000,
        "mdb-1234",
        "stops?next=//evil.example",
        ("a/b", "value#fragment"),
        {"next": "https://evil.example/%0aLocation: https://other.example"},
    )

    parsed = urlsplit(url)
    assert parsed.scheme == "http"
    assert parsed.netloc == "schedule-explorer:8000"
    assert parsed.path == (
        "/api/mdb-1234/stops%3Fnext%3D%2F%2Fevil.example/"
        "a%2Fb/value%23fragment"
    )
    assert parse_qs(parsed.query) == {
        "next": ["https://evil.example/%0aLocation: https://other.example"]
    }


@pytest.mark.parametrize(
    "provider",
    ("mdb-1@evil.example", "mdb-1/../../etc", "//evil.example", "mdb-anything"),
)
def test_schedule_explorer_redirect_rejects_invalid_provider_ids(provider):
    with pytest.raises(ValueError, match="provider ID"):
        build_schedule_explorer_redirect_url("localhost", 8000, provider, "stops")


def test_provider_asset_directory_comes_from_registered_allowlist(tmp_path):
    providers_root = tmp_path / "transit_providers"
    registered = {"be/stib": Path("be/stib")}

    assert resolve_provider_asset_directory(
        providers_root, "be/stib", "js", registered
    ) == (providers_root / "be/stib/js").resolve()

    with pytest.raises(KeyError):
        resolve_provider_asset_directory(
            providers_root, "../../etc", "js", registered
        )

    with pytest.raises(ValueError, match="escapes its root"):
        resolve_provider_asset_directory(
            providers_root,
            "bad/provider",
            "js",
            {"bad/provider": Path("../../etc")},
        )


def test_static_path_rejects_traversal_and_symlink_escape(tmp_path):
    assets = tmp_path / "assets"
    assets.mkdir()
    script = assets / "provider.js"
    script.write_text("export default {};", encoding="utf-8")
    outside = tmp_path / "secret.js"
    outside.write_text("secret", encoding="utf-8")
    (assets / "linked.js").symlink_to(outside)

    assert is_safe_static_path(assets, "provider.js", {".js"})
    assert not is_safe_static_path(assets, "../secret.js", {".js"})
    assert not is_safe_static_path(assets, "linked.js", {".js"})
    assert not is_safe_static_path(assets, "provider.js", {".css"})
