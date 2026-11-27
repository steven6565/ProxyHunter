"""GeoIP resolution with a local database first and a rate-limited batch API.

MaxMind's GeoLite2 databases require a free licence key, so they cannot be
downloaded silently. Drop ``GeoLite2-City.mmdb`` into ``ProxyHunter/data/``
(or point ``geoip_db_path`` at one) to get fully offline lookups. Without it,
geography comes from the validation response or from ip-api.com's batch
endpoint (100 IPs/request, 45 requests/minute on the free tier).
"""

from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import Iterable

import aiohttp

from .config import resolve_path
from .models import utc_now
from .utils import normalize_country_code

BATCH_URL = "http://ip-api.com/batch?fields=status,country,countryCode,city,isp,query"
FIELDS = ("status", "country", "countryCode", "city", "isp", "query")


class GeoResolver:
    def __init__(self, config: dict, storage) -> None:
        self.config = config
        self.storage = storage
        self.reader = None
        self._cache: dict[str, dict] = {}
        self._last_batch = 0.0
        self.backend = "none"

        try:
            from geoip2.database import Reader  # type: ignore
        except Exception:  # noqa: BLE001
            Reader = None

        candidates = []
        configured = config.get("geoip_db_path")
        if configured:
            candidates.append(resolve_path(configured))
        candidates += [
            resolve_path("data/GeoLite2-City.mmdb"),
            resolve_path("GeoLite2-City.mmdb"),
            Path("/usr/share/GeoIP/GeoLite2-City.mmdb"),
        ]
        if Reader is not None:
            for path in candidates:
                try:
                    if path.is_file():
                        self.reader = Reader(str(path))
                        self.backend = f"GeoLite2 ({path.name})"
                        break
                except Exception:  # noqa: BLE001
                    continue

    def close(self) -> None:
        if self.reader is not None:
            try:
                self.reader.close()
            except Exception:  # noqa: BLE001
                pass

    # ------------------------------------------------------------------ helpers
    @staticmethod
    def _clean(data: dict) -> dict:
        if not isinstance(data, dict):
            return {}
        status = str(data.get("status", "")).lower()
        if status and status != "success":
            return {}
        return {
            "country": str(data.get("country") or ""),
            "country_code": normalize_country_code(str(data.get("countryCode") or data.get("country_code") or "")),
            "city": str(data.get("city") or ""),
            "isp": str(data.get("isp") or data.get("asname") or ""),
        }

    def _remember(self, ip: str, geo: dict) -> dict:
        geo = self._clean(geo)
        if not geo:
            return {}
        self._cache[ip] = geo
        self.storage.set_geo_cache(ip, geo)
        return geo

    # ------------------------------------------------------------------ lookups
    def resolve(self, ip: str, api_data: dict | None = None) -> dict:
        """Resolve synchronously (no network). API data wins over local data."""
        if not ip:
            return {}
        if api_data:
            geo = self._clean(api_data)
            if geo:
                return self._remember(ip, geo)
        cached = self._cache.get(ip)
        if cached is None:
            cached = self.storage.get_geo_cache(ip)
            if cached:
                self._cache[ip] = cached
        if cached:
            return cached
        if self.reader is not None:
            try:
                record = self.reader.city(ip)
                geo = {
                    "country": (record.country.names or {}).get("en", ""),
                    "country_code": record.country.iso_code or "",
                    "city": (record.city.names or {}).get("en", ""),
                    "isp": "",
                }
                return self._remember(ip, geo)
            except Exception:  # noqa: BLE001 - address not in database
                pass
        return {}

    async def resolve_batch(self, ips: Iterable[str], session: aiohttp.ClientSession) -> dict[str, dict]:
        """Fill missing geography with one rate-limited batch request per 100 IPs."""
        if not self.config.get("use_remote_geo", True):
            return {}
        unique: list[str] = []
        for ip in ips:
            if ip and ip not in unique:
                unique.append(ip)
        missing = [ip for ip in unique if ip not in self._cache and not self.storage.get_geo_cache(ip)]
        if not missing:
            return {}

        result: dict[str, dict] = {}
        timeout = aiohttp.ClientTimeout(total=12)
        for start in range(0, len(missing), 100):
            chunk = missing[start:start + 100]
            # Free tier: 45 requests/minute => never faster than ~1.4s.
            wait = 1.4 - (time.monotonic() - self._last_batch)
            if wait > 0:
                await asyncio.sleep(wait)
            self._last_batch = time.monotonic()
            try:
                async with session.post(BATCH_URL, json=[{"query": ip} for ip in chunk], timeout=timeout) as resp:
                    if resp.status != 200:
                        continue
                    payload = await resp.json(content_type=None)
                if not isinstance(payload, list):
                    continue
                for entry in payload:
                    ip = str(entry.get("query") or "")
                    if not ip:
                        continue
                    geo = self._remember(ip, entry)
                    if geo:
                        result[ip] = geo
            except (aiohttp.ClientError, asyncio.TimeoutError, ValueError):
                continue
        return result
