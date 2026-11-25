"""Automated tests for the Binder-API Docker spawner and HTTP/WebSocket reverse proxy."""

from __future__ import annotations

import gzip
import json
import sys
import time
from pathlib import Path

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import SpawnerConfig, create_app  # noqa: E402
from metrics import MetricsStore, parse_docker_container_stats  # noqa: E402


class MockJupyterBackend:
    """In-process fake ContainerBackend that spins up a real aiohttp mock Jupyter server."""

    def __init__(self) -> None:
        self.servers: dict[str, TestServer] = {}
        self.tokens: dict[str, str] = {}
        self.stopped: list[str] = []
        self.orphans_cleaned = 0
        self.stats_by_cid: dict[str, dict] = {}

    async def spawn(
        self,
        session_id: str,
        token: str,
        client_ip_hash: str,
        config: SpawnerConfig,
    ) -> tuple[str, str, int]:
        mock_app = web.Application()
        prefix = f"/user/{session_id}"

        async def status(request: web.Request) -> web.Response:
            if request.query.get("token") != token:
                return web.json_response({"error": "unauthorized"}, status=403)
            # Deliberately emit wildcard CORS to verify the proxy strips duplicate headers
            return web.json_response(
                {"started": "2026-01-01T00:00:00Z", "connections": 0},
                headers={"Access-Control-Allow-Origin": "*"},
            )

        async def kernelspecs(request: web.Request) -> web.Response:
            return web.json_response(
                {"default": "julia", "kernelspecs": {"julia": {"name": "julia"}}}
            )

        async def lab_redirect(request: web.Request) -> web.Response:
            resp = web.Response(status=302, headers={"Location": f"{prefix}/lab"})
            resp.set_cookie("_xsrf", "xsrf-val", path=f"{prefix}/")
            resp.set_cookie("username-test", "auth-val", path=f"{prefix}/")
            return resp

        async def lab_gzip_bundle(request: web.Request) -> web.Response:
            payload = gzip.compress(b"console.log('jupyterlab-ok');")
            return web.Response(
                body=payload,
                headers={
                    "Content-Type": "application/javascript",
                    "Content-Encoding": "gzip",
                },
            )

        async def ws_channels(request: web.Request) -> web.WebSocketResponse:
            ws = web.WebSocketResponse(
                protocols=("v1.kernel.websocket.jupyter.org",)
            )
            await ws.prepare(request)
            async for msg in ws:
                if msg.data == "ping-julia":
                    await ws.send_str("pong-julia")
                else:
                    await ws.send_str(f"echo:{msg.data}")
            return ws

        mock_app.router.add_get(f"{prefix}/api/status", status)
        mock_app.router.add_get(f"{prefix}/api/kernelspecs", kernelspecs)
        mock_app.router.add_get(f"{prefix}/lab", lab_redirect)
        mock_app.router.add_get(f"{prefix}/static/lab/bundle.js", lab_gzip_bundle)
        mock_app.router.add_get(f"{prefix}/api/kernels/k1/channels", ws_channels)

        server = TestServer(mock_app)
        await server.start_server()
        cid = f"mock-container-{session_id}"
        self.servers[cid] = server
        self.tokens[cid] = token
        self.stats_by_cid[cid] = {
            "cpu_percent": 42.5,
            "cpu_seconds": 18.0,
            "mem_bytes": 512 * 1024 * 1024,
            "mem_mb": 512.0,
            "mem_limit_bytes": 4 * 1024**3,
            "mem_limit_mb": 4096.0,
            "mem_percent": 12.5,
            "pids": 9,
        }
        return cid, server.host, server.port

    async def stop_and_remove(self, container_id: str) -> None:
        self.stopped.append(container_id)
        server = self.servers.pop(container_id, None)
        if server is not None:
            await server.close()

    async def is_running(self, container_id: str) -> bool:
        return container_id in self.servers

    async def cleanup_orphans(self) -> int:
        self.orphans_cleaned += 1
        return 0

    async def image_info(self, image_name: str) -> dict[str, str]:
        return {
            "kernel_image_id": "sha256:mock1234",
            "kernel_image_created": "2026-01-01T00:00:00Z",
            "kernel_git_sha": "abc1234",
        }

    async def container_stats(self, container_id: str) -> dict | None:
        if container_id not in self.servers:
            return None
        return self.stats_by_cid.get(container_id)


