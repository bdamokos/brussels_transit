"""Offline checks for the installed CA bundle used by default HTTPX clients."""

import asyncio
import ssl

import certifi
import httpx
import pytest


def _assert_safe_context(context):
    assert context.verify_mode == ssl.CERT_REQUIRED
    assert context.check_hostname
    certificates = context.get_ca_certs()
    assert certificates
    common_names = {
        value
        for certificate in certificates
        for rdn in certificate["subject"]
        for key, value in rdn
        if key == "commonName"
    }
    assert "emSign ECC Root CA - G3" not in common_names


def test_installed_certifi_excludes_compromised_root():
    _assert_safe_context(ssl.create_default_context(cafile=certifi.where()))


@pytest.mark.parametrize("asynchronous", [False, True])
def test_default_httpx_clients_use_safe_certifi(monkeypatch, asynchronous):
    # Exercise the default bundle, independently of a developer's CA overrides.
    monkeypatch.delenv("SSL_CERT_FILE", raising=False)
    monkeypatch.delenv("SSL_CERT_DIR", raising=False)
    original = ssl.create_default_context
    contexts = []

    def capture_context(*args, **kwargs):
        context = original(*args, **kwargs)
        contexts.append((kwargs.get("cafile"), context))
        return context

    monkeypatch.setattr(ssl, "create_default_context", capture_context)

    async def open_async_client():
        async with httpx.AsyncClient():
            pass

    if asynchronous:
        asyncio.run(open_async_client())
    else:
        with httpx.Client():
            pass

    assert contexts
    for cafile, context in contexts:
        assert cafile == certifi.where()
        _assert_safe_context(context)
