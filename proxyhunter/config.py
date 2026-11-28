"""Configuration loading, validation and persistence."""

from __future__ import annotations

import copy
import json
import os
import sys
from pathlib import Path
from typing import Any

def is_frozen() -> bool:
    """True in PyInstaller EXE or Android/Chaquopy packaging."""
    return bool(getattr(sys, "frozen", False)) or bool(getattr(sys, "_MEIPASS", None)) or bool(
        os.environ.get("PROXYHUNTER_HOME")
    ) or (os.path.exists("/system/build.prop") and not (Path(__file__).resolve().parent.parent / "sources.json").exists())


WORKER_PRESETS = {
    "low": 10,
    "normal": 50,
    "fast": 100,
    "high": 200,
    "advanced": 500,
}

DEFAULT_CONFIG: dict[str, Any] = {
    "config_version": 4,
    "validation_max_age_hours": 24,
    "workers": {"preset": "normal", "count": 50},
    "timeout_seconds": 8,
    "connect_timeout_seconds": 5,
    "retries": 1,
    "rate_limit_per_second": 15,
    "discovery_concurrency": 10,
    "validation_endpoints": [
        {
            "url": "http://ip-api.com/json/?fields=status,country,countryCode,city,isp,query",
            "type": "ipapi",
            "weight": 3,
        },
        {"url": "https://api.ipify.org?format=json", "type": "ipify", "weight": 2},
        {"url": "https://httpbin.org/get", "type": "generic", "weight": 1},
    ],
    "export_format": "ip_port",  # ip_port | protocol_url
    "protocol_filter": ["http", "https", "socks4", "socks5"],
    "country_filter": [],  # empty = all countries
    "max_proxies_to_check": 0,  # 0 = unlimited
    "use_remote_geo": True,
    "geoip_db_path": "",  # e.g. data/GeoLite2-City.mmdb
    "refresh_mode": {
        "interval_minutes": 15,
        "auto_discover": True,
        "auto_recheck": True,
        "remove_expired_hours": 24,
    },
    "log_level": "INFO",
    "user_agent": "Mozilla/5.0 (compatible; ProxyHunter/3.4.0; +https://github.com)",
    "github_token": "",  # optional, raises GitHub API rate limits
    "auto_update": True,  # check GitHub Releases for a newer Windows build
    "auto_export": False,
    "performance_profile": "balanced",  # lite | balanced | performance
    "reduce_animations": False,
    "gateway": {
        "auto_start": True,
        "bind": "127.0.0.1",
        "port": 8080,
        "country": "all",
        "rotation_mode": "per_connection",
        "rotation_seconds": 60,
        "max_retries": 2,
        "connect_timeout_seconds": 5,
        "failure_threshold": 3,
        "pool_refresh_minutes": 15,
        "health_check_minutes": 5,
        "health_batch_size": 50,
        "refresh_check_limit": 200,
        "max_pool_size": 0,  # 0 = unlimited
        "allow_remote_access": False,
        "auth": {
            "enabled": False,
            "username": "",
            "password": "",  # legacy input only; migrated to PBKDF2 hash
            "salt": "",
            "password_hash": "",
            "iterations": 160000,
        },
        "health": {
            "quarantine_minutes": 15,
            "recovery_batch_size": 20,
            "max_consecutive_failures": 3,
            "circuit_breaker_threshold": 5,
            "circuit_cooldown_seconds": 60,
            "backoff_base_seconds": 1.0,
            "backoff_max_seconds": 30.0,
            "max_upstream_age_hours": 24,
        },
        "security": {
            "ip_allowlist": [],
            "destination_policy": "deny_private",
            "destination_allowlist": [],
            "allow_loopback": False,  # opt-in only; loopback destinations are not trusted by default
            "max_connections": 200,
            "max_connections_per_user": 10,
            "rate_limit_per_second": 0,
            "session_ttl_minutes": 30,
            "tls": {"enabled": False, "certfile": "", "keyfile": ""},
        },
    },
}