def parse_sse_events(raw: str) -> list[dict]:
    events = []
    for block in raw.strip().split("\n\n"):
        for line in block.splitlines():
            if line.startswith("data: "):
                events.append(json.loads(line[len("data: ") :]))
    return events


@pytest.mark.asyncio
async def test_binder_sse_spawn_http_and_websocket_proxy():
    backend = MockJupyterBackend()
    cfg = SpawnerConfig(
        public_base_url="https://kernels.mitchell.science",
        allowed_origins=("https://mitchell.science",),
        allowed_repos=("siftw/interactivetutorials",),
        max_concurrent_sessions=5,
        max_sessions_per_ip=2,
        cull_interval_seconds=3600,
        metrics_db_path=":memory:",
        metrics_sample_interval_seconds=3600,
    )
    app = create_app(cfg, backend=backend)

    async with TestClient(TestServer(app)) as client:
        # 1. Health endpoint
        resp = await client.get("/health")
        assert resp.status == 200
        health = await resp.json()
        assert health["status"] == "ok"
        assert health["active_sessions"] == 0
        assert health["kernel_git_sha"] == "abc1234"

        # 2. CORS preflight
        pre = await client.options(
            "/build/gh/SiFTW/interactivetutorials/main",
            headers={"Origin": "https://mitchell.science"},
        )
        assert pre.status == 204
        assert pre.headers["Access-Control-Allow-Origin"] == "https://mitchell.science"

        # 3. Binder SSE build stream
        sse_resp = await client.get(
            "/build/gh/SiFTW/interactivetutorials/main",
            headers={"Origin": "https://mitchell.science"},
        )
        assert sse_resp.status == 200
        assert sse_resp.headers["Content-Type"].startswith("text/event-stream")
        assert sse_resp.headers["Access-Control-Allow-Origin"] == "https://mitchell.science"
        events = parse_sse_events(await sse_resp.text())
        assert events[-1]["phase"] == "ready"
        ready_url = events[-1]["url"]
        token = events[-1]["token"]
        assert ready_url.startswith("https://kernels.mitchell.science/user/")
        assert ready_url.endswith("/")
        sid = ready_url.rstrip("/").split("/")[-1]

        # 4. HTTP reverse proxy + single authoritative CORS header
        ks_resp = await client.get(
            f"/user/{sid}/api/kernelspecs?token={token}",
            headers={"Origin": "https://mitchell.science"},
        )
        assert ks_resp.status == 200
        assert ks_resp.headers.getall("Access-Control-Allow-Origin") == [
            "https://mitchell.science"
        ]
        ks_data = await ks_resp.json()
        assert ks_data["default"] == "julia"

        # 4b. JupyterLab auth redirect preserves ALL Set-Cookie headers
        lab_resp = await client.get(
            f"/user/{sid}/lab?token={token}",
            allow_redirects=False,
        )
        assert lab_resp.status == 302
        set_cookies = lab_resp.headers.getall("Set-Cookie")
        assert len(set_cookies) == 2
        assert any(c.startswith("_xsrf=xsrf-val") for c in set_cookies)
        assert any(c.startswith("username-test=auth-val") for c in set_cookies)

        # 4c. Gzipped JupyterLab JS assets stream verbatim without decompression mismatch
        bundle_resp = await client.get(f"/user/{sid}/static/lab/bundle.js")
        assert bundle_resp.status == 200
        assert bundle_resp.headers.get("Content-Encoding") == "gzip"
        assert (await bundle_resp.text()) == "console.log('jupyterlab-ok');"

        # 5. WebSocket reverse proxy (Jupyter kernel channel protocol)
        async with client.ws_connect(
            f"/user/{sid}/api/kernels/k1/channels?token={token}",
            protocols=("v1.kernel.websocket.jupyter.org",),
        ) as ws:
            assert ws.protocol == "v1.kernel.websocket.jupyter.org"
            await ws.send_str("ping-julia")
            reply = await ws.receive_str()
            assert reply == "pong-julia"

    # Cleanup stops all spawned containers
    assert len(backend.stopped) == 1


