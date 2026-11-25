"""Host resource collection and persistent SQLite usage metrics for the tutorial spawner.

Designed with zero third-party dependencies (Python 3 standard library only) so
`mitchell-tutorial-spawner` can report:
  - Live host CPU %, load averages, total cores, and RAM usage (via Linux `/proc`).
  - Live per-container CPU %, RAM, PIDs, and cumulative CPU-seconds.
  - Persistent historical & funder impact statistics (total sessions launched,
    anonymized unique visitors, peak concurrent users, collective CPU-hours,
    collective student session-hours, and CSV/JSON exports).

Privacy guarantee: only truncated SHA-256 IP hashes are stored (never raw IPs or
user session tokens).
"""

from __future__ import annotations

import csv
from datetime import datetime, timezone
import io
import os
from pathlib import Path
import sqlite3
import threading
import time
from typing import Any


def _utc_iso(ts: float | None) -> str:
    if not ts:
        return ""
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _read_proc_cpu_ticks() -> tuple[int, int] | None:
    """Return (idle_ticks, total_ticks) from /proc/stat, or None if unavailable."""
    try:
        with open("/proc/stat", "r", encoding="utf-8") as fp:
            first = fp.readline()
        if not first.startswith("cpu "):
            return None
        parts = [int(x) for x in first.split()[1:]]
        idle = parts[3] + (parts[4] if len(parts) > 4 else 0)
        total = sum(parts)
        return idle, total
    except OSError:
        return None


def _read_proc_meminfo() -> dict[str, int] | None:
    """Return MemTotal and MemAvailable in bytes from /proc/meminfo."""
    try:
        vals: dict[str, int] = {}
        with open("/proc/meminfo", "r", encoding="utf-8") as fp:
            for line in fp:
                if ":" not in line:
                    continue
                key, rest = line.split(":", 1)
                if key in ("MemTotal", "MemAvailable", "MemFree", "Buffers", "Cached"):
                    num = int(rest.strip().split()[0])
                    vals[key] = num * 1024
        if "MemTotal" not in vals:
            return None
        if "MemAvailable" not in vals:
            vals["MemAvailable"] = (
                vals.get("MemFree", 0)
                + vals.get("Buffers", 0)
                + vals.get("Cached", 0)
            )
        return vals
    except OSError:
        return None


def _read_loadavg() -> tuple[float, float, float]:
    try:
        return os.getloadavg()
    except OSError:
        return (0.0, 0.0, 0.0)


