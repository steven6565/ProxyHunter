"""SQLite persistence and all file exports."""

from __future__ import annotations

import csv
import json
import os
import sqlite3
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable

from .config import resolve_path
from .models import Proxy, utc_now
from .utils import normalize_country_code

# Countries that always get a dedicated file, even when empty.
MAJOR_COUNTRIES = ("US", "GB", "IN", "DE", "CA", "FR", "JP", "SG", "NL", "AU")


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(content)
    os.replace(tmp, path)


class Storage:
    def __init__(self, config: dict) -> None:
        self.config = config
        self.root = resolve_path("output")
        self.root.mkdir(parents=True, exist_ok=True)
        for folder in ("protocols", "countries", "filters", "logs"):
            (self.root / folder).mkdir(parents=True, exist_ok=True)
        (self.root.parent / "data").mkdir(exist_ok=True)

        self.db_path = self.root / "proxies.db"
        self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA synchronous=NORMAL")
        self.conn.execute("PRAGMA temp_store=MEMORY")
        self._create_tables()

    def _create_tables(self) -> None:
        self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS proxies (
                key              TEXT PRIMARY KEY,
                host             TEXT NOT NULL,
                port             INTEGER NOT NULL,
                protocol         TEXT NOT NULL,
                working          INTEGER NOT NULL DEFAULT 1,
                response_time_ms REAL DEFAULT 0,
                country          TEXT DEFAULT '',
                country_code     TEXT DEFAULT '',
                city             TEXT DEFAULT '',
                isp              TEXT DEFAULT '',
                exit_ip          TEXT DEFAULT '',
                source           TEXT DEFAULT '',
                last_checked     TEXT DEFAULT '',
                error            TEXT DEFAULT ''
            );
            CREATE INDEX IF NOT EXISTS idx_protocol ON proxies(protocol);
            CREATE INDEX IF NOT EXISTS idx_country  ON proxies(country_code);
            CREATE INDEX IF NOT EXISTS idx_checked  ON proxies(last_checked);

            CREATE TABLE IF NOT EXISTS check_history (
                id        INTEGER PRIMARY KEY AUTOINCREMENT,
                key       TEXT,
                working   INTEGER,
                response  REAL,
                checked   TEXT
            );

            CREATE TABLE IF NOT EXISTS source_errors (
                id        INTEGER PRIMARY KEY AUTOINCREMENT,
                source    TEXT,
                level     TEXT,
                message   TEXT,
                timestamp TEXT
            );

            CREATE TABLE IF NOT EXISTS geo_cache (
                ip           TEXT PRIMARY KEY,
                country      TEXT DEFAULT '',
                country_code TEXT DEFAULT '',
                city         TEXT DEFAULT '',
                isp          TEXT DEFAULT '',
                checked      TEXT DEFAULT ''
            );

            CREATE TABLE IF NOT EXISTS health_events (
                id        INTEGER PRIMARY KEY AUTOINCREMENT,
                key       TEXT,
                event     TEXT,
                detail    TEXT,
                timestamp TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_health_event_key ON health_events(key);
            """
        )
        self.conn.commit()
        self._migrate()

    # --------------------------------------------------------------- migrations
    def _column_exists(self, table: str, column: str) -> bool:
        return any(row[1] == column for row in self.conn.execute(f"PRAGMA table_info({table})").fetchall())

    def _migrate(self) -> None:
        """Add v2 health columns in place; existing rows and records survive."""
        version = int(self.conn.execute("PRAGMA user_version").fetchone()[0] or 0)
        if version < 1:
            additions = {
                "health_state": "TEXT DEFAULT 'healthy'",
                "consecutive_failures": "INTEGER DEFAULT 0",
                "last_success": "TEXT DEFAULT ''",
                "quarantine_until": "TEXT DEFAULT ''",
                "unique_exit_ip": "TEXT DEFAULT ''",
            }
            for column, definition in additions.items():
                if not self._column_exists("proxies", column):
                    self.conn.execute(f"ALTER TABLE proxies ADD COLUMN {column} {definition}")
            self.conn.execute(
                "UPDATE proxies SET health_state='healthy', last_success=last_checked, "
                "unique_exit_ip=CASE WHEN exit_ip <> '' THEN exit_ip ELSE host END "
                "WHERE health_state IS NULL OR health_state = ''"
            )
            self.conn.execute("CREATE INDEX IF NOT EXISTS idx_health_state ON proxies(health_state)")
            self.conn.execute("CREATE INDEX IF NOT EXISTS idx_quarantine ON proxies(quarantine_until)")
            self.conn.commit()
            version = 1
        if version < 2:
            self.conn.execute("PRAGMA user_version=2")
            self.conn.commit()

    @property
    def schema_version(self) -> int:
        return int(self.conn.execute("PRAGMA user_version").fetchone()[0] or 0)

    # ------------------------------------------------------------------ writes
    def upsert_results(self, results: Iterable[Proxy], remove_dead: bool = True) -> None:
        """Persist validated results. Dead rows are removed or left for health handling."""
        rows = []
        history = []
        for proxy in results:
            if not proxy.working:
                if remove_dead:
                    self.conn.execute("DELETE FROM proxies WHERE key = ?", (proxy.key,))
                continue
            proxy.last_checked = proxy.last_checked or utc_now()
            exit_ip = proxy.exit_ip or proxy.host
            rows.append(
                (
                    proxy.key, proxy.host, proxy.port, proxy.protocol, 1,
                    round(proxy.response_time_ms, 2), proxy.country,
                    normalize_country_code(proxy.country_code), proxy.city, proxy.isp,
                    proxy.exit_ip, proxy.source, proxy.last_checked, proxy.error,
                    "healthy", 0, proxy.last_checked, "", exit_ip,
                )
            )
            history.append((proxy.key, 1, round(proxy.response_time_ms, 2), proxy.last_checked))
        if rows:
            self.conn.executemany(
                """INSERT INTO proxies
                   (key, host, port, protocol, working, response_time_ms, country,
                    country_code, city, isp, exit_ip, source, last_checked, error,
                    health_state, consecutive_failures, last_success, quarantine_until,
                    unique_exit_ip)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(key) DO UPDATE SET
                     working=excluded.working,
                     response_time_ms=excluded.response_time_ms,
                     country=excluded.country, country_code=excluded.country_code,
                     city=excluded.city, isp=excluded.isp, exit_ip=excluded.exit_ip,
                     source=excluded.source, last_checked=excluded.last_checked,
                     error=excluded.error, health_state=excluded.health_state,
                     consecutive_failures=0, last_success=excluded.last_success,
                     quarantine_until='', unique_exit_ip=excluded.unique_exit_ip""",
                rows,
            )
        if history:
            self.conn.executemany(
                "INSERT INTO check_history (key, working, response, checked) VALUES (?,?,?,?)",
                history,
            )
        self.conn.commit()

    def delete_proxy(self, key: str) -> None:
        self.conn.execute("DELETE FROM proxies WHERE key = ?", (key,))
        self.conn.commit()

    def prune_expired(self, hours: int) -> int:
        """Mark stale validation results expired; records are retained for history."""
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M:%SZ")
        cur = self.conn.execute(
            "UPDATE proxies SET working = 0, health_state = 'expired' "
            "WHERE last_checked < ? AND health_state <> 'expired'", (cutoff,)
        )
        self.conn.commit()
        return cur.rowcount

    def log_source(self, source: str, level: str, message: str) -> None:
        self.conn.execute(
            "INSERT INTO source_errors (source, level, message, timestamp) VALUES (?,?,?,?)",
            (source, level, str(message)[:500], utc_now()),
        )
        self.conn.commit()

    # ------------------------------------------------------------------- reads
    def get_working(
        self,
        protocols: Iterable[str] | None = None,
        countries: Iterable[str] | None = None,
        limit: int = 0,
        max_age_hours: float = 0,
        include_quarantined: bool = False,
    ) -> list[Proxy]:
        now = utc_now()
        query = "SELECT * FROM proxies WHERE working = 1 AND health_state = 'healthy'"
        params: list = []
        if not include_quarantined:
            query += " AND (quarantine_until = '' OR quarantine_until < ?)"
            params.append(now)
        if max_age_hours > 0:
            cutoff = (datetime.now(timezone.utc) - timedelta(hours=float(max_age_hours))).strftime("%Y-%m-%dT%H:%M:%SZ")
            query += " AND last_checked >= ?"
            params.append(cutoff)
        if protocols:
            marks = ",".join("?" for _ in protocols)
            query += f" AND protocol IN ({marks})"
            params.extend(protocols)
        if countries:
            marks = ",".join("?" for _ in countries)
            query += f" AND country_code IN ({marks})"
            params.extend(countries)
        query += " ORDER BY response_time_ms ASC"
        if limit:
            query += " LIMIT ?"
            params.append(limit)
        return [Proxy.from_row(row) for row in self.conn.execute(query, params).fetchall()]

    def count_working(self, max_age_hours: float = 0) -> int:
        return len(self.get_working(max_age_hours=max_age_hours))

    # ---------------------------------------------------------- health lifecycle
    def mark_success(self, key: str, latency_ms: float = 0.0) -> None:
        now = utc_now()
        self.conn.execute(
            """UPDATE proxies SET health_state='healthy', consecutive_failures=0,
               quarantine_until='', last_success=?, last_checked=?,
               unique_exit_ip=CASE WHEN exit_ip <> '' THEN exit_ip ELSE host END,
               response_time_ms=CASE WHEN ? > 0 THEN ? ELSE response_time_ms END
               WHERE key=?""",
            (now, now, latency_ms, latency_ms, key),
        )
        self.log_health_event(key, "success", f"latency={round(float(latency_ms), 1)}ms")
        self.conn.commit()

    def mark_failure(self, key: str, threshold: int, quarantine_minutes: int, reason: str = "") -> str:
        row = self.conn.execute(
            "SELECT consecutive_failures FROM proxies WHERE key = ?", (key,)
        ).fetchone()
        failures = int(row[0]) + 1 if row else 1
        state = "healthy"
        if failures >= max(1, int(threshold)):
            until = (datetime.now(timezone.utc) + timedelta(minutes=max(1, quarantine_minutes))).strftime("%Y-%m-%dT%H:%M:%SZ")
            self.conn.execute(
                "UPDATE proxies SET health_state='quarantined', consecutive_failures=?, quarantine_until=? WHERE key=?",
                (failures, until, key),
            )
            state = "quarantined"
            self.log_health_event(key, "quarantine", f"{reason[:120]} until={until}")
        else:
            self.conn.execute(
                "UPDATE proxies SET consecutive_failures=? WHERE key=?", (failures, key)
            )
            self.log_health_event(key, "failure", f"{reason[:120]} ({failures}/{threshold})")
        self.conn.commit()
        return state

    def get_quarantined(self, limit: int = 20) -> list[Proxy]:
        now = utc_now()
        rows = self.conn.execute(
            """SELECT * FROM proxies WHERE health_state='quarantined'
               AND quarantine_until <> '' AND quarantine_until <= ?
               ORDER BY quarantine_until ASC LIMIT ?""", (now, max(1, limit))
        ).fetchall()
        return [Proxy.from_row(row) for row in rows]

    def recover_proxy(self, key: str) -> None:
        now = utc_now()
        self.conn.execute(
            """UPDATE proxies SET health_state='healthy', working=1, consecutive_failures=0,
               quarantine_until='', last_success=?, last_checked=? WHERE key=?""",
            (now, now, key),
        )
        self.log_health_event(key, "recovered", "controlled revalidation succeeded")
        self.conn.commit()

    def log_health_event(self, key: str, event: str, detail: str = "") -> None:
        self.conn.execute(
            "INSERT INTO health_events (key, event, detail, timestamp) VALUES (?,?,?,?)",
            (key, event, detail[:300], utc_now()),
        )

    def health_distribution(self) -> dict[str, int]:
        result = {"healthy": 0, "quarantined": 0, "expired": 0, "other": 0}
        for row in self.conn.execute(
            "SELECT health_state, COUNT(*) AS n FROM proxies GROUP BY health_state"
        ):
            state = str(row[0] or "other")
            result[state if state in result else "other"] = int(row[1])
        return result

    def capacity_report(self, max_age_hours: float = 24) -> dict:
        proxies = self.get_working(max_age_hours=max_age_hours)
        by_country: dict[str, dict] = {}
        for proxy in proxies:
            code = normalize_country_code(proxy.country_code) or "XX"
            entry = by_country.setdefault(code, {"count": 0, "exit_ips": set()})
            entry["count"] += 1
            entry["exit_ips"].add(proxy.exit_ip or proxy.host)
        return {
            "healthy": len(proxies),
            "unique_exit_ips": len({p.exit_ip or p.host for p in proxies}),
            "countries": {
                code: {"count": data["count"], "unique_ips": len(data["exit_ips"])}
                for code, data in sorted(by_country.items())
            },
        }

    def find_duplicates(self) -> dict[str, int]:
        endpoints = self.conn.execute(
            "SELECT COUNT(*) FROM (SELECT host, port FROM proxies GROUP BY host, port HAVING COUNT(*) > 1)"
        ).fetchone()[0]
        exits = self.conn.execute(
            "SELECT COUNT(*) FROM (SELECT exit_ip FROM proxies WHERE exit_ip <> '' "
            "GROUP BY exit_ip HAVING COUNT(*) > 1)"
        ).fetchone()[0]
        return {"duplicate_endpoints": int(endpoints), "shared_exit_ips": int(exits)}

    def source_errors(self, limit: int = 30) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM source_errors ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()

    # --------------------------------------------------------------- geo cache
    def get_geo_cache(self, ip: str) -> dict:
        row = self.conn.execute(
            "SELECT country, country_code, city, isp FROM geo_cache WHERE ip = ?", (ip,)
        ).fetchone()
        if row is None:
            return {}
        return {key: row[key] for key in ("country", "country_code", "city", "isp")}

    def set_geo_cache(self, ip: str, geo: dict) -> None:
        self.conn.execute(
            """INSERT INTO geo_cache (ip, country, country_code, city, isp, checked)
               VALUES (?,?,?,?,?,?)
               ON CONFLICT(ip) DO UPDATE SET country=excluded.country,
                 country_code=excluded.country_code, city=excluded.city,
                 isp=excluded.isp, checked=excluded.checked""",
            (
                ip, geo.get("country", ""), geo.get("country_code", ""),
                geo.get("city", ""), geo.get("isp", ""), utc_now(),
            ),
        )
        self.conn.commit()

    # ---------------------------------------------------------------- exports
    def export_all(self) -> dict[str, int]:
        """Write every output file and return per-file line counts."""
        proxies = self.get_working(max_age_hours=float(self.config.get("validation_max_age_hours", 24) or 0))
        fmt = self.config.get("export_format", "ip_port")
        other_fmt = "protocol_url" if fmt == "ip_port" else "ip_port"

        def lines(items: list[Proxy], f: str) -> str:
            return "\n".join(p.export_line(f) for p in items) + ("\n" if items else "")

        _atomic_write(self.root / "working_proxies.txt", lines(proxies, fmt))
        _atomic_write(self.root / "working_proxies_addresses.txt", lines(proxies, other_fmt))

        json_obj = {
            "generated_at": utc_now(),
            "total": len(proxies),
            "proxies": [p.to_dict() for p in proxies],
        }
        _atomic_write(
            self.root / "working_proxies.json",
            json.dumps(json_obj, indent=2, ensure_ascii=False) + "\n",
        )

        csv_file = self.root / "working_proxies.csv"
        tmp = csv_file.with_name(csv_file.name + ".tmp")
        fields = [
            "host", "port", "protocol", "working", "response_time_ms", "country",
            "country_code", "city", "isp", "exit_ip", "source", "last_checked",
            "address", "url",
        ]
        with open(tmp, "w", encoding="utf-8", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=fields)
            writer.writeheader()
            for p in proxies:
                row = p.to_dict()
                writer.writerow({k: row.get(k, "") for k in fields})
        os.replace(tmp, csv_file)

        counts: dict[str, int] = {
            "working_proxies.txt": len(proxies),
            "working_proxies.json": len(proxies),
            "working_proxies.csv": len(proxies),
        }

        # Protocol files (all four always exist).
        for protocol in ("http", "https", "socks4", "socks5"):
            group = [p for p in proxies if p.protocol == protocol]
            _atomic_write(self.root / "protocols" / f"{protocol}.txt", lines(group, fmt))
            counts[f"protocols/{protocol}.txt"] = len(group)

        # Country files. Every detected code gets a file; majors are created
        # even when empty; everything else also goes to other_countries.txt.
        by_country: dict[str, list[Proxy]] = defaultdict(list)
        for p in proxies:
            code = normalize_country_code(p.country_code) or "XX"
            by_country[code].append(p)
        for code in MAJOR_COUNTRIES:
            by_country.setdefault(code, [])
        other: list[Proxy] = []
        for code, group in by_country.items():
            _atomic_write(self.root / "countries" / f"{code}.txt", lines(group, fmt))
            counts[f"countries/{code}.txt"] = len(group)
            if code not in MAJOR_COUNTRIES:
                other.extend(group)
        _atomic_write(self.root / "countries" / "other_countries.txt", lines(other, fmt))
        counts["countries/other_countries.txt"] = len(other)

        return counts

    def export_filtered(self, proxies: list[Proxy], name: str) -> Path:
        """Write an ad-hoc filtered list to output/filters/."""
        safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in name)[:80]
        path = self.root / "filters" / f"{safe}.txt"
        fmt = self.config.get("export_format", "ip_port")
        _atomic_write(path, "\n".join(p.export_line(fmt) for p in proxies) + ("\n" if proxies else ""))
        return path

    def save_discovered(self, proxies: Iterable[Proxy]) -> Path:
        path = self.root / "discovered_proxies.txt"
        items = list(proxies)
        _atomic_write(path, "\n".join(p.url for p in items) + ("\n" if items else ""))
        return path

    def close(self) -> None:
        try:
            self.conn.commit()
            self.conn.close()
        except Exception:  # noqa: BLE001
            pass