@pytest.mark.asyncio
async def test_disallowed_repo_rejected():
    backend = MockJupyterBackend()
    cfg = SpawnerConfig(
        allowed_repos=("siftw/interactivetutorials",),
        cull_interval_seconds=3600,
        metrics_db_path=":memory:",
        metrics_sample_interval_seconds=3600,
    )
    app = create_app(cfg, backend=backend)

    async with TestClient(TestServer(app)) as client:
        resp = await client.get("/build/gh/evilorg/cryptominer/main")
        assert resp.status == 200
        events = parse_sse_events(await resp.text())
        assert events[-1]["phase"] == "failed"
        assert "not permitted" in events[-1]["message"].lower()
        assert len(backend.servers) == 0


@pytest.mark.asyncio
async def test_session_limits_and_idle_culler():
    backend = MockJupyterBackend()
    cfg = SpawnerConfig(
        allowed_repos=("siftw/interactivetutorials",),
        max_concurrent_sessions=1,
        max_sessions_per_ip=1,
        idle_timeout_seconds=10,
        cull_interval_seconds=3600,
        metrics_db_path=":memory:",
        metrics_sample_interval_seconds=3600,
    )
    app = create_app(cfg, backend=backend)

    async with TestClient(TestServer(app)) as client:
        # First spawn succeeds
        r1 = await client.get("/build/gh/SiFTW/interactivetutorials/main")
        e1 = parse_sse_events(await r1.text())
        assert e1[-1]["phase"] == "ready"
        sid = e1[-1]["url"].rstrip("/").split("/")[-1]

        # Second spawn rejected due to capacity limit
        r2 = await client.get("/build/gh/SiFTW/interactivetutorials/main")
        e2 = parse_sse_events(await r2.text())
        assert e2[-1]["phase"] == "failed"
        assert "capacity" in e2[-1]["message"].lower()

        # Simulate idle timeout and run culler
        spawner = app["spawner"]
        spawner.sessions[sid].last_seen = time.monotonic() - 30
        culled = await spawner.cull_once()
        assert culled == [sid]
        assert sid not in spawner.sessions
        assert len(backend.stopped) == 1

        # Expired session now returns 404
        r404 = await client.get(f"/user/{sid}/api/status")
        assert r404.status == 404


def test_parse_docker_container_stats():
    raw = {
        "cpu_stats": {
            "cpu_usage": {"total_usage": 5_000_000_000},
            "system_cpu_usage": 20_000_000_000,
            "online_cpus": 4,
        },
        "precpu_stats": {
            "cpu_usage": {"total_usage": 4_000_000_000},
            "system_cpu_usage": 16_000_000_000,
        },
        "memory_stats": {
            "usage": 600 * 1024 * 1024,
            "limit": 4 * 1024**3,
            "stats": {"inactive_file": 88 * 1024 * 1024},
        },
        "pids_stats": {"current": 14},
    }
    parsed = parse_docker_container_stats(raw)
    assert parsed["cpu_percent"] == 100.0
    assert parsed["cpu_seconds"] == 5.0
    assert parsed["mem_mb"] == 512.0
    assert parsed["mem_limit_mb"] == 4096.0
    assert parsed["mem_percent"] == 12.5
    assert parsed["pids"] == 14


