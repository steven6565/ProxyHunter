"""Parsing, validation and small helper functions.

Everything in here is deliberately dependency-free so it also runs on
minimal Android/Termux installations.
"""

from __future__ import annotations

import ipaddress
import re
from typing import Iterable, Optional
from urllib.parse import urlparse

from .models import Proxy, SUPPORTED_PROTOCOLS

_IPV4 = r"(?:\d{1,3}\.){3}\d{1,3}"
_IPV6 = r"\[[0-9A-Fa-f:.]+\]"
_DOMAIN = r"[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?)+"
PROXY_RE = re.compile(
    r"(?:(?P<proto>https?|socks4|socks5)://)?"
    r"(?P<host>" + _IPV4 + r"|" + _IPV6 + r"|" + _DOMAIN + r")"
    r"(?::(?P<port>\d{1,5}))?",
    re.IGNORECASE,
)

# Country names for the codes we care about most (used by the dashboard and
# when the GeoIP database only provides an ISO code).
COUNTRY_NAMES = {
    "US": "United States", "GB": "United Kingdom", "IN": "India",
    "DE": "Germany", "CA": "Canada", "FR": "France", "JP": "Japan",
    "SG": "Singapore", "NL": "Netherlands", "AU": "Australia",
    "BR": "Brazil", "RU": "Russia", "CN": "China", "KR": "South Korea",
    "IT": "Italy", "ES": "Spain", "TR": "Turkey", "ID": "Indonesia",
    "VN": "Vietnam", "PL": "Poland", "UA": "Ukraine", "MX": "Mexico",
    "ZA": "South Africa", "SE": "Sweden", "CH": "Switzerland",
    "XX": "Unknown", "SA": "Saudi Arabia", "UZ": "Uzbekistan",
    "AL": "Albania", "KH": "Cambodia", "HK": "Hong Kong",
    "TW": "Taiwan", "MY": "Malaysia", "TH": "Thailand",
    "PH": "Philippines", "PK": "Pakistan", "BD": "Bangladesh",
    "NG": "Nigeria", "EG": "Egypt", "AE": "United Arab Emirates",
    "IL": "Israel", "CZ": "Czechia", "RO": "Romania", "HU": "Hungary",
    "GR": "Greece", "PT": "Portugal", "IE": "Ireland", "BE": "Belgium",
    "AT": "Austria", "DK": "Denmark", "FI": "Finland", "NO": "Norway",
    "NZ": "New Zealand", "CL": "Chile", "AR": "Argentina", "CO": "Colombia",
}
_ALIASES = {"UK": "GB", "ENG": "GB", "ENGLAND": "GB", "USA": "US", "U.S.": "US"}


def normalize_country_code(code: str) -> str:
    """Normalise a country code to ISO 3166-1 alpha-2 (UK -> GB)."""
    value = (code or "").strip().upper()
    return _ALIASES.get(value, value)


def country_name(code: str, fallback: str = "") -> str:
    code = normalize_country_code(code)
    return COUNTRY_NAMES.get(code, fallback or code or "Unknown")


def normalize_protocol(value: str, default: str = "http") -> str:
    proto = (value or "").strip().lower().rstrip(":")
    if proto in ("socks", "socks5h"):
        return "socks5"
    if proto in ("socks4a",):
        return "socks4"
    return proto if proto in SUPPORTED_PROTOCOLS else default


def is_public_ip(value: str) -> bool:
    """Return True only for globally routable unicast addresses.

    Private, loopback, link-local, reserved, multicast and unspecified
    ranges are rejected so a remote list can never point us at the local
    network (basic SSRF protection).
    """
    try:
        ip = ipaddress.ip_address(str(value).strip().strip("[]"))
    except (ValueError, TypeError):
        return False
    if ip.version == 4:
        # Extra conservative blocks not always covered by is_private.
        first = int(str(ip).split(".")[0])
        if first in (0, 127) or str(ip).startswith("169.254."):
            return False
    return not (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
    )


def parse_proxy(raw: str, default_protocol: str = "http", source: str = "") -> Optional[Proxy]:
    """Parse one proxy definition. Returns ``None`` when it is unusable."""
    if not raw:
        return None
    text = str(raw).strip().strip(",;\"'")
    if not text or text.startswith("#"):
        return None
    # Strip common prefixes found in pasted lists.
    text = re.sub(r"^(?:proxy|proxylist|list)[:\s]+", "", text, flags=re.I).strip()

    match = PROXY_RE.search(text)
    if not match:
        return None
    port_raw = match.group("port")
    if not port_raw:
        return None
    try:
        port = int(port_raw)
    except (TypeError, ValueError):
        return None
    if not 1 <= port <= 65535:
        return None

    host = match.group("host").strip("[]").lower()
    proto = normalize_protocol(match.group("proto"), default_protocol)

    if _looks_like_ip(host):
        if not is_public_ip(host):
            return None
    elif not re.fullmatch(_DOMAIN, host):
        return None

    return Proxy(host=host, port=port, protocol=proto, source=source)


def _looks_like_ip(host: str) -> bool:
    try:
        ipaddress.ip_address(host)
        return True
    except ValueError:
        return False


def extract_proxies(text: str, default_protocol: str = "http", source: str = "") -> list[Proxy]:
    """Pull every valid proxy out of an arbitrary block of text."""
    if not text:
        return []
    found: list[Proxy] = []
    for match in PROXY_RE.finditer(str(text)):
        port_raw = match.group("port")
        if not port_raw:
            continue
        proxy = parse_proxy(match.group(0), default_protocol=default_protocol, source=source)
        if proxy is not None:
            found.append(proxy)
    return found


def deduplicate(proxies: Iterable[Proxy]) -> list[Proxy]:
    """Remove duplicates by protocol+host+port, keeping the first occurrence."""
    seen: set[str] = set()
    unique: list[Proxy] = []
    for proxy in proxies:
        if proxy.key in seen:
            continue
        seen.add(proxy.key)
        unique.append(proxy)
    return unique


def endpoint_host(url: str) -> str:
    try:
        return urlparse(url).netloc or url
    except Exception:
        return url
