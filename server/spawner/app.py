"""Lightweight BinderHub-compatible Docker spawner and HTTP/WebSocket reverse proxy.

Designed to run completely independently alongside an existing production JupyterHub
without modifying any existing JupyterHub configuration, ports, or networks.

Protocol compatibility:
  - GET /build/{provider}/{spec}  -> Server-Sent Events (BinderHub v2 protocol used by
                                     Jupyter Book 2 / MyST / thebe-core)
  - GET /v2/{provider}/{spec}     -> Browser launch page that connects to /build/...
                                     and redirects to the user's JupyterLab session
  - ANY /user/{sid}/{path}        -> Full HTTP + WebSocket reverse proxy to the user's
                                     ephemeral, resource-capped Julia container
  - GET /health                   -> JSON health & capacity summary
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
import hashlib
import html
import ipaddress
import json
import logging
import os
import re
import secrets
import time
from typing import Any, Protocol

from aiohttp import ClientSession, ClientTimeout, WSMsgType, web
import docker
from docker.errors import APIError, NotFound
from multidict import CIMultiDict

LOG = logging.getLogger("mitchell.spawner")

MANAGED_LABEL_KEY = "managed-by"
MANAGED_LABEL_VALUE = "mitchell-tutorial-spawner"

HOP_BY_HOP_HEADERS = frozenset(
    {
        "connection",
        "keep-alive",
        "proxy-authenticate",
        "proxy-authorization",
        "te",
        "trailers",
        "transfer-encoding",
        "upgrade",
        "host",
    }
)


@dataclass(frozen=True)
class SpawnerConfig:
    listen_host: str = "0.0.0.0"
    listen_port: int = 8787
    public_base_url: str = ""
    kernel_image: str = "mitchell-lab/julia-tutorial-kernel:latest"
    user_network: str = "tutorials_user_net"
    user_subnet: str = ""
    allowed_origins: tuple[str, ...] = (
        "https://mitchell.science",
        "https://www.mitchell.science",
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    )
    allowed_origin_regex: str = ""
    allowed_repos: tuple[str, ...] = ("siftw/interactivetutorials",)
    max_concurrent_sessions: int = 20
    max_sessions_per_ip: int = 3
    container_mem_limit: str = "2g"
    container_nano_cpus: int = 2_000_000_000
    container_pids_limit: int = 256
    idle_timeout_seconds: int = 1200
    max_session_age_seconds: int = 7200
    spawn_timeout_seconds: int = 45
    cull_interval_seconds: int = 30

    @classmethod
    def from_env(cls) -> "SpawnerConfig":
        def _csv(name: str, default: tuple[str, ...]) -> tuple[str, ...]:
            raw = os.environ.get(name)
            if raw is None:
                return default
            return tuple(item.strip() for item in raw.split(",") if item.strip())

        return cls(
            listen_host=os.environ.get("SPAWNER_HOST", "0.0.0.0"),
            listen_port=int(os.environ.get("SPAWNER_PORT", "8787")),
            public_base_url=os.environ.get("PUBLIC_BASE_URL", "").rstrip("/"),
            kernel_image=os.environ.get(
                "KERNEL_IMAGE", "mitchell-lab/julia-tutorial-kernel:latest"
            ),
            user_network=os.environ.get("USER_NETWORK", "tutorials_user_net"),
            user_subnet=os.environ.get("USER_SUBNET", "").strip(),
            allowed_origins=_csv(
                "ALLOWED_ORIGINS",
                (
                    "https://mitchell.science",
                    "https://www.mitchell.science",
                    "http://localhost:3000",
                    "http://127.0.0.1:3000",
                ),
            ),
            allowed_origin_regex=os.environ.get("ALLOWED_ORIGIN_REGEX", "").strip(),
            allowed_repos=tuple(
                r.lower() for r in _csv("ALLOWED_REPOS", ("siftw/interactivetutorials",))
            ),
            max_concurrent_sessions=int(os.environ.get("MAX_CONCURRENT_SESSIONS", "20")),
            max_sessions_per_ip=int(os.environ.get("MAX_SESSIONS_PER_IP", "3")),
            container_mem_limit=os.environ.get("CONTAINER_MEM_LIMIT", "2g"),
            container_nano_cpus=int(
                float(os.environ.get("CONTAINER_CPUS", "2.0")) * 1_000_000_000
            ),
            container_pids_limit=int(os.environ.get("CONTAINER_PIDS_LIMIT", "256")),
            idle_timeout_seconds=int(os.environ.get("IDLE_TIMEOUT_SECONDS", "1200")),
            max_session_age_seconds=int(
                os.environ.get("MAX_SESSION_AGE_SECONDS", "7200")
            ),
            spawn_timeout_seconds=int(os.environ.get("SPAWN_TIMEOUT_SECONDS", "45")),
            cull_interval_seconds=int(os.environ.get("CULL_INTERVAL_SECONDS", "30")),
        )


@dataclass
class UserSession:
    session_id: str
    token: str
    container_id: str
    upstream_host: str
    upstream_port: int
    client_ip_hash: str
    created_at: float = field(default_factory=time.monotonic)
    last_seen: float = field(default_factory=time.monotonic)
    active_ws: int = 0

    @property
    def upstream_http_base(self) -> str:
        return f"http://{self.upstream_host}:{self.upstream_port}"

    @property
    def upstream_ws_base(self) -> str:
        return f"ws://{self.upstream_host}:{self.upstream_port}"


class ContainerBackend(Protocol):
    """Abstract interface for spawning and managing isolated user containers."""

    async def spawn(
        self,
        session_id: str,
        token: str,
        client_ip_hash: str,
        config: SpawnerConfig,
    ) -> tuple[str, str, int]:
        """Spawn a container and return (container_id, upstream_host, upstream_port)."""

    async def stop_and_remove(self, container_id: str) -> None:
        """Stop and remove a container, ignoring already-removed containers."""

    async def is_running(self, container_id: str) -> bool:
        """Return True if the container still exists and is running."""

    async def cleanup_orphans(self) -> int:
        """Remove any stale containers left behind by previous spawner runs."""


class DockerBackend:
    """Production ContainerBackend backed by the local Docker daemon."""

    def __init__(self) -> None:
        self._client = docker.from_env()

    def _spawn_sync(
        self,
        session_id: str,
        token: str,
        client_ip_hash: str,
        config: SpawnerConfig,
    ) -> tuple[str, str, int]:
        base_url = f"/user/{session_id}/"
        cmd = [
            "jupyter",
            "server",
            "--ServerApp.ip=0.0.0.0",
            "--ServerApp.port=8888",
            f"--ServerApp.base_url={base_url}",
            f"--ServerApp.token={token}",
            "--ServerApp.password=",
            "--ServerApp.disable_check_xsrf=True",
            "--ServerApp.allow_origin=*",
            "--ServerApp.allow_remote_access=True",
            "--ServerApp.open_browser=False",
            "--ServerApp.default_url=/lab",
            "--ServerApp.root_dir=/home/jovyan/work",
            f"--MappingKernelManager.cull_idle_timeout={config.idle_timeout_seconds}",
            "--MappingKernelManager.cull_interval=60",
        ]
        container = self._client.containers.run(
            image=config.kernel_image,
            command=cmd,
            detach=True,
            auto_remove=True,
            name=f"tutorial-julia-{session_id}",
            network=config.user_network,
            mem_limit=config.container_mem_limit,
            memswap_limit=config.container_mem_limit,
            nano_cpus=config.container_nano_cpus,
            pids_limit=config.container_pids_limit,
            cap_drop=["ALL"],
            security_opt=["no-new-privileges:true"],
            labels={
                MANAGED_LABEL_KEY: MANAGED_LABEL_VALUE,
                "session-id": session_id,
                "client-ip-hash": client_ip_hash,
                "created-at": str(int(time.time())),
            },
        )
        # Wait briefly for Docker to populate the container's IP on the internal network
        ip_address = ""
        for _ in range(30):
            container.reload()
            networks = container.attrs.get("NetworkSettings", {}).get("Networks", {})
            net_info = networks.get(config.user_network)
            if net_info and net_info.get("IPAddress"):
                ip_address = net_info["IPAddress"]
                break
            time.sleep(0.1)

        if not ip_address:
            try:
                container.stop(timeout=2)
            except Exception:
                pass
            raise RuntimeError(
                f"Container {container.id[:12]} did not receive an IP on network "
                f"'{config.user_network}'"
            )

        return container.id, ip_address, 8888

    async def spawn(
        self,
        session_id: str,
        token: str,
        client_ip_hash: str,
        config: SpawnerConfig,
    ) -> tuple[str, str, int]:
        return await asyncio.to_thread(
            self._spawn_sync, session_id, token, client_ip_hash, config
        )

    def _stop_sync(self, container_id: str) -> None:
        try:
            container = self._client.containers.get(container_id)
            container.stop(timeout=3)
            try:
                container.remove(force=True)
            except NotFound:
                pass
        except NotFound:
            pass
        except APIError as exc:
            LOG.warning("Docker error stopping %s: %s", container_id[:12], exc)

    async def stop_and_remove(self, container_id: str) -> None:
        await asyncio.to_thread(self._stop_sync, container_id)

    def _is_running_sync(self, container_id: str) -> bool:
        try:
            container = self._client.containers.get(container_id)
            return container.status == "running"
        except NotFound:
            return False
        except APIError:
            return False

    async def is_running(self, container_id: str) -> bool:
        return await asyncio.to_thread(self._is_running_sync, container_id)

    def _cleanup_orphans_sync(self) -> int:
        removed = 0
        containers = self._client.containers.list(
            all=True,
            filters={"label": f"{MANAGED_LABEL_KEY}={MANAGED_LABEL_VALUE}"},
        )
        for container in containers:
            try:
                container.stop(timeout=2)
            except Exception:
                pass
            try:
                container.remove(force=True)
            except Exception:
                pass
            removed += 1
        return removed

    async def cleanup_orphans(self) -> int:
        return await asyncio.to_thread(self._cleanup_orphans_sync)


class TutorialSpawnerApp:
    """Core application state, session registry, Binder API, proxy, and idle culler."""

    def __init__(self, config: SpawnerConfig, backend: ContainerBackend) -> None:
        self.config = config
        self.backend = backend
        self.sessions: dict[str, UserSession] = {}
        self.started_at = time.monotonic()
        self._lock = asyncio.Lock()
        self._http_client: ClientSession | None = None
        self._culler_task: asyncio.Task[None] | None = None
        self._origin_re = (
            re.compile(config.allowed_origin_regex)
            if config.allowed_origin_regex
            else None
        )
        self._blocked_network = (
            ipaddress.ip_network(config.user_subnet, strict=False)
            if config.user_subnet
            else None
        )

    def _match_allowed_origin(self, origin: str | None) -> str | None:
        if not origin:
            return None
        if "*" in self.config.allowed_origins:
            return origin
        if origin in self.config.allowed_origins:
            return origin
        if self._origin_re and self._origin_re.match(origin):
            return origin
        return None

    def _apply_cors(self, request: web.Request, response: web.StreamResponse) -> None:
        # Remove any upstream CORS headers to avoid duplicate header rejections
        for key in list(response.headers.keys()):
            if key.lower().startswith("access-control-"):
                del response.headers[key]

        origin = request.headers.get("Origin")
        allowed = self._match_allowed_origin(origin)
        if allowed:
            response.headers["Access-Control-Allow-Origin"] = allowed
            response.headers["Vary"] = "Origin"
            response.headers["Access-Control-Allow-Credentials"] = "true"
            response.headers["Access-Control-Allow-Methods"] = (
                "GET, POST, PUT, PATCH, DELETE, OPTIONS"
            )
            response.headers["Access-Control-Allow-Headers"] = (
                "Authorization, Content-Type, X-XSRFToken, X-Requested-With, Cache-Control"
            )
            response.headers["Access-Control-Max-Age"] = "600"

    def _is_from_user_container(self, request: web.Request) -> bool:
        peer = request.remote
        if not peer:
            return False
        try:
            peer_ip = ipaddress.ip_address(peer)
            if peer_ip.is_loopback:
                return False
            if self._blocked_network is not None and peer_ip in self._blocked_network:
                return True
        except ValueError:
            pass
        return any(s.upstream_host == peer for s in self.sessions.values())

    def _client_ip_hash(self, request: web.Request) -> str:
        # Prefer Cloudflare's verified client IP header, then X-Forwarded-For, then peer IP
        raw_ip = (
            request.headers.get("CF-Connecting-IP")
            or (request.headers.get("X-Forwarded-For", "").split(",")[0].strip())
            or (request.remote or "unknown")
        )
        return hashlib.sha256(raw_ip.encode("utf-8")).hexdigest()[:16]

    def _public_base_url(self, request: web.Request) -> str:
        if self.config.public_base_url:
            return self.config.public_base_url
        proto = request.headers.get("X-Forwarded-Proto", request.scheme)
        host = request.headers.get("X-Forwarded-Host", request.host)
        return f"{proto}://{host}".rstrip("/")

    def _is_repo_allowed(self, provider: str, spec: str) -> bool:
        if not self.config.allowed_repos:
            return True
        if provider not in {"gh", "github", "git"}:
            return False
        parts = [p for p in spec.strip("/").split("/") if p]
        if len(parts) < 2:
            return False
        repo = f"{parts[0]}/{parts[1]}".lower()
        return repo in self.config.allowed_repos

    async def _destroy_session(self, session_id: str, reason: str) -> None:
        async with self._lock:
            session = self.sessions.pop(session_id, None)
        if session is None:
            return
        LOG.info(
            "Removing session %s (container %s): %s",
            session_id,
            session.container_id[:12],
            reason,
        )
        await self.backend.stop_and_remove(session.container_id)

    async def _wait_until_ready(
        self,
        session: UserSession,
        sse_send: Any,
    ) -> bool:
        assert self._http_client is not None
        status_url = (
            f"{session.upstream_http_base}/user/{session.session_id}/api/status"
            f"?token={session.token}"
        )
        deadline = time.monotonic() + self.config.spawn_timeout_seconds
        last_heartbeat = 0.0
        while time.monotonic() < deadline:
            now = time.monotonic()
            if now - last_heartbeat >= 2.0:
                await sse_send("launching", "Starting isolated Julia kernel server...")
                last_heartbeat = now
            try:
                async with self._http_client.get(
                    status_url, timeout=ClientTimeout(total=2)
                ) as resp:
                    if resp.status == 200:
                        return True
            except Exception:
                pass
            await asyncio.sleep(0.35)
        return False

    async def handle_health(self, request: web.Request) -> web.Response:
        return web.json_response(
            {
                "status": "ok",
                "active_sessions": len(self.sessions),
                "max_sessions": self.config.max_concurrent_sessions,
                "kernel_image": self.config.kernel_image,
                "uptime_seconds": round(time.monotonic() - self.started_at, 1),
            }
        )

    async def handle_binder_build(self, request: web.Request) -> web.StreamResponse:
        """BinderHub-compatible SSE endpoint: GET /build/{provider}/{spec}."""
        provider = request.match_info["provider"].lower()
        spec = request.match_info["spec"]

        response = web.StreamResponse(
            status=200,
            headers={
                "Content-Type": "text/event-stream; charset=utf-8",
                "Cache-Control": "no-cache, no-transform",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )
        self._apply_cors(request, response)
        await response.prepare(request)

        async def sse_send(phase: str, message: str, **extra: Any) -> None:
            payload = {"phase": phase, "message": message, **extra}
            chunk = f"data: {json.dumps(payload)}\n\n".encode("utf-8")
            await response.write(chunk)

        if not self._is_repo_allowed(provider, spec):
            await sse_send(
                "failed",
                f"Repository '{provider}/{spec}' is not permitted on this tutorial server.",
            )
            await response.write_eof()
            return response

        ip_hash = self._client_ip_hash(request)
        async with self._lock:
            if len(self.sessions) >= self.config.max_concurrent_sessions:
                await sse_send(
                    "failed",
                    "The tutorial compute server is currently at capacity. "
                    "Please try again in a minute.",
                )
                await response.write_eof()
                return response

            ip_sessions = sum(
                1 for s in self.sessions.values() if s.client_ip_hash == ip_hash
            )
            if ip_sessions >= self.config.max_sessions_per_ip:
                await sse_send(
                    "failed",
                    f"You already have {ip_sessions} active tutorial sessions. "
                    "Close an existing tab or wait for idle sessions to expire.",
                )
                await response.write_eof()
                return response

            session_id = secrets.token_hex(8)
            token = secrets.token_urlsafe(24)
            # Reserve a placeholder slot immediately to avoid races under burst load
            placeholder = UserSession(
                session_id=session_id,
                token=token,
                container_id="pending",
                upstream_host="",
                upstream_port=0,
                client_ip_hash=ip_hash,
            )
            self.sessions[session_id] = placeholder

        container_id: str | None = None
        try:
            await sse_send("built", "Using precompiled Mitchell Lab Julia & Python image.")
            await sse_send("launching", "Allocating isolated container...")

            container_id, host, port = await self.backend.spawn(
                session_id=session_id,
                token=token,
                client_ip_hash=ip_hash,
                config=self.config,
            )
            session = UserSession(
                session_id=session_id,
                token=token,
                container_id=container_id,
                upstream_host=host,
                upstream_port=port,
                client_ip_hash=ip_hash,
            )
            async with self._lock:
                self.sessions[session_id] = session

            ready = await self._wait_until_ready(session, sse_send)
            if not ready:
                await self._destroy_session(session_id, "startup timeout")
                await sse_send(
                    "failed",
                    "Timed out waiting for the tutorial kernel container to start.",
                )
                await response.write_eof()
                return response

            public_url = f"{self._public_base_url(request)}/user/{session_id}/"
            LOG.info(
                "Session %s ready (container %s) -> %s",
                session_id,
                container_id[:12],
                public_url,
            )
            await sse_send(
                "ready",
                "Tutorial kernel ready!",
                url=public_url,
                token=token,
            )
            await response.write_eof()
            return response

        except (asyncio.CancelledError, ConnectionResetError):
            LOG.info("Client disconnected while launching session %s; cleaning up", session_id)
            async with self._lock:
                self.sessions.pop(session_id, None)
            if container_id:
                await self.backend.stop_and_remove(container_id)
            raise
        except Exception as exc:
            LOG.exception("Failed to spawn session %s: %s", session_id, exc)
            async with self._lock:
                self.sessions.pop(session_id, None)
            if container_id:
                await self.backend.stop_and_remove(container_id)
            try:
                await sse_send("failed", f"Server error launching Julia kernel: {exc}")
                await response.write_eof()
            except Exception:
                pass
            return response

    async def handle_binder_launch_page(self, request: web.Request) -> web.Response:
        """Browser-friendly Binder launch URL: GET /v2/{provider}/{spec}."""
        provider = html.escape(request.match_info["provider"])
        spec = html.escape(request.match_info["spec"])
        build_path = f"/build/{provider}/{spec}"
        page = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <title>Launching Julia Tutorial Session…</title>
  <style>
    body {{ font-family: system-ui, -apple-system, sans-serif; max-width: 560px; margin: 4rem auto; padding: 0 1.25rem; color: #0f172a; }}
    .card {{ border: 1px solid #e2e8f0; border-radius: 12px; padding: 1.5rem; background: #f8fafc; }}
    pre {{ background: #0f172a; color: #e2e8f0; padding: 1rem; border-radius: 8px; overflow: auto; font-size: 0.85rem; }}
  </style>
</head>
<body>
  <div class="card">
    <h2>Launching your isolated Julia workspace…</h2>
    <p id="status">Connecting to Mitchell Lab compute server…</p>
    <pre id="log"></pre>
  </div>
  <script>
    const statusEl = document.getElementById('status');
    const logEl = document.getElementById('log');
    const es = new EventSource({json.dumps(build_path)});
    es.onmessage = (evt) => {{
      const msg = JSON.parse(evt.data);
      logEl.textContent += `[${{msg.phase}}] ${{msg.message}}\\n`;
      if (msg.phase === 'ready') {{
        es.close();
        statusEl.textContent = 'Ready! Redirecting to JupyterLab…';
        window.location.href = `${{msg.url}}lab?token=${{encodeURIComponent(msg.token)}}`;
      }} else if (msg.phase === 'failed') {{
        es.close();
        statusEl.textContent = 'Launch failed: ' + msg.message;
      }}
    }};
    es.onerror = () => {{
      es.close();
      statusEl.textContent = 'Connection lost while starting the Julia kernel.';
    }};
  </script>
</body>
</html>"""
        return web.Response(text=page, content_type="text/html")

    async def handle_user_proxy(self, request: web.Request) -> web.StreamResponse:
        """Reverse proxy HTTP and WebSocket traffic to /user/{sid}/..."""
        sid = request.match_info["sid"]
        subpath = request.match_info.get("path", "")

        session = self.sessions.get(sid)
        if session is None or not session.upstream_host:
            return web.json_response(
                {"error": "Session not found or expired. Please reconnect your kernel."},
                status=404,
            )

        session.last_seen = time.monotonic()

        # Check for WebSocket upgrade
        if request.headers.get("Upgrade", "").lower() == "websocket":
            return await self._proxy_websocket(request, session, subpath)
        return await self._proxy_http(request, session, subpath)

    async def _proxy_http(
        self, request: web.Request, session: UserSession, subpath: str
    ) -> web.StreamResponse:
        assert self._http_client is not None
        qs = f"?{request.query_string}" if request.query_string else ""
        target_url = f"{session.upstream_http_base}/user/{session.session_id}/{subpath}{qs}"

        forward_headers = {
            k: v
            for k, v in request.headers.items()
            if k.lower() not in HOP_BY_HOP_HEADERS
        }
        forward_headers["X-Forwarded-Proto"] = request.headers.get(
            "X-Forwarded-Proto", request.scheme
        )
        forward_headers["X-Forwarded-Host"] = request.headers.get(
            "X-Forwarded-Host", request.host
        )

        body = await request.read()
        try:
            async with self._http_client.request(
                method=request.method,
                url=target_url,
                headers=forward_headers,
                data=body if body else None,
                allow_redirects=False,
                auto_decompress=False,
                timeout=ClientTimeout(total=120),
            ) as upstream:
                resp_headers = CIMultiDict(
                    (k, v)
                    for k, v in upstream.headers.items()
                    if k.lower() not in HOP_BY_HOP_HEADERS
                    and not k.lower().startswith("access-control-")
                )
                resp = web.StreamResponse(status=upstream.status, headers=resp_headers)
                self._apply_cors(request, resp)
                await resp.prepare(request)
                async for chunk in upstream.content.iter_chunked(65536):
                    await resp.write(chunk)
                await resp.write_eof()
                session.last_seen = time.monotonic()
                return resp
        except Exception as exc:
            LOG.warning("Upstream HTTP proxy error for session %s: %s", session.session_id, exc)
            return web.json_response(
                {"error": "Upstream Julia server unavailable"},
                status=502,
            )

    async def _proxy_websocket(
        self, request: web.Request, session: UserSession, subpath: str
    ) -> web.WebSocketResponse:
        assert self._http_client is not None
        qs = f"?{request.query_string}" if request.query_string else ""
        target_ws_url = f"{session.upstream_ws_base}/user/{session.session_id}/{subpath}{qs}"

        requested_protocols = [
            p.strip()
            for p in request.headers.get("Sec-WebSocket-Protocol", "").split(",")
            if p.strip()
        ]
        upstream_headers = {}
        for h in ("Authorization", "Cookie", "Origin"):
            if h in request.headers:
                upstream_headers[h] = request.headers[h]

        session.active_ws += 1
        try:
            async with self._http_client.ws_connect(
                target_ws_url,
                protocols=requested_protocols,
                headers=upstream_headers,
                heartbeat=30.0,
                max_msg_size=32 * 1024 * 1024,
            ) as upstream_ws:
                negotiated = (
                    [upstream_ws.protocol] if upstream_ws.protocol else requested_protocols
                )
                client_ws = web.WebSocketResponse(
                    protocols=negotiated,
                    heartbeat=30.0,
                    max_msg_size=32 * 1024 * 1024,
                )
                await client_ws.prepare(request)

                async def client_to_upstream() -> None:
                    async for msg in client_ws:
                        session.last_seen = time.monotonic()
                        if msg.type == WSMsgType.TEXT:
                            await upstream_ws.send_str(msg.data)
                        elif msg.type == WSMsgType.BINARY:
                            await upstream_ws.send_bytes(msg.data)
                        elif msg.type in (WSMsgType.CLOSE, WSMsgType.ERROR):
                            break

                async def upstream_to_client() -> None:
                    async for msg in upstream_ws:
                        session.last_seen = time.monotonic()
                        if msg.type == WSMsgType.TEXT:
                            await client_ws.send_str(msg.data)
                        elif msg.type == WSMsgType.BINARY:
                            await client_ws.send_bytes(msg.data)
                        elif msg.type in (WSMsgType.CLOSE, WSMsgType.ERROR):
                            break

                t1 = asyncio.create_task(client_to_upstream())
                t2 = asyncio.create_task(upstream_to_client())
                done, pending = await asyncio.wait(
                    {t1, t2}, return_when=asyncio.FIRST_COMPLETED
                )
                for task in pending:
                    task.cancel()
                    try:
                        await task
                    except asyncio.CancelledError:
                        pass
                for task in done:
                    task.exception() if not task.cancelled() else None

                if not client_ws.closed:
                    await client_ws.close()
                return client_ws
        finally:
            session.active_ws = max(0, session.active_ws - 1)
            session.last_seen = time.monotonic()

    async def cull_once(self) -> list[str]:
        """Inspect active sessions and stop any that are dead, idle, or past max age."""
        now = time.monotonic()
        to_remove: list[tuple[str, str]] = []

        for sid, session in list(self.sessions.items()):
            if session.container_id == "pending":
                if now - session.created_at > self.config.spawn_timeout_seconds + 15:
                    to_remove.append((sid, "stuck pending spawn"))
                continue

            age = now - session.created_at
            idle = now - session.last_seen

            if age > self.config.max_session_age_seconds:
                to_remove.append((sid, f"max age exceeded ({int(age)}s)"))
                continue

            if idle > self.config.idle_timeout_seconds and session.active_ws == 0:
                to_remove.append((sid, f"idle timeout ({int(idle)}s)"))
                continue

            if not await self.backend.is_running(session.container_id):
                to_remove.append((sid, "container exited"))

        culled: list[str] = []
        for sid, reason in to_remove:
            await self._destroy_session(sid, reason)
            culled.append(sid)
        return culled

    async def _culler_loop(self) -> None:
        while True:
            try:
                await asyncio.sleep(self.config.cull_interval_seconds)
                await self.cull_once()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                LOG.exception("Error in idle culler loop: %s", exc)

    async def on_startup(self, app: web.Application) -> None:
        self._http_client = ClientSession()
        removed = await self.backend.cleanup_orphans()
        if removed:
            LOG.info("Cleaned up %d orphaned tutorial container(s) on startup", removed)
        self._culler_task = asyncio.create_task(self._culler_loop())

    async def on_cleanup(self, app: web.Application) -> None:
        if self._culler_task:
            self._culler_task.cancel()
            try:
                await self._culler_task
            except asyncio.CancelledError:
                pass
        for sid in list(self.sessions.keys()):
            await self._destroy_session(sid, "spawner shutdown")
        if self._http_client:
            await self._http_client.close()


