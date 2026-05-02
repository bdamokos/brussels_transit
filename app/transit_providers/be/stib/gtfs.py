"""Download STIB GTFS static data from the Belgian Mobility Open Data Portal."""

import io
import json
import logging
import os
import zipfile
from pathlib import Path
from urllib.parse import urlparse

import niquests as requests
from transit_providers.config import get_provider_config

from .mobility import mobility_apim_base_url, mobility_subscription_headers

logger = logging.getLogger("stib.gtfs")

provider_config = get_provider_config("stib")
logger.debug(f"Provider config: {provider_config}")

GTFS_DIR = provider_config.get("GTFS_DIR")
GTFS_STATIC_FEED_URL = provider_config.get(
    "GTFS_STATIC_FEED_URL"
) or provider_config.get("GTFS_API_URL")
GTFS_USED_FILES = provider_config.get("GTFS_USED_FILES")
if GTFS_DIR is not None:
    GTFS_DIR.mkdir(parents=True, exist_ok=True)


def _required_gtfs_filenames() -> list[str]:
    if GTFS_USED_FILES:
        return list(GTFS_USED_FILES)
    return ["stops.txt"]


def _missing_required_gtfs_files() -> list[str]:
    req = _required_gtfs_filenames()
    if GTFS_DIR is None:
        return req
    return [name for name in req if not (GTFS_DIR / name).exists()]


def _trusted_download_netlocs() -> set[str]:
    """Hosts allowed to receive subscription headers on follow-up file downloads."""
    out = {urlparse(mobility_apim_base_url()).netloc.lower()}
    extra = os.getenv("MOBILITY_TRUSTED_FILE_HOSTS", "")
    for part in extra.split(","):
        p = part.strip().lower()
        if p:
            out.add(p)
    return out


def _headers_for_file_url(file_url: str) -> dict:
    """HTTPS + trusted host only — never send the subscription key over plain HTTP."""
    parsed = urlparse(file_url)
    if parsed.scheme != "https" or not parsed.netloc:
        return {}
    if parsed.netloc.lower() in _trusted_download_netlocs():
        return mobility_subscription_headers()
    return {}


def _safe_extract_zip(zf: zipfile.ZipFile, dest_dir) -> None:
    """Extract ZIP members under dest_dir only (mitigates Zip Slip)."""
    dest_root = Path(dest_dir).resolve()
    for member in zf.infolist():
        name = member.filename
        if name.endswith("/") or not name:
            continue
        target = (dest_root / name).resolve()
        try:
            target.relative_to(dest_root)
        except ValueError:
            logger.warning("Skipping ZIP entry outside GTFS dir: %s", name)
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        with zf.open(member, "r") as src, open(target, "wb") as out_f:
            out_f.write(src.read())


def _download_via_ods_file_list(data: dict) -> bool:
    """Legacy: JSON listing of GTFS files (OpenDataSoft-style)."""
    files = data.get("results", [])
    for file_data in files:
        try:
            file_info = file_data.get("file", {})
            filename = file_info.get("filename")
            file_url = file_info.get("url")
            if not filename or not file_url or not GTFS_DIR:
                logger.error(f"Missing filename or URL in file data: {file_data}")
                continue
            if filename not in (GTFS_USED_FILES or []):
                logger.debug(f"Skipping unused file: {filename}")
                continue
            logger.info(f"Downloading {filename} from {file_url}")
            headers = _headers_for_file_url(file_url)
            file_response = requests.get(file_url, headers=headers, timeout=120)
            if file_response.status_code != 200:
                logger.error(
                    f"Failed to download {filename}: {file_response.status_code}"
                )
                continue
            file_path = GTFS_DIR / filename
            file_path.write_bytes(file_response.content)
            logger.info(f"Successfully downloaded {filename} to {file_path}")
        except Exception as e:
            logger.error(f"Error downloading file from listing: {e}")
            continue
    missing = _missing_required_gtfs_files()
    if missing:
        logger.error("Missing GTFS files after JSON listing download: %s", missing)
        return False
    return True


def download_gtfs_data():
    """Fetch STIB GTFS from the mobility portal (ZIP feed or legacy JSON file list)."""
    try:
        headers = mobility_subscription_headers()
        if not headers:
            logger.error(
                "MOBILITY_API_PRIMARY_KEY, MOBILITY_API_SECONDARY_KEY, or STIB_API_KEY "
                "is required for GTFS download"
            )
            return False
        if not GTFS_STATIC_FEED_URL or not GTFS_DIR:
            logger.error("GTFS_STATIC_FEED_URL or GTFS_DIR is not configured")
            return False

        logger.info("Downloading STIB GTFS from %s", GTFS_STATIC_FEED_URL)
        response = requests.get(
            GTFS_STATIC_FEED_URL,
            headers=headers,
            timeout=300,
        )
        if response.status_code != 200:
            logger.error(
                "Failed to get GTFS feed: %s %s",
                response.status_code,
                response.text[:800],
            )
            return False

        ctype = (response.headers.get("content-type") or "").lower()
        if "json" in ctype or response.content[:1] == b"{":
            try:
                data = response.json()
            except json.JSONDecodeError:
                logger.error("GTFS endpoint returned non-JSON, non-ZIP body")
                return False
            return _download_via_ods_file_list(data)

        try:
            zf = zipfile.ZipFile(io.BytesIO(response.content))
        except zipfile.BadZipFile:
            logger.error(
                "GTFS response was not a valid ZIP (content-type=%s)",
                ctype or "unknown",
            )
            return False

        _safe_extract_zip(zf, GTFS_DIR)
        zf.close()

        downloaded_files = list(GTFS_DIR.glob("*.txt"))
        logger.info(f"Extracted GTFS files: {[f.name for f in downloaded_files]}")

        missing = _missing_required_gtfs_files()
        if missing:
            logger.error(
                "Missing GTFS files after extract: %s. Present: %s",
                missing,
                [f.name for f in downloaded_files],
            )
            return False
        return True

    except Exception as e:
        logger.error(f"Error in download_gtfs_data: {e}")
        import traceback

        logger.error(traceback.format_exc())
        return False


def ensure_gtfs_data():
    """Ensures the GTFS data is downloaded and available."""
    if not GTFS_DIR:
        return False
    if not (GTFS_DIR / "stops.txt").exists():
        return download_gtfs_data()
    used = GTFS_USED_FILES or []
    if not used:
        return True
    if not all((GTFS_DIR / file).exists() for file in used):
        return download_gtfs_data()
    return True


if __name__ == "__main__":
    download_gtfs_data()