class HostStatsCollector:
    """Lightweight Linux host CPU & memory collector using /proc."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._prev_ticks: tuple[int, int] | None = _read_proc_cpu_ticks()
        self._last_cpu_pct: float = 0.0

    def sample(self) -> dict[str, Any]:
        cpu_cores = os.cpu_count() or 1
        load1, load5, load15 = _read_loadavg()

        cpu_pct = 0.0
        with self._lock:
            cur = _read_proc_cpu_ticks()
            if cur is not None and self._prev_ticks is not None:
                idle_delta = cur[0] - self._prev_ticks[0]
                total_delta = cur[1] - self._prev_ticks[1]
                if total_delta > 0:
                    cpu_pct = max(
                        0.0, min(100.0, 100.0 * (1.0 - idle_delta / total_delta))
                    )
                    self._last_cpu_pct = cpu_pct
                else:
                    cpu_pct = self._last_cpu_pct
            if cur is not None:
                self._prev_ticks = cur

        mem = _read_proc_meminfo()
        if mem:
            mem_total = mem["MemTotal"]
            mem_avail = mem["MemAvailable"]
            mem_used = max(0, mem_total - mem_avail)
            mem_pct = (100.0 * mem_used / mem_total) if mem_total > 0 else 0.0
        else:
            mem_total = mem_avail = mem_used = 0
            mem_pct = 0.0

        gib = 1024.0**3
        return {
            "cpu_cores": cpu_cores,
            "cpu_percent": round(cpu_pct, 1),
            "load_avg_1m": round(load1, 2),
            "load_avg_5m": round(load5, 2),
            "load_avg_15m": round(load15, 2),
            "mem_total_bytes": mem_total,
            "mem_used_bytes": mem_used,
            "mem_available_bytes": mem_avail,
            "mem_total_gb": round(mem_total / gib, 2),
            "mem_used_gb": round(mem_used / gib, 2),
            "mem_available_gb": round(mem_avail / gib, 2),
            "mem_percent": round(mem_pct, 1),
        }


def parse_docker_container_stats(raw: dict[str, Any]) -> dict[str, Any]:
    """Extract normalized CPU %, cumulative CPU seconds, memory, and PIDs from Docker stats JSON."""
    cpu_stats = raw.get("cpu_stats") or {}
    precpu_stats = raw.get("precpu_stats") or {}
    cpu_usage = cpu_stats.get("cpu_usage") or {}
    precpu_usage = precpu_stats.get("cpu_usage") or {}

    total_usage_ns = int(cpu_usage.get("total_usage") or 0)
    prev_total_ns = int(precpu_usage.get("total_usage") or 0)
    system_ns = int(cpu_stats.get("system_cpu_usage") or 0)
    prev_system_ns = int(precpu_stats.get("system_cpu_usage") or 0)

    online_cpus = int(
        cpu_stats.get("online_cpus")
        or len(cpu_usage.get("percpu_usage") or [])
        or 1
    )

    cpu_delta = total_usage_ns - prev_total_ns
    system_delta = system_ns - prev_system_ns
    cpu_percent = 0.0
    if cpu_delta > 0 and system_delta > 0:
        # 100% = 1 full CPU core; a 2-core container can reach 200%
        cpu_percent = (cpu_delta / system_delta) * online_cpus * 100.0

    mem_stats = raw.get("memory_stats") or {}
    stats_detail = mem_stats.get("stats") or {}
    raw_usage = int(mem_stats.get("usage") or 0)
    # Subtract inactive file cache (matches `docker stats` memory calculation on cgroup v1/v2)
    cache = int(
        stats_detail.get("inactive_file")
        or stats_detail.get("total_inactive_file")
        or stats_detail.get("cache")
        or 0
    )
    mem_used = max(0, raw_usage - cache)
    mem_limit = int(mem_stats.get("limit") or 0)
    mem_pct = (100.0 * mem_used / mem_limit) if mem_limit > 0 else 0.0

    pids_stats = raw.get("pids_stats") or {}
    pids = int(pids_stats.get("current") or 0)

    return {
        "cpu_percent": round(cpu_percent, 1),
        "cpu_seconds": round(total_usage_ns / 1e9, 2),
        "mem_bytes": mem_used,
        "mem_mb": round(mem_used / (1024.0**2), 1),
        "mem_limit_bytes": mem_limit,
        "mem_limit_mb": round(mem_limit / (1024.0**2), 1),
        "mem_percent": round(mem_pct, 1),
        "pids": pids,
    }


class MetricsStore:
    """Thread-safe SQLite store for persistent tutorial usage and funder statistics."""

    SNAPSHOT_RETENTION_SECONDS = 90 * 86400  # Keep 90 days of per-minute snapshots

    def __init__(self, db_path: str = "/data/metrics.db") -> None:
        self._lock = threading.Lock()
        self.db_path = self._resolve_writable_path(db_path)
        self._conn = sqlite3.connect(
            self.db_path, check_same_thread=False, timeout=15.0
        )
        self._conn.row_factory = sqlite3.Row
        self._init_schema()

    @staticmethod
    def _resolve_writable_path(requested: str) -> str:
        if requested == ":memory:":
            return requested
        target = Path(requested)
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            with open(target, "a", encoding="utf-8"):
                pass
            return str(target)
        except OSError:
            fallback = Path("/tmp/mitchell-tutorials-metrics.db")
            fallback.parent.mkdir(parents=True, exist_ok=True)
            return str(fallback)

    def _init_schema(self) -> None:
        with self._lock:
            self._conn.execute("PRAGMA journal_mode=WAL;")
            self._conn.execute("PRAGMA synchronous=NORMAL;")
            self._conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS sessions (
                    session_id TEXT PRIMARY KEY,
                    client_ip_hash TEXT NOT NULL,
                    repo TEXT NOT NULL DEFAULT '',
                    started_at REAL NOT NULL,
                    ended_at REAL,
                    duration_seconds REAL NOT NULL DEFAULT 0.0,
                    cpu_seconds REAL NOT NULL DEFAULT 0.0,
                    peak_mem_bytes INTEGER NOT NULL DEFAULT 0,
                    end_reason TEXT NOT NULL DEFAULT ''
                );

                CREATE INDEX IF NOT EXISTS idx_sessions_started_at
                    ON sessions(started_at);

                CREATE TABLE IF NOT EXISTS snapshots (
                    ts REAL PRIMARY KEY,
                    active_sessions INTEGER NOT NULL,
                    host_cpu_pct REAL NOT NULL,
                    host_mem_pct REAL NOT NULL,
                    host_mem_used_gb REAL NOT NULL,
                    containers_cpu_pct REAL NOT NULL,
                    containers_mem_mb REAL NOT NULL
                );

                CREATE TABLE IF NOT EXISTS meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                """
            )
            now = time.time()
            self._conn.execute(
                "INSERT OR IGNORE INTO meta(key, value) VALUES ('first_recorded_at', ?)",
                (str(now),),
            )
            self._conn.execute(
                "INSERT OR IGNORE INTO meta(key, value) VALUES ('peak_concurrent_users', '0')"
            )
            self._conn.execute(
                "INSERT OR IGNORE INTO meta(key, value) VALUES ('peak_concurrent_at', '0')"
            )
            self._conn.commit()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def record_session_start(
        self,
        session_id: str,
        client_ip_hash: str,
        repo: str,
        active_count: int,
        started_at: float | None = None,
    ) -> None:
        ts = started_at if started_at is not None else time.time()
        with self._lock:
            self._conn.execute(
                """
                INSERT OR REPLACE INTO sessions
                    (session_id, client_ip_hash, repo, started_at, ended_at,
                     duration_seconds, cpu_seconds, peak_mem_bytes, end_reason)
                VALUES (?, ?, ?, ?, NULL, 0.0, 0.0, 0, '')
                """,
                (session_id, client_ip_hash, repo, ts),
            )
            row = self._conn.execute(
                "SELECT value FROM meta WHERE key = 'peak_concurrent_users'"
            ).fetchone()
            cur_peak = int(row["value"]) if row else 0
            if active_count > cur_peak:
                self._conn.execute(
                    "UPDATE meta SET value = ? WHERE key = 'peak_concurrent_users'",
                    (str(active_count),),
                )
                self._conn.execute(
                    "UPDATE meta SET value = ? WHERE key = 'peak_concurrent_at'",
                    (str(ts),),
                )
            self._conn.commit()

    def update_session_usage(
        self,
        session_id: str,
        cpu_seconds: float,
        mem_bytes: int,
        now_ts: float | None = None,
    ) -> None:
        now = now_ts if now_ts is not None else time.time()
        with self._lock:
            self._conn.execute(
                """
                UPDATE sessions
                SET cpu_seconds = MAX(cpu_seconds, ?),
                    peak_mem_bytes = MAX(peak_mem_bytes, ?),
                    duration_seconds = MAX(duration_seconds, ? - started_at)
                WHERE session_id = ? AND ended_at IS NULL
                """,
                (float(cpu_seconds), int(mem_bytes), now, session_id),
            )
            self._conn.commit()

    def record_session_end(
        self,
        session_id: str,
        duration_seconds: float,
        cpu_seconds: float,
        peak_mem_bytes: int,
        end_reason: str,
        ended_at: float | None = None,
    ) -> None:
        ts = ended_at if ended_at is not None else time.time()
        with self._lock:
            self._conn.execute(
                """
                UPDATE sessions
                SET ended_at = ?,
                    duration_seconds = MAX(duration_seconds, ?),
                    cpu_seconds = MAX(cpu_seconds, ?),
                    peak_mem_bytes = MAX(peak_mem_bytes, ?),
                    end_reason = ?
                WHERE session_id = ?
                """,
                (
                    ts,
                    max(0.0, float(duration_seconds)),
                    max(0.0, float(cpu_seconds)),
                    max(0, int(peak_mem_bytes)),
                    end_reason,
                    session_id,
                ),
            )
            self._conn.commit()

    def record_snapshot(
        self,
        active_sessions: int,
        host_cpu_pct: float,
        host_mem_pct: float,
        host_mem_used_gb: float,
        containers_cpu_pct: float,
        containers_mem_mb: float,
        ts: float | None = None,
    ) -> None:
        now = ts if ts is not None else time.time()
        cutoff = now - self.SNAPSHOT_RETENTION_SECONDS
        with self._lock:
            self._conn.execute(
                """
                INSERT OR REPLACE INTO snapshots
                    (ts, active_sessions, host_cpu_pct, host_mem_pct,
                     host_mem_used_gb, containers_cpu_pct, containers_mem_mb)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    now,
                    int(active_sessions),
                    round(float(host_cpu_pct), 1),
                    round(float(host_mem_pct), 1),
                    round(float(host_mem_used_gb), 2),
                    round(float(containers_cpu_pct), 1),
                    round(float(containers_mem_mb), 1),
                ),
            )
            self._conn.execute("DELETE FROM snapshots WHERE ts < ?", (cutoff,))
            self._conn.commit()

    def get_summary(
        self,
        live_active_count: int = 0,
        live_cpu_seconds_by_sid: dict[str, float] | None = None,
        live_duration_by_sid: dict[str, float] | None = None,
    ) -> dict[str, Any]:
        now = time.time()
        live_cpu = live_cpu_seconds_by_sid or {}
        live_dur = live_duration_by_sid or {}

        with self._lock:
            meta_rows = {
                r["key"]: r["value"]
                for r in self._conn.execute("SELECT key, value FROM meta").fetchall()
            }

            def _window(since_ts: float | None) -> dict[str, Any]:
                if since_ts is None:
                    row = self._conn.execute(
                        """
                        SELECT
                            COUNT(*) AS cnt,
                            COUNT(DISTINCT client_ip_hash) AS uniq,
                            COALESCE(SUM(cpu_seconds), 0.0) AS cpu_s,
                            COALESCE(SUM(duration_seconds), 0.0) AS dur_s,
                            COALESCE(MAX(peak_mem_bytes), 0) AS max_mem
                        FROM sessions
                        """
                    ).fetchone()
                    active_rows = self._conn.execute(
                        "SELECT session_id, cpu_seconds, duration_seconds FROM sessions WHERE ended_at IS NULL"
                    ).fetchall()
                else:
                    row = self._conn.execute(
                        """
                        SELECT
                            COUNT(*) AS cnt,
                            COUNT(DISTINCT client_ip_hash) AS uniq,
                            COALESCE(SUM(cpu_seconds), 0.0) AS cpu_s,
                            COALESCE(SUM(duration_seconds), 0.0) AS dur_s,
                            COALESCE(MAX(peak_mem_bytes), 0) AS max_mem
                        FROM sessions
                        WHERE started_at >= ?
                        """,
                        (since_ts,),
                    ).fetchone()
                    active_rows = self._conn.execute(
                        "SELECT session_id, cpu_seconds, duration_seconds FROM sessions WHERE ended_at IS NULL AND started_at >= ?",
                        (since_ts,),
                    ).fetchall()

                # Add any unsampled live increments for active sessions
                extra_cpu = 0.0
                extra_dur = 0.0
                for ar in active_rows:
                    sid = ar["session_id"]
                    if sid in live_cpu and live_cpu[sid] > ar["cpu_seconds"]:
                        extra_cpu += live_cpu[sid] - ar["cpu_seconds"]
                    if sid in live_dur and live_dur[sid] > ar["duration_seconds"]:
                        extra_dur += live_dur[sid] - ar["duration_seconds"]

                cnt = int(row["cnt"])
                total_cpu_s = float(row["cpu_s"]) + extra_cpu
                total_dur_s = float(row["dur_s"]) + extra_dur
                return {
                    "sessions": cnt,
                    "unique_visitors": int(row["uniq"]),
                    "cpu_hours": round(total_cpu_s / 3600.0, 3),
                    "session_hours": round(total_dur_s / 3600.0, 2),
                    "avg_duration_minutes": round((total_dur_s / cnt) / 60.0, 1)
                    if cnt > 0
                    else 0.0,
                    "peak_container_mem_mb": round(
                        int(row["max_mem"]) / (1024.0**2), 1
                    ),
                }

            all_time = _window(None)
            last_30d = _window(now - 30 * 86400)
            last_7d = _window(now - 7 * 86400)
            last_24h = _window(now - 86400)

        peak_users = max(
            int(meta_rows.get("peak_concurrent_users", "0")), live_active_count
        )
        peak_at = float(meta_rows.get("peak_concurrent_at", "0"))
        first_at = float(meta_rows.get("first_recorded_at", "0"))

        return {
            "all_time": all_time,
            "last_30d": last_30d,
            "last_7d": last_7d,
            "last_24h": last_24h,
            "peak_concurrent_users": peak_users,
            "peak_concurrent_at": _utc_iso(peak_at) if peak_at > 0 else "",
            "first_recorded_at": _utc_iso(first_at) if first_at > 0 else "",
        }

    def get_timeseries(self, hours: int = 24, max_points: int = 240) -> list[dict[str, Any]]:
        since = time.time() - max(1, hours) * 3600
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT ts, active_sessions, host_cpu_pct, host_mem_pct,
                       host_mem_used_gb, containers_cpu_pct, containers_mem_mb
                FROM snapshots
                WHERE ts >= ?
                ORDER BY ts ASC
                """,
                (since,),
            ).fetchall()

        if not rows:
            return []

        step = max(1, len(rows) // max_points)
        sampled = rows[::step]
        if rows[-1]["ts"] != sampled[-1]["ts"]:
            sampled.append(rows[-1])

        return [
            {
                "ts": r["ts"],
                "iso": _utc_iso(r["ts"]),
                "active_sessions": int(r["active_sessions"]),
                "host_cpu_pct": float(r["host_cpu_pct"]),
                "host_mem_pct": float(r["host_mem_pct"]),
                "host_mem_used_gb": float(r["host_mem_used_gb"]),
                "containers_cpu_pct": float(r["containers_cpu_pct"]),
                "containers_mem_mb": float(r["containers_mem_mb"]),
            }
            for r in sampled
        ]

    def get_recent_sessions(self, limit: int = 25) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT session_id, client_ip_hash, repo, started_at, ended_at,
                       duration_seconds, cpu_seconds, peak_mem_bytes, end_reason
                FROM sessions
                WHERE ended_at IS NOT NULL
                ORDER BY ended_at DESC
                LIMIT ?
                """,
                (int(limit),),
            ).fetchall()
        return [
            {
                "session_id": r["session_id"][:8],
                "visitor_id": r["client_ip_hash"][:6],
                "started_at": _utc_iso(r["started_at"]),
                "ended_at": _utc_iso(r["ended_at"]),
                "duration_seconds": round(float(r["duration_seconds"]), 1),
                "cpu_seconds": round(float(r["cpu_seconds"]), 2),
                "peak_mem_mb": round(int(r["peak_mem_bytes"]) / (1024.0**2), 1),
                "end_reason": r["end_reason"],
            }
            for r in rows
        ]

    def export_funder_csv(self) -> str:
        """Return a grant/funder-ready CSV report with overall summary + daily breakdown."""
        summary = self.get_summary()
        buf = io.StringIO()
        writer = csv.writer(buf)

        writer.writerow(["Mitchell Lab Interactive Tutorials — Server Usage & Impact Report"])
        writer.writerow(["Generated (UTC)", _utc_iso(time.time())])
        writer.writerow(["Tracking Since (UTC)", summary["first_recorded_at"]])
        writer.writerow([])
        writer.writerow(["Summary Metric", "All-Time", "Last 30 Days", "Last 7 Days", "Last 24 Hours"])
        for label, key in (
            ("Sessions Launched", "sessions"),
            ("Unique Visitors (Anonymized)", "unique_visitors"),
            ("Collective CPU-Hours", "cpu_hours"),
            ("Collective Student Session-Hours", "session_hours"),
            ("Average Session Duration (min)", "avg_duration_minutes"),
            ("Peak Container RAM (MiB)", "peak_container_mem_mb"),
        ):
            writer.writerow(
                [
                    label,
                    summary["all_time"][key],
                    summary["last_30d"][key],
                    summary["last_7d"][key],
                    summary["last_24h"][key],
                ]
            )
        writer.writerow(["All-Time Peak Concurrent Users", summary["peak_concurrent_users"], summary["peak_concurrent_at"], "", ""])
        writer.writerow([])
        writer.writerow(
            [
                "Date (UTC)",
                "Sessions Launched",
                "Unique Visitors",
                "Collective CPU-Hours",
                "Student Session-Hours",
                "Peak Concurrent Users",
            ]
        )

        with self._lock:
            daily_sessions = self._conn.execute(
                """
                SELECT
                    strftime('%Y-%m-%d', started_at, 'unixepoch') AS day,
                    COUNT(*) AS sessions,
                    COUNT(DISTINCT client_ip_hash) AS uniq,
                    COALESCE(SUM(cpu_seconds), 0.0) / 3600.0 AS cpu_hrs,
                    COALESCE(SUM(duration_seconds), 0.0) / 3600.0 AS sess_hrs
                FROM sessions
                GROUP BY day
                ORDER BY day DESC
                """
            ).fetchall()
            daily_peaks = {
                r["day"]: int(r["peak"])
                for r in self._conn.execute(
                    """
                    SELECT
                        strftime('%Y-%m-%d', ts, 'unixepoch') AS day,
                        MAX(active_sessions) AS peak
                    FROM snapshots
                    GROUP BY day
                    """
                ).fetchall()
            }

        for r in daily_sessions:
            day = r["day"]
            writer.writerow(
                [
                    day,
                    int(r["sessions"]),
                    int(r["uniq"]),
                    round(float(r["cpu_hrs"]), 4),
                    round(float(r["sess_hrs"]), 3),
                    daily_peaks.get(day, ""),
                ]
            )
        return buf.getvalue()