def base_dir() -> Path:
    """Writable data directory.

    Source checkouts keep using the project folder. Packaged Windows EXEs and
    the Android app use a writable user directory so config, sources, SQLite
    and exports survive restarts without needing the repository.
    """
    source_root = Path(__file__).resolve().parent.parent
    packaged = bool(getattr(sys, "frozen", False)) or (
        os.path.exists("/system/build.prop") and not (source_root / "sources.json").exists()
    )
    # An explicit override always wins (Android sets it to filesDir), even on
    # a development machine where a source checkout is also present.
    override = os.environ.get("PROXYHUNTER_HOME")
    if override:
        root = Path(override)
    elif not packaged:
        return source_root
    elif os.name == "nt":
        root = Path(os.environ.get("APPDATA") or str(Path.home())) / "ProxyHunter"
    else:
        root = Path.home() / "ProxyHunter"
    root.mkdir(parents=True, exist_ok=True)
    (root / "output" / "logs").mkdir(parents=True, exist_ok=True)
    return root


def bundle_dir() -> Path:
    """Directory containing read-only files bundled by PyInstaller/Chaquopy."""
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        return Path(str(meipass))
    return Path(__file__).resolve().parent.parent


def ensure_packaged_defaults() -> None:
    """Seed a fresh writable app-data dir with the bundled sample files."""
    if not is_frozen():
        return
    source = bundle_dir()
    target = base_dir()
    for name in ("config.json", "sources.json"):
        destination = target / name
        if destination.exists():
            continue
        bundled = source / name
        try:
            if bundled.is_file():
                destination.write_bytes(bundled.read_bytes())
            elif name == "config.json":
                save_config(copy.deepcopy(DEFAULT_CONFIG), destination)
            else:
                # Android/Chaquopy does not package sources.json next to the
                # Python sources.  Seed the full authorized source list from
                # the bundled Python module instead of writing an empty file
                # (which made discovery report "No enabled sources").
                from .default_sources import DEFAULT_SOURCES

                destination.write_text(
                    json.dumps(DEFAULT_SOURCES, indent=2, ensure_ascii=False) + "\n",
                    encoding="utf-8",
                )
        except (OSError, ImportError):
            pass


def resolve_path(path: str | Path) -> Path:
    p = Path(os.path.expanduser(str(path)))
    if not p.is_absolute():
        p = base_dir() / p
    return p


def _merge(defaults: dict, overrides: dict) -> dict:
    result = copy.deepcopy(defaults)
    for key, value in (overrides or {}).items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _merge(result[key], value)
        else:
            result[key] = copy.deepcopy(value)
    return result


