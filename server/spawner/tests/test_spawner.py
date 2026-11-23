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


class MockJupyterBackend:
    """In-process fake ContainerBackend that spins up a real aiohttp mock Jupyter server."""

    def __init__(self) -> None:
        self.servers: dict[str, TestServer] = {}
        self.tokens: dict[str, str] = {}
        self.stopped: list[str] = []
        self.orphans_cleaned = 0

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
    )
    app = create_app(cfg, backend=backend)

    async with TestClient(TestServer(app)) as client:
        # 1. Health endpoint
        resp = await client.get("/health")
        assert resp.status == 200
        health = await resp.json()
        assert health["status"] == "ok"
        assert health["active_sessions"] == 0

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