def test_metrics_store_summary_timeseries_and_csv(tmp_path: Path):
    db_file = tmp_path / "metrics.db"
    store = MetricsStore(str(db_file))
    try:
        now = time.time()
        # Session 1 (completed 2 days ago)
        store.record_session_start(
            "sess0001aaaa", "visitor111111", "gh/SiFTW/interactivetutorials", active_count=1, started_at=now - 2 * 86400
        )
        store.record_session_end(
            "sess0001aaaa",
            duration_seconds=1800.0,
            cpu_seconds=360.0,
            peak_mem_bytes=1024 * 1024 * 600,
            end_reason="idle timeout",
            ended_at=now - 2 * 86400 + 1800.0,
        )

        # Session 2 (active right now from a different visitor, peak concurrency = 3)
        store.record_session_start(
            "sess0002bbbb", "visitor222222", "gh/SiFTW/interactivetutorials", active_count=3, started_at=now - 600
        )
        store.update_session_usage("sess0002bbbb", cpu_seconds=90.0, mem_bytes=1024 * 1024 * 400, now_ts=now)

        # Snapshot points
        store.record_snapshot(
            active_sessions=3,
            host_cpu_pct=55.5,
            host_mem_pct=48.2,
            host_mem_used_gb=31.0,
            containers_cpu_pct=120.0,
            containers_mem_mb=1536.0,
            ts=now - 120,
        )
        store.record_snapshot(
            active_sessions=1,
            host_cpu_pct=18.0,
            host_mem_pct=30.0,
            host_mem_used_gb=19.2,
            containers_cpu_pct=40.0,
            containers_mem_mb=512.0,
            ts=now - 60,
        )

        summary = store.get_summary(
            live_active_count=1,
            live_cpu_seconds_by_sid={"sess0002bbbb": 180.0},
            live_duration_by_sid={"sess0002bbbb": 900.0},
        )
        assert summary["all_time"]["sessions"] == 2
        assert summary["all_time"]["unique_visitors"] == 2
        # 360s (sess1) + 180s (live sess2) = 540s = 0.15 CPU-hours
        assert summary["all_time"]["cpu_hours"] == 0.15
        # 1800s + 900s = 2700s = 0.75 session-hours
        assert summary["all_time"]["session_hours"] == 0.75
        assert summary["all_time"]["peak_container_mem_mb"] == 600.0
        assert summary["last_24h"]["sessions"] == 1
        assert summary["last_7d"]["sessions"] == 2
        assert summary["peak_concurrent_users"] == 3
        assert summary["peak_concurrent_at"]

        series = store.get_timeseries(hours=24)
        assert len(series) == 2
        assert series[0]["active_sessions"] == 3
        assert series[1]["active_sessions"] == 1

        recent = store.get_recent_sessions(limit=10)
        assert len(recent) == 1
        assert recent[0]["session_id"] == "sess0001"
        assert recent[0]["end_reason"] == "idle timeout"

        csv_text = store.export_funder_csv()
        assert "Mitchell Lab Interactive Tutorials" in csv_text
        assert "Sessions Launched,2,2,2,1" in csv_text
        assert "All-Time Peak Concurrent Users,3," in csv_text
        assert "Date (UTC),Sessions Launched,Unique Visitors" in csv_text
    finally:
        store.close()


@pytest.mark.asyncio
async def test_admin_dashboard_open_readonly_mode():
    backend = MockJupyterBackend()
    cfg = SpawnerConfig(
        allowed_repos=("siftw/interactivetutorials",),
        max_concurrent_sessions=10,
        max_sessions_per_ip=2,
        cull_interval_seconds=3600,
        admin_token="",
        metrics_db_path=":memory:",
        metrics_sample_interval_seconds=3600,
    )
    app = create_app(cfg, backend=backend)

    async with TestClient(TestServer(app)) as client:
        # Both /admin and /admin/ serve the HTML dashboard
        for path in ("/admin", "/admin/"):
            page = await client.get(path)
            assert page.status == 200
            html_body = await page.text()
            assert "Mitchell Lab Tutorial Server" in html_body
            assert "Live Status &amp; Usage Statistics" in html_body

        # Spawn one active student session
        sse = await client.get("/build/gh/SiFTW/interactivetutorials/main")
        events = parse_sse_events(await sse.text())
        assert events[-1]["phase"] == "ready"
        sid = events[-1]["url"].rstrip("/").split("/")[-1]
        user_token = events[-1]["token"]

        # Stats API works without auth in open read-only mode
        stats_resp = await client.get("/api/admin/stats?hours=24")
        assert stats_resp.status == 200
        raw_stats = await stats_resp.text()
        assert user_token not in raw_stats  # Never leak student session tokens!

        data = json.loads(raw_stats)
        assert data["can_manage"] is False
        assert data["admin_login_enabled"] is False
        assert data["server"]["active_sessions"] == 1
        assert data["server"]["max_sessions"] == 10
        assert data["host"]["cpu_cores"] >= 1
        assert len(data["containers"]) == 1
        assert data["containers"][0]["session_id"] == sid
        assert data["containers"][0]["cpu_percent"] == 42.5
        assert data["containers"][0]["mem_mb"] == 512.0
        assert data["summary"]["all_time"]["sessions"] == 1
        assert data["summary"]["peak_concurrent_users"] >= 1

        # CSV export works without auth and never leaks student tokens
        csv_resp = await client.get("/api/admin/export.csv")
        assert csv_resp.status == 200
        assert "text/csv" in csv_resp.headers["Content-Type"]
        csv_body = await csv_resp.text()
        assert "Sessions Launched,1,1,1,1" in csv_body
        assert user_token not in csv_body

        # Admin verify and stopping containers return 403 when ADMIN_TOKEN is not configured
        assert (await client.post("/api/admin/verify")).status == 403
        stop_resp = await client.post(f"/api/admin/sessions/{sid}/stop")
        assert stop_resp.status == 403


