"""Asynchronous discovery of public proxy lists from many source types."""

from __future__ import annotations

import asyncio
import copy
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Iterable
from urllib.parse import quote

import aiohttp
from bs4 import BeautifulSoup

from .config import ensure_packaged_defaults, resolve_path
from .logging_utils import RotatingFileLogger, safe_source_name
from .models import Proxy
from .utils import deduplicate, extract_proxies, normalize_country_code, normalize_protocol, parse_proxy

SOURCE_FILE = "sources.json"
GITHUB_API = "https://api.github.com"


def default_sources() -> dict:
    from .default_sources import DEFAULT_SOURCES
    return copy.deepcopy(DEFAULT_SOURCES)


def load_sources(path: str | Path | None = None) -> dict:
    ensure_packaged_defaults()
    path = resolve_path(path or SOURCE_FILE)
    if not path.exists():
        # First launch of a packaged app: create a valid, writable source file.
        created = default_sources()
        save_sources(created, path)
        return created
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        if not isinstance(data, dict) or not data:
            raise ValueError("empty source configuration")
        return data
    except (OSError, json.JSONDecodeError, ValueError):
        created = default_sources()
        save_sources(created, path)
        return created


def save_sources(data: dict, path: str | Path | None = None) -> None:
    path = resolve_path(path or SOURCE_FILE)
    tmp = path.with_suffix(".json.tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    tmp.replace(path)


class Discovery:
    def __init__(self, config: dict, storage, metrics, dashboard) -> None:
        self.config = config
        self.storage = storage
        self.metrics = metrics
        self.dashboard = dashboard
        self.sources_data = load_sources()
        self._loggers: dict[str, RotatingFileLogger] = {}

    # --------------------------------------------------------------- utilities
    def enabled_sources(self) -> list[dict]:
        result: list[dict] = []
        for category, entries in self.sources_data.items():
            if category.startswith("_") or not isinstance(entries, list):
                continue
            for entry in entries:
                if isinstance(entry, dict) and entry.get("enabled", True):
                    item = dict(entry)
                    item["_category"] = category
                    result.append(item)
        return result

    def source_list(self) -> list[dict]:
        result = []
        for category, entries in self.sources_data.items():
            if category.startswith("_") or not isinstance(entries, list):
                continue
            for entry in entries:
                if isinstance(entry, dict):
                    item = dict(entry)
                    item["category"] = category
                    result.append(item)
        return result

    def set_source_enabled(self, name: str, enabled: bool) -> bool:
        for category, entries in self.sources_data.items():
            if category.startswith("_") or not isinstance(entries, list):
                continue
            for entry in entries:
                if isinstance(entry, dict) and entry.get("name") == name:
                    entry["enabled"] = bool(enabled)
                    save_sources(self.sources_data)
                    return True
        return False

    async def check_sources(self) -> list[dict]:
        """Bounded connectivity diagnostics for configured sources."""
        import aiohttp
        targets = [s for s in self.source_list() if s.get("url")]
        results = []
        timeout = aiohttp.ClientTimeout(total=6, connect=4)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            for source in targets[:30]:
                name = source.get("name", "?")
                try:
                    async with session.head(source["url"], allow_redirects=True) as response:
                        results.append({
                            "name": name, "enabled": bool(source.get("enabled", True)),
                            "reachable": response.status < 500, "status": response.status,
                            "error": "",
                        })
                except Exception as exc:  # noqa: BLE001
                    results.append({
                        "name": name, "enabled": bool(source.get("enabled", True)),
                        "reachable": False, "status": 0,
                        "error": f"{type(exc).__name__}: {exc}"[:160],
                    })
        return results

    def add_source(self, source: dict) -> None:
        """Add or update a user supplied source in the 'custom' section."""
        custom = self.sources_data.setdefault("custom", [])
        name = source.get("name", "custom")
        for index, existing in enumerate(custom):
            if existing.get("name") == name:
                custom[index] = source
                break
        else:
            custom.append(source)
        save_sources(self.sources_data)

    def _log(self, source: str, level: str, message: str) -> None:
        safe = safe_source_name(source)
        logger = self._loggers.setdefault(
            safe, RotatingFileLogger(self.storage.root / "logs" / f"{safe}.log")
        )
        logger.log(level, message)
        self.storage.log_source(source, level, message)
        if level == "ERROR":
            self.dashboard.log(f"{source}: {message}", "red")

    # ------------------------------------------------------------ entry point
    async def discover(self) -> list[Proxy]:
        sources = self.enabled_sources()
        if not sources:
            self.dashboard.log("No enabled sources found in sources.json", "yellow")
            return []
        self.dashboard.set_phase("[cyan]Discovering proxies…", total=len(sources))
        sem = asyncio.Semaphore(max(1, int(self.config.get("discovery_concurrency", 10))))
        timeout = aiohttp.ClientTimeout(total=25, connect=8)
        headers = {"User-Agent": self.config.get("user_agent", "ProxyHunter/1.0"), "Accept": "*/*"}
        connector = aiohttp.TCPConnector(limit=20, ttl_dns_cache=300)

        async with aiohttp.ClientSession(timeout=timeout, headers=headers, connector=connector) as session:
            tasks = [self._fetch_source(source, session, sem) for source in sources]
            batches = await asyncio.gather(*tasks, return_exceptions=True)

        found: list[Proxy] = []
        for source, batch in zip(sources, batches):
            if isinstance(batch, Exception):
                self._log(source.get("name", "?"), "ERROR", f"Unhandled error: {batch}")
                continue
            found.extend(batch)
            self.dashboard.advance(1)

        allowed = set(self.config.get("protocol_filter") or [])
        candidates = [p for p in found if not allowed or p.protocol in allowed]
        unique = deduplicate(candidates)
        self.metrics.add_discovered(len(found), len(unique))

        self.storage.save_discovered(unique)
        self.dashboard.log(f"Discovery complete: {len(found)} found, {len(unique)} unique", "green")
        self.dashboard.set_phase(f"[green]{len(unique)} unique proxies discovered", total=max(1, len(unique)))
        return unique

    # ----------------------------------------------------------- source fetch
    async def _fetch_source(self, source: dict, session: aiohttp.ClientSession, sem: asyncio.Semaphore) -> list[Proxy]:
        name = source.get("name", source.get("url", "source"))
        async with sem:
            try:
                if source.get("type") == "github_search":
                    proxies = await self._github_search(source, session)
                else:
                    url = source.get("url")
                    if not url:
                        raise ValueError("missing url")
                    proxies = await self._fetch_url_source(source, url, session)
                self._log(name, "INFO", f"fetched {len(proxies)} proxies")
                return proxies
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 - one broken source must not stop the run
                self._log(name, "ERROR", f"{type(exc).__name__}: {exc}")
                return []

    async def _fetch_url_source(self, source: dict, url: str, session: aiohttp.ClientSession) -> list[Proxy]:
        headers = {}
        if source.get("type") == "github_search":
            headers["Accept"] = "application/vnd.github+json"
        async with session.get(url, headers=headers) as resp:
            if resp.status != 200:
                raise RuntimeError(f"HTTP {resp.status} from {url}")
            body = await resp.text(errors="replace")

        kind = source.get("type", "raw")
        default = source.get("default_protocol", "http")
        if kind == "json":
            try:
                data = json.loads(body)
            except json.JSONDecodeError as exc:
                raise ValueError("invalid JSON") from exc
            path = source.get("json_path")
            if path:
                for part in str(path).split("."):
                    if isinstance(data, dict):
                        data = data.get(part)
                    elif isinstance(data, list) and part.isdigit():
                        data = data[int(part)]
                    else:
                        data = None
                    if data is None:
                        break
            return self._json_to_proxies(data, default)
        if kind == "html":
            return self._html_to_proxies(body, default)
        return extract_proxies(body, default_protocol=default, source=source.get("name", ""))

    def _json_to_proxies(self, data, default: str, depth: int = 0) -> list[Proxy]:
        if depth > 4 or data is None:
            return []
        if isinstance(data, str):
            proxy = parse_proxy(data, default_protocol=default)
            return [proxy] if proxy else []
        if isinstance(data, dict):
            if "proxy" in data:
                parsed = self._json_to_proxies(data["proxy"], default, depth + 1)
                if parsed:
                    for p in parsed:
                        info = data.get("ip_data") or {}
                        p.country_code = normalize_country_code(str(info.get("countryCode", "")))
                        p.country = str(info.get("country", "")) or p.country
                        p.source = p.source or "json-api"
                    return parsed
            host = data.get("ip") or data.get("host") or data.get("address")
            port = data.get("port")
            if host and port:
                proto = normalize_protocol(str(data.get("protocol", "")), default)
                proxy = parse_proxy(f"{proto}://{host}:{port}", default_protocol=proto)
                if proxy:
                    info = data.get("ip_data") or {}
                    proxy.country_code = normalize_country_code(str(info.get("countryCode", "")))
                    proxy.country = str(info.get("country", "")) or proxy.country
                    return [proxy]
            result: list[Proxy] = []
            for value in data.values():
                if isinstance(value, (list, dict)):
                    result.extend(self._json_to_proxies(value, default, depth + 1))
            return result
        if isinstance(data, list):
            result = []
            for item in data:
                result.extend(self._json_to_proxies(item, default, depth + 1))
            return result
        return []

    def _html_to_proxies(self, html: str, default: str) -> list[Proxy]:
        soup = BeautifulSoup(html, "html.parser")
        proxies: list[Proxy] = []
        seen_rows: set[str] = set()
        for row in soup.find_all("tr"):
            cells = [cell.get_text(" ", strip=True) for cell in row.find_all(["td", "th"])]
            if not cells:
                continue
            # Try IP:port inside any cell first.
            for cell in cells:
                extracted = extract_proxies(cell, default_protocol=default)
                if extracted:
                    for proxy in extracted:
                        if proxy.key not in seen_rows:
                            seen_rows.add(proxy.key)
                            proxies.append(proxy)
                    break
            else:
                # Classic table: IP | Port | ... | Country code
                ip_text = next((c for c in cells if re.fullmatch(r"[\d.]+", c) and c.count(".") == 3), None)
                port_text = next((c for c in cells if c.isdigit() and 1 <= int(c) <= 65535), None)
                if ip_text and port_text:
                    proxy = parse_proxy(f"{default}://{ip_text}:{port_text}", default_protocol=default)
                    if proxy:
                        code = next((c for c in cells if re.fullmatch(r"[A-Za-z]{2}", c)), "")
                        proxy.country_code = normalize_country_code(code)
                        ssl_cell = next((c for c in cells if c.lower() in ("yes", "no")), "")
                        if ssl_cell.lower() == "yes":
                            proxy.protocol = "https"
                        if proxy.key not in seen_rows:
                            seen_rows.add(proxy.key)
                            proxies.append(proxy)
        if not proxies:
            proxies = extract_proxies(soup.get_text(" "), default_protocol=default)
        return proxies

    async def _github_search(self, source: dict, session: aiohttp.ClientSession) -> list[Proxy]:
        token = str(self.config.get("github_token") or "").strip()
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if token:
            headers["Authorization"] = f"Bearer {token}"
        query = source.get("query", "proxy list in:name,description")
        max_repos = max(1, min(5, int(source.get("max_repos", 2))))
        max_files = max(1, min(10, int(source.get("max_files", 4))))
        search_url = f"{GITHUB_API}/search/repositories?q={quote(query)}&sort=updated&per_page={max_repos}"

        async with session.get(search_url, headers=headers) as resp:
            if resp.status == 403:
                raise RuntimeError("GitHub API rate limit reached (set github_token in config.json)")
            if resp.status != 200:
                raise RuntimeError(f"GitHub search returned HTTP {resp.status}")
            data = await resp.json(content_type=None)
        repos = data.get("items", [])[:max_repos] if isinstance(data, dict) else []

        proxies: list[Proxy] = []
        for repo in repos:
            full_name = repo.get("full_name", "")
            branch = repo.get("default_branch", "main")
            if not full_name:
                continue
            contents_url = f"{GITHUB_API}/repos/{full_name}/contents?ref={quote(branch)}"
            async with session.get(contents_url, headers=headers) as resp:
                if resp.status != 200:
                    continue
                files = await resp.json(content_type=None)
            if not isinstance(files, list):
                continue
            candidates = [
                item for item in files
                if item.get("type") == "file"
                and str(item.get("name", "")).lower().endswith((".txt", ".csv", ".json"))
                and re.search(r"proxy|socks|http", str(item.get("name", "")), re.I)
            ][:max_files]
            for item in candidates:
                raw_url = item.get("download_url")
                if not raw_url:
                    continue
                try:
                    async with session.get(raw_url) as resp:
                        if resp.status != 200:
                            continue
                        body = await resp.text(errors="replace")
                    if str(item.get("name", "")).lower().endswith(".json"):
                        try:
                            proxies.extend(self._json_to_proxies(json.loads(body), "http"))
                        except json.JSONDecodeError:
                            pass
                    else:
                        proxies.extend(extract_proxies(body, default_protocol="http"))
                except aiohttp.ClientError:
                    continue
            if len(proxies) >= 2000:  # guard against a huge repo
                break
        return proxies
