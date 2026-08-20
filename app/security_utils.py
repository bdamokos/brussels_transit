"""Security boundaries shared by the legacy Flask application."""

import re
from pathlib import Path
from typing import Mapping, Optional, Tuple, Union
from urllib.parse import quote, urlencode, urlsplit, urlunsplit


PROVIDER_ID_PATTERN = re.compile(r"^[a-zA-Z]+-\d+$")
ALLOWED_PROVIDER_ASSET_TYPES = {"css", "js"}


def build_schedule_explorer_redirect_url(
    host: str,
    port: Union[int, str],
    provider: str,
    endpoint: str,
    path_parameters: Tuple[str, ...] = (),
    query_parameters: Optional[Mapping[str, str]] = None,
) -> str:
    """Build a redirect whose origin comes only from trusted configuration."""
    if not PROVIDER_ID_PATTERN.fullmatch(provider):
        raise ValueError("Invalid Mobility Database provider ID")

    configured_host = str(host).strip()
    if (
        not configured_host
        or any(character.isspace() for character in configured_host)
        or any(character in configured_host for character in "/?#@\\")
    ):
        raise ValueError("Invalid Schedule Explorer host")

    hostname = configured_host
    if hostname.startswith("[") and hostname.endswith("]"):
        hostname = hostname[1:-1]
    url_host = f"[{hostname}]" if ":" in hostname else hostname

    configured_port = int(port)
    if not 1 <= configured_port <= 65535:
        raise ValueError("Invalid Schedule Explorer port")

    components = (provider, endpoint, *path_parameters)
    path = "/api/" + "/".join(quote(str(component), safe="") for component in components)
    query = urlencode(query_parameters or {})
    relative_target = urlunsplit(("", "", path, query, ""))

    # Keep the user-controlled part relative. This rejects browser URL forms that
    # could otherwise replace the configured origin.
    parsed_target = urlsplit(relative_target.replace("\\", ""))
    if (
        parsed_target.scheme
        or parsed_target.netloc
        or not parsed_target.path.startswith("/api/")
    ):
        raise ValueError("Unsafe Schedule Explorer redirect target")

    configured_origin = urlunsplit(
        ("http", f"{url_host}:{configured_port}", "", "", "")
    )
    return configured_origin + relative_target


def resolve_provider_asset_directory(
    providers_root: Union[str, Path],
    requested_provider_path: str,
    asset_type: str,
    registered_provider_paths: Mapping[str, Union[str, Path]],
) -> Path:
    """Resolve an asset directory from the registered provider allowlist."""
    if asset_type not in ALLOWED_PROVIDER_ASSET_TYPES:
        raise ValueError("Unsupported provider asset type")

    registered_path = registered_provider_paths.get(requested_provider_path)
    if registered_path is None:
        raise KeyError(requested_provider_path)

    registered_path = Path(registered_path)
    if registered_path.is_absolute():
        raise ValueError("Registered provider paths must be relative")

    root = Path(providers_root).resolve()
    directory = (root / registered_path / asset_type).resolve()
    try:
        directory.relative_to(root)
    except ValueError as error:
        raise ValueError("Provider asset directory escapes its root") from error
    return directory


def is_safe_static_path(
    base_directory: Union[str, Path],
    filename: str,
    allowed_extensions: set[str],
) -> bool:
    """Return whether a requested static file resolves inside its base directory."""
    if not filename:
        return False

    base_path = Path(base_directory).resolve()
    file_path = (base_path / filename).resolve()
    try:
        file_path.relative_to(base_path)
    except ValueError:
        return False

    return file_path.suffix.lower() in allowed_extensions and file_path.is_file()