@pytest.mark.asyncio
async def test_admin_dashboard_token_protected_and_stop_session():
    backend = MockJupyterBackend()
    cfg = SpawnerConfig(
        allowed_repos=("siftw/interactivetutorials",),
        max_concurrent_sessions=10,
        max_sessions_per_ip=2,
        cull_interval_seconds=3600,
        admin_token="secret-admin-token",
        metrics_db_path=":memory:",
        metrics_sample_interval_seconds=3600,
    )
    app = create_app(cfg, backend=backend)

    async with TestClient(TestServer(app)) as client:
        # /admin serves the open read-only dashboard with the Admin Login button enabled
        page = await client.get("/admin")
        assert page.status == 200
        page_html = await page.text()
        assert "const ADMIN_LOGIN_ENABLED = true;" in page_html
        assert "Admin Login" in page_html

        # Spawn one active session
        sse = await client.get("/build/gh/SiFTW/interactivetutorials/main")
        events = parse_sse_events(await sse.text())
        assert events[-1]["phase"] == "ready"
        sid = events[-1]["url"].rstrip("/").split("/")[-1]
        user_token = events[-1]["token"]

        # Read-only stats and CSV remain open without password (can_manage=False)
        anon_stats = await client.get("/api/admin/stats")
        assert anon_stats.status == 200
        anon_raw = await anon_stats.text()
        assert user_token not in anon_raw
        anon_data = json.loads(anon_raw)
        assert anon_data["can_manage"] is False
        assert anon_data["admin_login_enabled"] is True
        assert anon_data["server"]["active_sessions"] == 1

        anon_csv = await client.get("/api/admin/export.csv")
        assert anon_csv.status == 200
        assert "Mitchell Lab Interactive Tutorials" in (await anon_csv.text())

        # Admin verify and write actions require valid ADMIN_TOKEN
        assert (await client.post("/api/admin/verify")).status == 401
        assert (
            await client.post(
                "/api/admin/verify", headers={"Authorization": "Bearer wrong-token"}
            )
        ).status == 401
        assert (await client.post(f"/api/admin/sessions/{sid}/stop")).status == 401
        assert (
            await client.post(
                f"/api/admin/sessions/{sid}/stop",
                headers={"Authorization": "Bearer wrong-token"},
            )
        ).status == 401

        # Valid admin password unlocks verify & can_manage=True
        auth_headers = {"Authorization": "Bearer secret-admin-token"}
        verify_resp = await client.post("/api/admin/verify", headers=auth_headers)
        assert verify_resp.status == 200
        assert (await verify_resp.json()) == {"authenticated": True}

        stats_resp = await client.get("/api/admin/stats", headers=auth_headers)
        assert stats_resp.status == 200
        raw_stats = await stats_resp.text()
        assert user_token not in raw_stats
        data = json.loads(raw_stats)
        assert data["can_manage"] is True
        assert data["admin_login_enabled"] is True
        assert data["server"]["active_sessions"] == 1

        # Stop the active container as admin
        stop_resp = await client.post(
            f"/api/admin/sessions/{sid}/stop", headers=auth_headers
        )
        assert stop_resp.status == 200
        assert (await stop_resp.json()) == {"status": "stopped", "session_id": sid}
        assert len(backend.stopped) == 1

        # Stopping a non-existent session returns 404
        stop_missing = await client.post(
            f"/api/admin/sessions/{sid}/stop", headers=auth_headers
        )
        assert stop_missing.status == 404

        # Stats now show 0 active sessions and 1 recent session stopped by admin
        after_resp = await client.get("/api/admin/stats", headers=auth_headers)
        assert after_resp.status == 200
        after_data = await after_resp.json()
        assert after_data["server"]["active_sessions"] == 0
        assert len(after_data["recent_sessions"]) == 1
        assert after_data["recent_sessions"][0]["end_reason"] == "stopped by admin"


