import importlib.util
import os
import sys
from pathlib import Path

_APP_DIR = Path(__file__).resolve().parents[2]
os.environ.setdefault("PROJECT_ROOT", str(_APP_DIR))
if str(_APP_DIR) not in sys.path:
    sys.path.insert(0, str(_APP_DIR))

_MODULE_PATH = Path(__file__).with_name("mobility.py")
_SPEC = importlib.util.spec_from_file_location("mobility_under_test", _MODULE_PATH)
mobility = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(mobility)

mobility_apim_base_url = mobility.mobility_apim_base_url
mobility_subscription_headers = mobility.mobility_subscription_headers


def test_mobility_apim_base_url_reads_top_level_config(monkeypatch):
    monkeypatch.delenv("MOBILITY_APIM_BASE_URL", raising=False)

    def fake_get_config(key, default=None):
        values = {"MOBILITY_APIM_BASE_URL": "https://example.test/"}
        return values.get(key, default)

    monkeypatch.setattr(mobility, "get_config", fake_get_config)

    assert mobility_apim_base_url() == "https://example.test"


def test_mobility_subscription_headers_reads_top_level_config(monkeypatch):
    monkeypatch.delenv("MOBILITY_API_PRIMARY_KEY", raising=False)
    monkeypatch.delenv("MOBILITY_API_SECONDARY_KEY", raising=False)

    def fake_get_config(key, default=None):
        values = {"MOBILITY_API_PRIMARY_KEY": "top-level-key"}
        return values.get(key, default)

    monkeypatch.setattr(mobility, "get_config", fake_get_config)
    monkeypatch.setattr(mobility, "get_provider_config", lambda provider: {})

    assert mobility_subscription_headers("sncb") == {
        "Ocp-Apim-Subscription-Key": "top-level-key",
        "bmc-partner-key": "top-level-key"
    }
