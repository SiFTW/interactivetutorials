# Deploying the Isolated Julia Kernel Spawner on `139.184.169.98`

This deployment runs **100% independently** of your existing production JupyterHub (`https://jeanlucpacard.mitchell.science`). You do **not** need to find, edit, or restart your existing JupyterHub configuration or containers.

## Safety guarantees for `139.184.169.98`

| Concern | How this stack isolates it |
|---|---|
| Existing JupyterHub config & containers | Never touched. Uses its own Docker Compose project (`mitchell-tutorials`) and container prefix (`tutorial-julia-*`). |
| Host network ports | Spawner binds **only** to `127.0.0.1:8787` (does not conflict with ports `8000`, `8080`, `8081`, `8111`, or `443`). |
| Compute starvation of research jobs | Hard caps via Docker cgroups: `2g` RAM, `2.0` CPUs, `256` PIDs per user container, `MAX_CONCURRENT_SESSIONS=20`, `MAX_SESSIONS_PER_IP=30` (supports a classroom sharing campus NAT). |
| Network abuse / SSRF / cryptominers | Ephemeral user containers attach **only** to `mitchell-tutorials_user_net` (`internal: true`) — **zero outbound internet or campus LAN egress**. |
| User filesystem isolation | Each visitor gets their own disposable container (`--cap-drop=ALL`, `no-new-privileges`, `auto_remove=True`), automatically culled after 20 minutes idle or 2 hours max lifetime. |

---

## Step 1: Clone this repository on `139.184.169.98`

SSH into `139.184.169.98` and place the repository in a clean directory (for example `/opt/interactivetutorials` or `~/interactivetutorials`):

```bash
git clone https://github.com/SiFTW/interactivetutorials.git
cd interactivetutorials
```

## Step 2: Build the precompiled Julia kernel Docker image

Build the image from the **repository root** (so it can copy `tutorials/toyModel/` and `server/Project.toml`):

```bash
docker build \
  -f server/Dockerfile.julia-kernel \
  -t mitchell-lab/julia-tutorial-kernel:latest \
  .
```

> **Tip on build time vs. student startup speed:**
> - With the default `BUILD_SYSIMAGE=1`, the first build takes ~8–12 minutes (using `PackageCompiler.jl`), and in return every student's `using DifferentialEquations, Plots` + first plot runs in **~1–2 seconds**.
> - If you want a quick test build first (~3 minutes), pass `--build-arg BUILD_SYSIMAGE=0` (standard Julia precompilation; first plot takes ~8–15 seconds).

## Step 3: Configure `server/.env`

```bash
cp server/.env.example server/.env
```

Review `server/.env` and adjust resource caps if desired (`MAX_CONCURRENT_SESSIONS`, `CONTAINER_MEM_LIMIT`, `CONTAINER_CPUS`). The defaults are already configured for:
- `PUBLIC_BASE_URL=https://kernels.mitchell.science`
- `ALLOWED_ORIGINS=https://mitchell.science,https://www.mitchell.science,http://localhost:3000,http://127.0.0.1:3000`

## Step 4: Expose `kernels.mitchell.science` via Cloudflare Tunnel

Choose **whichever** option is easier for your setup — both leave `jeanlucpacard.mitchell.science` completely untouched!

### Option A (Zero host edits — Recommended): Run a dedicated `cloudflared` container in this stack

1. In the **Cloudflare Zero Trust Dashboard**, go to **Networks → Tunnels → Create a tunnel** (Cloudflared).
2. Name it e.g. `mitchell-tutorials-kernels` and copy the **Tunnel Token**.
3. Under **Public Hostname**, add:
   - **Subdomain**: `kernels`
   - **Domain**: `mitchell.science`
   - **Service Type**: `HTTP`
   - **URL**: `spawner:8787`
4. Paste the token into `CLOUDFLARE_TUNNEL_TOKEN=...` inside `server/.env`.
5. Start both the spawner and its dedicated tunnel container:

```bash
cd server
docker compose --profile tunnel up -d --build
```

### Option B: Add a second Public Hostname to your existing Cloudflare Tunnel

If you already manage your tunnel for `jeanlucpacard.mitchell.science` in the Cloudflare Zero Trust Dashboard:

1. Open your existing tunnel in **Cloudflare Zero Trust → Networks → Tunnels → Configure → Public Hostname**.
2. Add a new public hostname (without editing `jeanlucpacard.mitchell.science`):
   - **Subdomain**: `kernels`
   - **Domain**: `mitchell.science`
   - **Service Type**: `HTTP`
   - **URL**: `http://127.0.0.1:8787`
