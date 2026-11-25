#!/usr/bin/env python3
"""Live end-to-end smoke test against the running Mitchell Lab tutorial spawner.

Verifies the TRUE user path against `http://127.0.0.1:8787` (or `https://kernels.mitchell.science`):
  1. GET /health returns status=ok and (optionally) matches `--expect-sha`.
  2. GET /build/gh/SiFTW/interactivetutorials/main spawns a real ephemeral container via SSE.
  3. GET /user/{sid}/api/kernelspecs confirms BOTH `julia` and `python3` kernels exist.
  4. GET /user/{sid}/api/contents/{MD,NFkB,apoptosis,cellCycle} confirms all workspaces exist.

Uses only the Python 3 standard library.
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.parse
import urllib.request


def _get_json(url: str, timeout: int = 15) -> dict:
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        if resp.status != 200:
            raise RuntimeError(f"GET {url} returned HTTP {resp.status}")
        return json.loads(resp.read().decode("utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser(description="Live end-to-end smoke test for the tutorial spawner.")
    parser.add_argument("--url", default="http://127.0.0.1:8787", help="Base URL of spawner")
    parser.add_argument("--expect-sha", default="", help="Optional git SHA prefix expected in /health kernel_git_sha")
    parser.add_argument("--timeout", type=int, default=60, help="SSE spawn timeout in seconds")
    args = parser.parse_args()

    base = args.url.rstrip("/")

    # 1. Health check
    health = _get_json(f"{base}/health", timeout=10)
    print("Health:", json.dumps(health))
    if health.get("status") != "ok":
        print("FAIL: /health status is not 'ok'", file=sys.stderr)
        return 1
    if args.expect_sha:
        live_sha = str(health.get("kernel_git_sha", ""))
        if not live_sha.startswith(args.expect_sha[:7]):
            print(
                f"FAIL: /health kernel_git_sha={live_sha!r} does not match expected {args.expect_sha!r}",
                file=sys.stderr,
            )
            return 1

    # 2. Spawn a real ephemeral container via BinderHub SSE
    build_url = f"{base}/build/gh/SiFTW/interactivetutorials/main"
    print(f"Spawning live session via {build_url} ...")
    ready_payload: dict | None = None
    req = urllib.request.Request(build_url, headers={"Accept": "text/event-stream"})
    with urllib.request.urlopen(req, timeout=args.timeout) as resp:
        for raw_line in resp:
            line = raw_line.decode("utf-8", errors="replace").strip()
            if not line.startswith("data:"):
                continue
            event = json.loads(line[len("data:") :].strip())
            phase = event.get("phase")
            print(f"  [{phase}] {event.get('message', '')}")
            if phase == "failed":
                print(f"FAIL: Binder spawn failed: {event.get('message')}", file=sys.stderr)
                return 1
            if phase == "ready":
                ready_payload = event
                break

    if not ready_payload or not ready_payload.get("url") or not ready_payload.get("token"):
        print("FAIL: Did not receive 'ready' event with url + token", file=sys.stderr)
        return 1

    # Rewrite returned public URL to the requested base URL (so localhost smoke tests stay local)
    parsed_ready = urllib.parse.urlparse(ready_payload["url"])
    user_base = f"{base}{parsed_ready.path.rstrip('/')}"
    token = urllib.parse.quote(ready_payload["token"], safe="")

    # 3. Verify BOTH julia and python3 kernelspecs exist in the live container
    ks = _get_json(f"{user_base}/api/kernelspecs?token={token}")
    specs = sorted((ks.get("kernelspecs") or {}).keys())
    print("Live kernelspecs:", specs)
    for required in ("julia", "python3"):
        if required not in specs:
            print(f"FAIL: Required kernelspec {required!r} missing from live container ({specs})", file=sys.stderr)
            return 1

    # 4. Verify all tutorial workspace directories exist in /home/jovyan/work
    for folder in ("MD", "NFkB", "apoptosis", "cellCycle"):
        try:
            _get_json(f"{user_base}/api/contents/{folder}?content=0&token={token}")
            print(f"  [OK] /home/jovyan/work/{folder}/ present")
        except urllib.error.HTTPError as exc:
            print(f"FAIL: Missing workspace folder /home/jovyan/work/{folder}/ (HTTP {exc.code})", file=sys.stderr)
            return 1

    # 5. Verify /admin dashboard serves cleanly
    with urllib.request.urlopen(f"{base}/admin", timeout=10) as resp:
        if resp.status != 200:
            print(f"FAIL: GET /admin returned HTTP {resp.status}", file=sys.stderr)
            return 1
        body = resp.read().decode("utf-8", errors="replace")
        if "Mitchell Lab Tutorial Server" not in body:
            print("FAIL: GET /admin did not return expected dashboard HTML", file=sys.stderr)
            return 1
        print("  [OK] /admin dashboard reachable")

    print("LIVE SPAWNER SMOKE TEST PASSED!")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
