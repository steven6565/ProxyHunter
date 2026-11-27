"""Data models used across Proxy Hunter."""

from __future__ import annotations

import ipaddress
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone

SUPPORTED_PROTOCOLS = ("http", "https", "socks4", "socks5")


def utc_now() -> str:
    """Return the current UTC time as a stable ISO-8601 string."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass
class Proxy:
    """A single proxy endpoint plus the metadata gathered during validation."""

    host: str
    port: int
    protocol: str = "http"
    working: bool = False
    response_time_ms: float = 0.0
    country: str = ""
    country_code: str = ""
    city: str = ""
    isp: str = ""
    exit_ip: str = ""
    source: str = ""
    last_checked: str = field(default_factory=utc_now)
    error: str = ""

    @property
    def _url_host(self) -> str:
        try:
            if ipaddress.ip_address(self.host).version == 6:
                return f"[{self.host}]"
        except ValueError:
            pass
        return self.host

    @property
    def address(self) -> str:
        """Plain ``host:port`` representation (IPv6 aware)."""
        return f"{self._url_host}:{self.port}"

    @property
    def url(self) -> str:
        """``protocol://host:port`` representation."""
        return f"{self.protocol}://{self._url_host}:{self.port}"

    @property
    def key(self) -> str:
        """Stable identity used for de-duplication and the database."""
        return f"{self.protocol}://{self.host.lower()}:{self.port}"

    def export_line(self, fmt: str = "ip_port") -> str:
        return self.address if fmt == "ip_port" else self.url

    def to_dict(self) -> dict:
        data = asdict(self)
        data["key"] = self.key
        data["address"] = self.address
        data["url"] = self.url
        data["response_time_ms"] = round(float(self.response_time_ms), 2)
        return data

    @classmethod
    def from_dict(cls, data: dict) -> "Proxy":
        """Build a Proxy from a JSON/desktop-selection dictionary."""
        return cls(
            host=str(data.get("host") or ""),
            port=int(data.get("port") or 0),
            protocol=str(data.get("protocol") or "http"),
            working=bool(data.get("working", True)),
            response_time_ms=float(data.get("response_time_ms") or 0),
            country=str(data.get("country") or ""),
            country_code=str(data.get("country_code") or ""),
            city=str(data.get("city") or ""),
            isp=str(data.get("isp") or ""),
            exit_ip=str(data.get("exit_ip") or ""),
            source=str(data.get("source") or ""),
            last_checked=str(data.get("last_checked") or utc_now()),
            error=str(data.get("error") or ""),
        )

    @classmethod
    def from_row(cls, row) -> "Proxy":
        """Build a Proxy from a sqlite row (mapping or tuple-like)."""
        try:
            keys = row.keys()
        except AttributeError:
            keys = (
                "host", "port", "protocol", "working", "response_time_ms",
                "country", "country_code", "city", "isp", "exit_ip",
                "source", "last_checked", "error",
            )
        values = dict(zip(keys, row))
        return cls(
            host=values.get("host", ""),
            port=int(values.get("port", 0)),
            protocol=values.get("protocol", "http"),
            working=bool(values.get("working", 0)),
            response_time_ms=float(values.get("response_time_ms") or 0.0),
            country=values.get("country") or "",
            country_code=values.get("country_code") or "",
            city=values.get("city") or "",
            isp=values.get("isp") or "",
            exit_ip=values.get("exit_ip") or "",
            source=values.get("source") or "",
            last_checked=values.get("last_checked") or utc_now(),
            error=values.get("error") or "",
        )