3. Start just the spawner container:

```bash
cd server
docker compose up -d --build
```

> **Note on WebSockets:** Cloudflare Tunnels automatically support `wss://` WebSockets (required by Jupyter kernels) — just make sure **WebSockets** is enabled in your Cloudflare dashboard under `mitchell.science` → **Network → WebSockets** (it is ON by default).

---

## Step 5: Verify end-to-end

1. **Check local health on `139.184.169.98`:**
   ```bash
   curl -s http://127.0.0.1:8787/health | jq
   ```
2. **Check public HTTPS health through Cloudflare:**
   ```bash
   curl -s https://kernels.mitchell.science/health | jq
   ```
   Expected output:
   ```json
   {
     "status": "ok",
     "active_sessions": 0,
     "max_sessions": 20,
     "kernel_image": "mitchell-lab/julia-tutorial-kernel:latest",
     "uptime_seconds": 12.4
   }
   ```
3. **Test spawning an isolated Julia session via the Binder SSE endpoint:**
   ```bash
   curl -N -H "Origin: https://mitchell.science" \
     https://kernels.mitchell.science/build/gh/SiFTW/interactivetutorials/main
   ```
   You should see SSE events ending with:
   ```text
   data: {"phase": "ready", "message": "Julia kernel ready!", "url": "https://kernels.mitchell.science/user/<id>/", "token": "<token>"}
   ```
4. **Confirm your existing JupyterHub was never touched:**
   Open `https://jeanlucpacard.mitchell.science` and check `docker ps` — you will only see the new `mitchell-tutorial-spawner` (and any short-lived `tutorial-julia-*` containers) alongside your untouched research containers.

## Day-to-day operations

- **View logs:** `cd server && docker compose logs -f spawner`
- **Update tutorial starter files or Julia packages:**
  ```bash
  git pull
  docker build -f server/Dockerfile.julia-kernel -t mitchell-lab/julia-tutorial-kernel:latest .
  cd server && docker compose up -d --build
  ```
- **Emergency stop (cleans up all tutorial containers automatically):**
  ```bash
  cd server && docker compose --profile tunnel down
  ```

---

## Optional: Automatic Pull-Only Rebuilds (`systemd` Timer)

Instead of manually SSHing in to run `git pull && docker build` after merging PRs, you can install a lightweight pull-only `systemd` timer on `139.184.169.98`:

- Polls `origin/main` every **2 minutes** (read-only HTTPS fetch — zero SSH keys or tokens leave the server).
- Uses an exclusive file lock (`flock`) and low CPU/IO priority (`Nice=10`) so builds never overlap or impact research jobs.
- **Selectively rebuilds only what changed and verifies BEFORE promoting:**
  - `tutorials/` or kernel files (`Dockerfile.julia-kernel`, `Project.toml`, `precompile_workload.jl`, `write_kernelspec.py`) → builds `:candidate`, executes **every code cell of every notebook** in `book/` and `ssc/` inside a `2g` RAM `--network=none` container, and **only promotes to `:latest` if all notebooks pass with zero errors**!
  - `server/spawner/` or `server/docker-compose.yml` → rebuilds & restarts only `mitchell-tutorial-spawner` and checks `http://127.0.0.1:8787/health`.
  - Notebook changes (`book/*.ipynb`, `ssc/*.ipynb`) → verifies all notebooks run cleanly on the deployed kernel image.
  - Markdown/doc/CI changes → pulls fast-forward and skips Docker completely.
- Never touches `jeanlucpacard.mitchell.science` or any local uncommitted files.

### Install once (on `139.184.169.98`)

```bash
cd /home/interactivetutorials && git pull && sudo bash server/auto-update/install-systemd-timer.sh
```

### Check status, view logs, test deployed image, or uninstall

```bash
# Check timer schedule
systemctl list-timers mitchell-tutorials-updater.timer

# View updater logs
journalctl -u mitchell-tutorials-updater.service -n 50 --no-pager

# Run all 13 interactive notebooks against the currently deployed kernel image
sudo bash /home/interactivetutorials/server/auto-update/update-tutorial-server.sh --test-only

# Trigger a manual check (or dry-run) immediately
sudo bash /home/interactivetutorials/server/auto-update/update-tutorial-server.sh --dry-run
sudo systemctl start mitchell-tutorials-updater.service

# Turn off & remove the timer cleanly
sudo bash /home/interactivetutorials/server/auto-update/uninstall-systemd-timer.sh
```

