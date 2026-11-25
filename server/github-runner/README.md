# Self-Hosted GitHub Actions Runner (`139.184.169.98`)

Running notebook tests and Docker image promotions on a **self-hosted GitHub Actions runner** directly on `139.184.169.98` eliminates the gap between CI and what students experience live:

- **True user environment:** Executes **every cell of every Julia and Python notebook** via real Jupyter kernels (`--via-jupyter` using `nbclient`) inside the **exact production Docker image** (`--memory=2g --cpus=2 --pids-limit=256 --network=none`).
- **Fast (~2 min instead of 22 min):** Reuses the server's warm local Docker layer cache (the Julia `PackageCompiler` sysimage stays cached!).
- **Zero silent drift:** When a PR merges to `main`, GitHub Actions immediately promotes that already-tested image to `:latest`, restarts `mitchell-tutorial-spawner`, and runs [`scripts/smoke_test_spawner.py`](../../scripts/smoke_test_spawner.py) against `http://127.0.0.1:8787` verifying `/health` reports the exact `kernel_git_sha`, both `julia` and `python3` kernelspecs exist, and all workspace folders (`MD`, `NFkB`, `apoptosis`, `cellCycle`) are live.
- **Zero open ports / zero JupyterHub impact:** Connects outbound over HTTPS only; runs under a dedicated non-root `gh-runner` user in the `docker` group with no `sudo`.

## One-Time Setup (~3 Minutes)

1. Open GitHub runner registration:
   `https://github.com/SiFTW/interactivetutorials/settings/actions/runners/new`
   Copy the short-lived registration token (`--token A...`).

2. SSH into `139.184.169.98`, pull `main`, and run:
   ```bash
   sudo bash /path/to/interactivetutorials/server/github-runner/setup-runner.sh --token <YOUR_TOKEN>
   ```

3. Verify the runner appears **Idle (green)** at:
   `https://github.com/SiFTW/interactivetutorials/settings/actions/runners`

4. **Public repo safety check:** Under
   `https://github.com/SiFTW/interactivetutorials/settings/actions`
   ensure **Fork pull request workflows from outside collaborators** is set to **"Require approval for all outside collaborators"**.
   *(In addition, `.github/workflows/server-test-and-deploy.yml` explicitly restricts execution to `main`, `workflow_dispatch`, and same-repo PRs from `OWNER`/`MEMBER`/`COLLABORATOR`.)*

5. Trigger your first true-environment build & deploy immediately from GitHub:
   `Actions -> Server True-Environment Test & Deploy -> Run workflow (main)`
   (or simply merge any PR!).
