"""TLS trust-store helpers shared by discovery, validation and the gateway.

Frozen Windows builds and the Android/Chaquopy runtime do not necessarily
inherit the host OpenSSL trust store.  ``certifi`` ships a CA bundle with the
app, so point OpenSSL at it before any default SSL context is created.
"""

from __future__ import annotations

import os
import ssl

_CA_PATH: str | None = None


def configure_ca_bundle() -> str | None:
    """Expose the bundled certifi CA file to OpenSSL/aiohttp/requests.

    Returns the CA path when certifi is available, otherwise ``None`` (the
    platform default trust store is used).
    """
    global _CA_PATH
    if _CA_PATH is not None:
        return _CA_PATH or None
    try:
        import certifi

        path = certifi.where()
    except Exception:  # noqa: BLE001 - certifi is optional on source checkouts
        _CA_PATH = ""
        return None
    if path and os.path.isfile(path):
        os.environ.setdefault("SSL_CERT_FILE", path)
        os.environ.setdefault("REQUESTS_CA_BUNDLE", path)
        _CA_PATH = path
        return path
    _CA_PATH = ""
    return None


def make_ssl_context() -> ssl.SSLContext:
    """Create a client SSL context that trusts the bundled CA bundle."""
    path = configure_ca_bundle()
    if path:
        try:
            return ssl.create_default_context(cafile=path)
        except (OSError, ssl.SSLError):
            pass
    return ssl.create_default_context()