@pytest.mark.asyncio
async def test_user_self_service_stop_frees_quota_immediately():
    backend = MockJupyterBackend()
    cfg = SpawnerConfig(
        allowed_repos=("siftw/interactivetutorials",),
        max_concurrent_sessions=5,
        max_sessions_per_ip=1,
        cull_interval_seconds=3600,
        metrics_db_path=":memory:",
        metrics_sample_interval_seconds=3600,
    )
    assert SpawnerConfig().max_sessions_per_ip == 30
    app = create_app(cfg, backend=backend)

    async with TestClient(TestServer(app)) as client:
        r1 = await client.get("/build/gh/SiFTW/interactivetutorials/main")
        e1 = parse_sse_events(await r1.text())
        assert e1[-1]["phase"] == "ready"
        sid1 = e1[-1]["url"].rstrip("/").split("/")[-1]
        tok1 = e1[-1]["token"]

        # Without stopping, a 2nd session from same IP is blocked while active/fresh
        r_blocked = await client.get("/build/gh/SiFTW/interactivetutorials/main")
        e_blocked = parse_sse_events(await r_blocked.text())
        assert e_blocked[-1]["phase"] == "failed"
        assert "already have 1 active" in e_blocked[-1]["message"].lower()

        # Wrong or missing token is rejected with 403
        assert (await client.post(f"/api/sessions/{sid1}/stop")).status == 403
        assert (
            await client.post(f"/api/sessions/{sid1}/stop?token=wrong-token")
        ).status == 403
        assert (await client.delete(f"/user/{sid1}/?token=wrong-token")).status == 403

        # Valid token stops container and frees the per-IP slot immediately
        stop_resp = await client.post(f"/api/sessions/{sid1}/stop?token={tok1}")
        assert stop_resp.status == 200
        assert (await stop_resp.json()) == {"status": "stopped", "session_id": sid1}
        assert len(backend.stopped) == 1

        # Calling stop again is idempotent (returns 200 gone)
        again_resp = await client.post(f"/api/sessions/{sid1}/stop?token={tok1}")
        assert again_resp.status == 200
        assert (await again_resp.json()) == {"status": "gone", "session_id": sid1}

        # Spawning a fresh session succeeds immediately, and DELETE /user/{sid}/ also stops it
        r2 = await client.get("/build/gh/SiFTW/interactivetutorials/main")
        e2 = parse_sse_events(await r2.text())
        assert e2[-1]["phase"] == "ready"
        sid2 = e2[-1]["url"].rstrip("/").split("/")[-1]
        tok2 = e2[-1]["token"]

        del_resp = await client.delete(
            f"/user/{sid2}/", headers={"Authorization": f"token {tok2}"}
        )
        assert del_resp.status == 200
        assert (await del_resp.json()) == {"status": "stopped", "session_id": sid2}
        assert len(backend.stopped) == 2


@pytest.mark.asyncio
async def test_reclaims_abandoned_disconnected_session_before_rejecting():
    backend = MockJupyterBackend()
    cfg = SpawnerConfig(
        allowed_repos=("siftw/interactivetutorials",),
        max_concurrent_sessions=5,
        max_sessions_per_ip=1,
        cull_interval_seconds=3600,
        metrics_db_path=":memory:",
        metrics_sample_interval_seconds=3600,
    )
    app = create_app(cfg, backend=backend)

    async with TestClient(TestServer(app)) as client:
        r1 = await client.get("/build/gh/SiFTW/interactivetutorials/main")
        e1 = parse_sse_events(await r1.text())
        assert e1[-1]["phase"] == "ready"
        sid1 = e1[-1]["url"].rstrip("/").split("/")[-1]

        spawner = app["spawner"]
        # Mark session as idle for 3 minutes, but WITH an active WebSocket: must NOT be reclaimed
        spawner.sessions[sid1].last_seen = time.monotonic() - 180
        spawner.sessions[sid1].active_ws = 1
        r_ws = await client.get("/build/gh/SiFTW/interactivetutorials/main")
        e_ws = parse_sse_events(await r_ws.text())
        assert e_ws[-1]["phase"] == "failed"
        assert sid1 in spawner.sessions

        # Once disconnected (active_ws=0) and idle >= 120s, it IS reclaimed automatically
        spawner.sessions[sid1].active_ws = 0
        r2 = await client.get("/build/gh/SiFTW/interactivetutorials/main")
        e2 = parse_sse_events(await r2.text())
        assert e2[-1]["phase"] == "ready"
        sid2 = e2[-1]["url"].rstrip("/").split("/")[-1]
        assert sid1 not in spawner.sessions
        assert sid2 in spawner.sessions
        assert len(backend.stopped) == 1



