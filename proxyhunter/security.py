"""Gateway security: credential hashing, sessions, allowlists and policies.

All secrets are stored as PBKDF2-HMAC-SHA256 salted hashes in config.json;
plaintext passwords are migrated and removed on first load.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import ipaddress
import secrets
import socket
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from .logging_utils import RotatingFileLogger
from .utils import is_public_ip

PBKDF2_ITERATIONS = 160_000


def hash_password(password: str, salt: str | None = None, iterations: int = PBKDF2_ITERATIONS) -> tuple[str, str, int]:
    salt_value = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", str(password).encode("utf-8"), bytes.fromhex(salt_value), iterations
    ).hex()
    return salt_value, digest, iterations


def verify_password(password: str, salt: str, expected: str, iterations: int) -> bool:
    try:
        _, actual, _ = hash_password(password, salt, int(iterations or PBKDF2_ITERATIONS))
        return hmac.compare_digest(actual, str(expected))
    except (ValueError, TypeError):
        return False


class TokenBucket:
    """Async-safe token bucket; rate <= 0 means unlimited."""

    def __init__(self, rate: float, capacity: float | None = None) -> None:
        self.rate = max(0.0, float(rate))
        self.capacity = float(capacity if capacity is not None else max(1.0, self.rate))
        self.tokens = self.capacity
        self.updated = time.monotonic()

    def allow(self) -> bool:
        if self.rate <= 0:
            return True
        now = time.monotonic()
        self.tokens = min(self.capacity, self.tokens + (now - self.updated) * self.rate)
        self.updated = now
        if self.tokens >= 1:
            self.tokens -= 1
            return True
        return False


@dataclass
class Session:
    username: str
    expires: float
    last_seen: float = field(default_factory=time.monotonic)


class AuthManager:
    def __init__(self, config: dict, events=None, log_path: str = "output/logs/gateway_auth.log") -> None:
        self.config = config
        self.cfg = config.setdefault("gateway", {})
        self.events = events
        self.auth = self.cfg.setdefault("auth", {})
        self.security = self.cfg.setdefault("security", {})
        self.logger = RotatingFileLogger(Path(__file__).resolve().parent.parent / log_path)
        self.sessions: dict[str, Session] = {}
        self.failed_attempts: dict[str, int] = {}
        self.user_connections: dict[str, int] = {}
        self.peer_buckets: dict[str, TokenBucket] = {}
        self._migrate_plaintext()
        self._cleanup()

    def _event(self, message: str) -> None:
        if self.events is not None:
            self.events.append(f"[security] {message}")

    def _migrate_plaintext(self) -> None:
        password = self.auth.get("password") or ""
        if password and not self.auth.get("password_hash"):
            salt, digest, iterations = hash_password(password)
            self.auth.update(salt=salt, password_hash=digest, iterations=iterations)
            self.auth["password"] = ""
            self._event("plaintext password migrated to PBKDF2 hash")
            from .config import save_config
            save_config(self.config)

    def set_credentials(self, username: str, password: str) -> None:
        salt, digest, iterations = hash_password(password)
        self.auth.update(
            username=str(username), salt=salt, password_hash=digest,
            iterations=iterations, password="", enabled=bool(username and password),
        )
        from .config import save_config
        save_config(self.config)
        self._event("credentials updated (PBKDF2)")

    # ------------------------------------------------------------- authentication
    def _cleanup(self) -> None:
        now = time.monotonic()
        ttl = max(1, int(self.security.get("session_ttl_minutes", 30))) * 60
        self.sessions = {k: v for k, v in self.sessions.items() if v.expires > now}
        for token, session in list(self.sessions.items()):
            if now - session.last_seen > ttl:
                self.sessions.pop(token, None)

    def authenticate_header(self, header: bytes | str | None, peer: str = "") -> tuple[bool, str, str]:
        """Return ``(ok, username, token_or_reason)``."""
        self._cleanup()
        if not self.auth.get("enabled"):
            return True, "anonymous", ""
        value = (header.decode("utf-8", "replace") if isinstance(header, bytes) else str(header or "")).strip()
        if value.lower().startswith("bearer "):
            token = value[7:].strip()
            session = self.sessions.get(token)
            if session and session.expires > time.monotonic():
                session.last_seen = time.monotonic()
                return True, session.username, token
            self._fail(peer, "invalid session token")
            return False, "", "invalid session token"
        if value.lower().startswith("basic "):
            try:
                decoded = base64.b64decode(value[6:], validate=False).decode("utf-8")
                username, password = decoded.split(":", 1)
            except Exception:  # noqa: BLE001
                self._fail(peer, "malformed basic credentials")
                return False, "", "malformed credentials"
            expected_user = str(self.auth.get("username") or "")
            if (
                hmac.compare_digest(username, expected_user)
                and verify_password(
                    password, str(self.auth.get("salt") or ""),
                    str(self.auth.get("password_hash") or ""),
                    int(self.auth.get("iterations") or PBKDF2_ITERATIONS),
                )
            ):
                token = secrets.token_urlsafe(24)
                ttl = max(1, int(self.security.get("session_ttl_minutes", 30))) * 60
                self.sessions[token] = Session(username=username, expires=time.monotonic() + ttl)
                self.failed_attempts.pop(peer, None)
                return True, username, token
            self._fail(peer, f"bad credentials for user {username!r}")
            return False, "", "invalid credentials"
        self._fail(peer, "missing proxy authorization")
        return False, "", "authentication required"

    def _fail(self, peer: str, reason: str) -> None:
        self.failed_attempts[peer] = self.failed_attempts.get(peer, 0) + 1
        self.logger.log("FAIL", f"peer={peer} reason={reason} count={self.failed_attempts[peer]}")
        self._event(f"auth failed from {peer}: {reason}")

    # --------------------------------------------------------------- access rules
    def peer_allowed(self, peer: str) -> bool:
        allowlist = [str(x) for x in (self.security.get("ip_allowlist") or []) if str(x).strip()]
        if not allowlist:
            return True
        try:
            address = ipaddress.ip_address(peer.split(":")[0] if ":" in peer and not peer.startswith("[") else peer)
            for entry in allowlist:
                if address in ipaddress.ip_network(entry, strict=False):
                    return True
        except ValueError:
            if peer in allowlist:
                return True
        self.logger.log("DENY", f"peer={peer} not in allowlist")
        return False

    def destination_allowed(self, host: str, port: int) -> tuple[bool, str]:
        policy = str(self.security.get("destination_policy", "deny_private")).lower()
        allowlist = [str(x).lower() for x in (self.security.get("destination_allowlist") or []) if str(x).strip()]
        target = f"{host}:{port}"
        if allowlist and target.lower() not in allowlist and host.lower() not in allowlist:
            self.logger.log("DENY", f"destination={target} not in allowlist")
            return False, "destination not in allowlist"
        if policy == "all":
            return True, ""
        try:
            address = ipaddress.ip_address(host)
            is_ip = True
            is_private = not is_public_ip(host)
        except ValueError:
            # Hostname: the upstream proxy performs DNS resolution. Block
            # obvious local/internal names, otherwise allow it.
            is_ip = False
            is_private = str(host).lower().startswith("localhost") or str(host).lower().endswith(
                (".local", ".internal", ".localhost")
            )
        if is_private and self.security.get("allow_loopback", False):
            if is_ip and address.is_loopback:
                return True, ""
            if not is_ip and str(host).lower().startswith("localhost"):
                return True, ""
        if is_private and policy == "deny_private":
            self.logger.log("DENY", f"destination={target} is private/reserved")
            return False, "private or reserved destination denied"
        return True, ""

    async def destination_allowed_async(self, host: str, port: int) -> tuple[bool, str]:
        """Policy + DNS-checked destination validation (v3 security fix).

        Hostnames are resolved with a bounded timeout and every resolved
        address must be globally routable unless loopback was explicitly
        allowed. This prevents a trusted-looking name from resolving into the
        private network.
        """
        allowed, reason = self.destination_allowed(host, port)
        if not allowed:
            return False, reason
        if str(self.security.get("destination_policy", "deny_private")).lower() == "all":
            return True, ""
        try:
            literal = ipaddress.ip_address(host)
            addresses = [str(literal)]
        except ValueError:
            try:
                infos = await asyncio.wait_for(
                    asyncio.get_running_loop().getaddrinfo(host, port, type=socket.SOCK_STREAM),
                    timeout=3.0,
                )
                addresses = sorted({info[4][0] for info in infos})
            except Exception as exc:  # noqa: BLE001
                self.logger.log("DENY", f"destination={host}:{port} DNS failed: {type(exc).__name__}")
                return False, "destination DNS resolution failed"
            if not addresses:
                return False, "destination DNS resolution failed"
        for address in addresses:
            if is_public_ip(address):
                continue
            try:
                is_loop = ipaddress.ip_address(address).is_loopback
            except ValueError:
                is_loop = False
            if is_loop and self.security.get("allow_loopback", False):
                continue
            self.logger.log("DENY", f"destination={host}:{port} resolved to private {address}")
            return False, f"destination resolves to private/reserved address {address}"
        return True, ""

    def rate_allowed(self, peer: str) -> bool:
        rate = float(self.security.get("rate_limit_per_second", 0) or 0)
        if rate <= 0:
            return True
        bucket = self.peer_buckets.setdefault(peer, TokenBucket(rate, max(1.0, rate)))
        if bucket.allow():
            return True
        self.logger.log("DENY", f"peer={peer} rate limit exceeded")
        return False

    def reserve_connection(self, user: str) -> bool:
        # With authentication disabled every client is "anonymous"; a
        # per-user limit must not silently throttle all local traffic.
        if not self.auth.get("enabled") and user == "anonymous":
            self.user_connections[user] = self.user_connections.get(user, 0) + 1
            return True
        maximum = max(1, int(self.security.get("max_connections_per_user", 10)))
        if self.user_connections.get(user, 0) >= maximum:
            self.logger.log("DENY", f"user={user} connection limit {maximum} reached")
            return False
        self.user_connections[user] = self.user_connections.get(user, 0) + 1
        return True

    def release_connection(self, user: str) -> None:
        if user in self.user_connections:
            self.user_connections[user] = max(0, self.user_connections[user] - 1)

    def close_session(self, token: str) -> None:
        self.sessions.pop(token, None)