def validate_config(cfg: dict) -> dict:
    """Coerce and sanity-check user supplied values."""
    cfg = copy.deepcopy(cfg)

    preset = str(cfg.get("workers", {}).get("preset", "normal")).lower()
    if preset not in WORKER_PRESETS:
        preset = "normal"
    count = cfg.get("workers", {}).get("count", WORKER_PRESETS[preset])
    try:
        count = int(count)
    except (TypeError, ValueError):
        count = WORKER_PRESETS[preset]
    count = max(1, min(2000, count))
    cfg["workers"] = {"preset": preset, "count": count}

    for key, low, high, cast in (
        ("timeout_seconds", 1, 120, float),
        ("connect_timeout_seconds", 1, 60, float),
        ("retries", 0, 10, int),
        ("rate_limit_per_second", 0, 1000, float),
        ("discovery_concurrency", 1, 100, int),
        ("max_proxies_to_check", 0, 5_000_000, int),
    ):
        try:
            value = cast(cfg.get(key, DEFAULT_CONFIG.get(key)))
        except (TypeError, ValueError):
            value = DEFAULT_CONFIG.get(key)
        cfg[key] = max(low, min(high, value))

    fmt = str(cfg.get("export_format", "ip_port")).lower()
    cfg["export_format"] = "protocol_url" if fmt in ("protocol_url", "url", "full") else "ip_port"

    protocols = cfg.get("protocol_filter") or list(DEFAULT_CONFIG["protocol_filter"])
    cfg["protocol_filter"] = [str(p).lower() for p in protocols if str(p).lower() in ("http", "https", "socks4", "socks5")]

    countries = cfg.get("country_filter") or []
    from .utils import normalize_country_code  # local import avoids a cycle
    cfg["country_filter"] = [normalize_country_code(c) for c in countries if str(c).strip()]

    if not isinstance(cfg.get("validation_endpoints"), list) or not cfg["validation_endpoints"]:
        cfg["validation_endpoints"] = copy.deepcopy(DEFAULT_CONFIG["validation_endpoints"])

    refresh = cfg.get("refresh_mode") or {}
    try:
        interval = float(refresh.get("interval_minutes", 15))
    except (TypeError, ValueError):
        interval = 15
    refresh["interval_minutes"] = max(1, min(10080, interval))
    try:
        refresh["remove_expired_hours"] = max(1, min(8760, int(refresh.get("remove_expired_hours", 24))))
    except (TypeError, ValueError):
        refresh["remove_expired_hours"] = 24
    refresh["auto_discover"] = bool(refresh.get("auto_discover", True))
    refresh["auto_recheck"] = bool(refresh.get("auto_recheck", True))
    cfg["refresh_mode"] = refresh

    # Rotating gateway settings.
    from .gateway import ROTATION_MODES  # local import: gateway imports config
    gateway = cfg.get("gateway") or {}
    gateway = _merge(DEFAULT_CONFIG["gateway"], gateway)
    try:
        gateway["port"] = max(1, min(65535, int(gateway.get("port", 8080))))
    except (TypeError, ValueError):
        gateway["port"] = 8080
    gateway["bind"] = str(gateway.get("bind") or "127.0.0.1")
    country = str(gateway.get("country") or "all").lower()
    if country not in ("all", "other"):
        country = normalize_country_code(country)
    gateway["country"] = country
    mode = str(gateway.get("rotation_mode") or "per_connection").lower()
    gateway["rotation_mode"] = mode if mode in ROTATION_MODES else "per_connection"
    for key, low, high, cast in (
        ("rotation_seconds", 1, 86400, int),
        ("max_retries", 0, 5, int),
        ("connect_timeout_seconds", 1, 60, float),
        ("failure_threshold", 1, 10, int),
        ("pool_refresh_minutes", 1, 720, int),
        ("health_check_minutes", 1, 720, int),
        ("health_batch_size", 1, 5000, int),
        ("refresh_check_limit", 1, 5000, int),
        ("max_pool_size", 0, 100000, int),
    ):
        try:
            gateway[key] = max(low, min(high, cast(gateway.get(key))))
        except (TypeError, ValueError):
            gateway[key] = DEFAULT_CONFIG["gateway"][key]
    # Legacy v1 configs used 1440 (24 h) for both intervals. Those values are
    # treated as unset so the reasonable v2 defaults take effect.
    if gateway["pool_refresh_minutes"] >= 1440:
        gateway["pool_refresh_minutes"] = DEFAULT_CONFIG["gateway"]["pool_refresh_minutes"]
    if gateway["health_check_minutes"] >= 1440:
        gateway["health_check_minutes"] = DEFAULT_CONFIG["gateway"]["health_check_minutes"]
    gateway["auto_start"] = bool(gateway.get("auto_start", True))
    gateway["allow_remote_access"] = bool(gateway.get("allow_remote_access", False))

    auth = _merge(DEFAULT_CONFIG["gateway"]["auth"], gateway.get("auth") or {})
    auth["enabled"] = bool(auth.get("enabled", False))
    auth["username"] = str(auth.get("username") or "")
    auth["password"] = str(auth.get("password") or "")
    auth["salt"] = str(auth.get("salt") or "")
    auth["password_hash"] = str(auth.get("password_hash") or "")
    try:
        auth["iterations"] = max(10000, min(1_000_000, int(auth.get("iterations", 160000))))
    except (TypeError, ValueError):
        auth["iterations"] = 160000
    gateway["auth"] = auth

    health = _merge(DEFAULT_CONFIG["gateway"]["health"], gateway.get("health") or {})
    for key, low, high, cast in (
        ("quarantine_minutes", 1, 1440, int),
        ("recovery_batch_size", 1, 1000, int),
        ("max_consecutive_failures", 1, 20, int),
        ("circuit_breaker_threshold", 1, 50, int),
        ("circuit_cooldown_seconds", 1, 3600, int),
        ("backoff_base_seconds", 0.1, 10.0, float),
        ("backoff_max_seconds", 1.0, 300.0, float),
        ("max_upstream_age_hours", 1, 720, int),
    ):
        try:
            health[key] = max(low, min(high, cast(health.get(key))))
        except (TypeError, ValueError):
            health[key] = DEFAULT_CONFIG["gateway"]["health"][key]
    gateway["health"] = health

    security = _merge(DEFAULT_CONFIG["gateway"]["security"], gateway.get("security") or {})
    security["ip_allowlist"] = [str(x) for x in (security.get("ip_allowlist") or []) if str(x).strip()]
    security["destination_allowlist"] = [str(x) for x in (security.get("destination_allowlist") or []) if str(x).strip()]
    security["destination_policy"] = str(security.get("destination_policy") or "deny_private").lower()
    if security["destination_policy"] not in ("all", "allowlist", "deny_private"):
        security["destination_policy"] = "deny_private"
    security["allow_loopback"] = bool(security.get("allow_loopback", False))
    for key, low, high, cast in (
        ("max_connections", 1, 10000, int),
        ("max_connections_per_user", 1, 1000, int),
        ("rate_limit_per_second", 0, 100000, float),
        ("session_ttl_minutes", 1, 10080, int),
    ):
        try:
            security[key] = max(low, min(high, cast(security.get(key))))
        except (TypeError, ValueError):
            security[key] = DEFAULT_CONFIG["gateway"]["security"][key]
    tls = _merge(DEFAULT_CONFIG["gateway"]["security"]["tls"], security.get("tls") or {})
    tls["enabled"] = bool(tls.get("enabled", False))
    tls["certfile"] = str(tls.get("certfile") or "")
    tls["keyfile"] = str(tls.get("keyfile") or "")
    security["tls"] = tls
    gateway["security"] = security
    cfg["gateway"] = gateway

    try:
        cfg["validation_max_age_hours"] = max(1, min(8760, int(cfg.get("validation_max_age_hours", 24))))
    except (TypeError, ValueError):
        cfg["validation_max_age_hours"] = 24

    return cfg


