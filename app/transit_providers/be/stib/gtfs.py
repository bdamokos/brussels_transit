"""Download STIB GTFS static data from the Belgian Mobility Open Data Portal."""

import io
import json
import logging
import zipfile

import niquests as requests
from transit_providers.config import get_provider_config

from .mobility import mobility_subscription_headers

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
            headers = mobility_subscription_headers()
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
    downloaded = list(GTFS_DIR.glob("*.txt")) if GTFS_DIR else []
    return bool(GTFS_DIR and (GTFS_DIR / "stops.txt").exists())


def download_gtfs_data():
    """Fetch STIB GTFS from the mobility portal (ZIP feed or legacy JSON file list)."""
    try:
        headers = mobility_subscription_headers()
        if not headers:
            logger.error(
                "MOBILITY_API_PRIMARY_KEY (or STIB_API_KEY) is required for GTFS download"
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

        zf.extractall(GTFS_DIR)
        zf.close()

        downloaded_files = list(GTFS_DIR.glob("*.txt"))
        logger.info(f"Extracted GTFS files: {[f.name for f in downloaded_files]}")

        if not (GTFS_DIR / "stops.txt").exists():
            logger.error(
                "stops.txt not found after extract. Files: "
                f"{[f.name for f in downloaded_files]}"
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
    if not all((GTFS_DIR / file).exists() for file in (GTFS_USED_FILES or [])):
        return download_gtfs_data()
    return True


if __name__ == "__main__":
    download_gtfs_data()