def create_app(
    config: SpawnerConfig | None = None,
    backend: ContainerBackend | None = None,
) -> web.Application:
    cfg = config or SpawnerConfig.from_env()
    be = backend or DockerBackend()
    spawner = TutorialSpawnerApp(cfg, be)

    @web.middleware
    async def security_and_cors_middleware(
        request: web.Request, handler: Any
    ) -> web.StreamResponse:
        # Block user containers from reaching the spawner API
        if spawner._is_from_user_container(request):
            return web.json_response({"error": "Forbidden"}, status=403)

        # Handle CORS preflight immediately
        if request.method == "OPTIONS":
            resp = web.Response(status=204)
            spawner._apply_cors(request, resp)
            return resp

        try:
            resp = await handler(request)
        except web.HTTPException as exc:
            spawner._apply_cors(request, exc)
            raise

        # Avoid touching headers on already-prepared StreamResponses / WebSockets
        if not resp.prepared:
            spawner._apply_cors(request, resp)
        return resp

    app = web.Application(middlewares=[security_and_cors_middleware])
    app["spawner"] = spawner
    app.on_startup.append(spawner.on_startup)
    app.on_cleanup.append(spawner.on_cleanup)

    app.router.add_get("/health", spawner.handle_health)
    app.router.add_get("/build/{provider}/{spec:.*}", spawner.handle_binder_build)
    app.router.add_get("/v2/{provider}/{spec:.*}", spawner.handle_binder_launch_page)
    app.router.add_route("*", "/user/{sid}", spawner.handle_user_proxy)
    app.router.add_route("*", "/user/{sid}/{path:.*}", spawner.handle_user_proxy)

    return app


def main() -> None:
    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    cfg = SpawnerConfig.from_env()
    LOG.info(
        "Starting Mitchell Lab Tutorial Spawner on %s:%d (image=%s, network=%s, max_sessions=%d)",
        cfg.listen_host,
        cfg.listen_port,
        cfg.kernel_image,
        cfg.user_network,
        cfg.max_concurrent_sessions,
    )
    app = create_app(cfg)
    web.run_app(app, host=cfg.listen_host, port=cfg.listen_port, access_log=LOG)


if __name__ == "__main__":
    main()