def migrate_config(data: dict) -> dict:
    """Upgrade v1 configuration in memory without discarding user settings."""
    data = copy.deepcopy(data or {})
    version = int(data.get("config_version", 1) or 1)
    if version < 2:
        gateway = data.get("gateway") or {}
        if int(gateway.get("pool_refresh_minutes", 0) or 0) >= 1440:
            gateway["pool_refresh_minutes"] = DEFAULT_CONFIG["gateway"]["pool_refresh_minutes"]
        if int(gateway.get("health_check_minutes", 0) or 0) >= 1440:
            gateway["health_check_minutes"] = DEFAULT_CONFIG["gateway"]["health_check_minutes"]
        data["gateway"] = gateway
        version = 2
    if version < 3:
        # v2 allowed loopback destinations by default. That is unsafe for a
        # proxy gateway, so v3 makes it explicit opt-in.
        gateway = data.get("gateway") or {}
        security = gateway.get("security") or {}
        security["allow_loopback"] = False
        gateway["security"] = security
        data["gateway"] = gateway
        version = 3
    if version < 4:
        # v3.1: start the local gateway automatically on app launch.
        gateway = data.get("gateway") or {}
        gateway["auto_start"] = True
        data["gateway"] = gateway
        data["config_version"] = 4
    return data


def load_config(path: str | Path | None = None) -> dict:
    ensure_packaged_defaults()
    path = resolve_path(path or "config.json")
    if not path.exists():
        cfg = copy.deepcopy(DEFAULT_CONFIG)
        save_config(cfg, path)
        return cfg
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, json.JSONDecodeError):
        data = {}
    return validate_config(_merge(DEFAULT_CONFIG, migrate_config(data)))


def save_config(cfg: dict, path: str | Path | None = None) -> None:
    path = resolve_path(path or "config.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(cfg, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    os.replace(tmp, path)


def apply_preset(cfg: dict, preset: str) -> dict:
    preset = preset.lower()
    if preset not in WORKER_PRESETS:
        raise ValueError(f"Unknown preset: {preset}")
    cfg["workers"] = {"preset": preset, "count": WORKER_PRESETS[preset]}
    return cfg
