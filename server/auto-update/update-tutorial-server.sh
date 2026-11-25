#!/usr/bin/env bash
# Pull-only auto-updater with pre-promote notebook verification for 139.184.169.98.
#
# Safety guarantees:
# - Zero credentials leave the server (read-only `git fetch` from public GitHub repo).
# - Uses an exclusive file lock so overlapping timer ticks never run concurrent builds.
# - Refuses to overwrite local uncommitted changes (uses `git merge --ff-only`).
# - Rebuilds ONLY what changed and verifies BEFORE promoting:
#     * tutorials/ or Julia kernel files -> builds `:candidate`, runs EVERY cell of
#       EVERY notebook inside a 2 GB RAM `--network=none` container, and ONLY promotes
#       to `:latest` if all notebooks pass with zero errors!
#     * server/spawner/ or docker-compose.yml -> rebuilds & restarts only
#       `mitchell-tutorial-spawner` and checks `http://127.0.0.1:8787/health`.
#     * book/*.ipynb or ssc/*.ipynb -> runs post-pull notebook verification against
#       the deployed kernel image and logs pass/fail in journalctl.
# - Strictly scoped to `mitchell-lab/julia-tutorial-kernel` and the
#   `mitchell-tutorials` Docker Compose project; never touches JupyterHub.
#
# Usage:
#   ./update-tutorial-server.sh                # normal pull + selective rebuild & test
#   ./update-tutorial-server.sh --dry-run      # print what would run without docker changes
#   ./update-tutorial-server.sh --force-kernel # force a cached kernel rebuild + test now
#   ./update-tutorial-server.sh --test-only    # test all notebooks against current :latest image
#   ./update-tutorial-server.sh --skip-tests   # skip container notebook test gate (emergency)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="${REPO_DIR:-$(cd "${SCRIPT_DIR}/../.." && pwd)}"
BRANCH="${UPDATE_BRANCH:-main}"
KERNEL_IMAGE="${KERNEL_IMAGE:-mitchell-lab/julia-tutorial-kernel:latest}"
CANDIDATE_IMAGE="${KERNEL_IMAGE%:*}:candidate"
LOCK_FILE="${LOCK_FILE:-/run/lock/mitchell-tutorials-updater.lock}"

DRY_RUN=0
FORCE_KERNEL=0
TEST_ONLY=0
SKIP_TESTS=0

for arg in "$@"; do
  case "$arg" in
    --dry-run) DRY_RUN=1 ;;
    --force-kernel) FORCE_KERNEL=1 ;;
    --test-only) TEST_ONLY=1 ;;
    --skip-tests) SKIP_TESTS=1 ;;
    -h|--help)
      sed -n '2,25p' "$0"
      exit 0
      ;;
    *)
      echo "[updater] Unknown argument: $arg" >&2
      exit 2
      ;;
  esac
done

log() {
  printf '[updater %s] %s\n' "$(date -u +'%Y-%m-%dT%H:%M:%SZ')" "$*"
}

run_notebook_suite() {
  local image="$1"
  log "Running end-to-end Julia & Python notebook test suite inside ${image} (2g RAM, --network=none)..."
  if [[ "$DRY_RUN" -eq 1 ]]; then
    log "[dry-run] Would run: docker run --rm --memory=2g --cpus=2 --pids-limit=256 --network=none -e GKSwstype=100 -e MPLBACKEND=Agg -e OPENMM_CPU_THREADS=1 -v ${REPO_DIR}:/repo:ro ${image} python3 /repo/scripts/test_notebooks.py --repo /repo --julia-args \"--sysimage=/opt/julia-env/tutorial_sysimage.so --project=/opt/julia-env\" --in-container-work /home/jovyan/work"
    return 0
  fi

  local julia_args="--project=/opt/julia-env"
  if docker run --rm --network=none "$image" test -f /opt/julia-env/tutorial_sysimage.so 2>/dev/null; then
    julia_args="--sysimage=/opt/julia-env/tutorial_sysimage.so --project=/opt/julia-env"
  fi

  docker run --rm \
    --memory=2g --cpus=2 --pids-limit=256 \
    --network=none \
    -e GKSwstype=100 \
    -e MPLBACKEND=Agg \
    -e OPENMM_CPU_THREADS=1 \
    -v "${REPO_DIR}:/repo:ro" \
    "$image" \
    python3 /repo/scripts/test_notebooks.py \
      --repo /repo \
      --via-jupyter \
      --julia-args="$julia_args" \
      --in-container-work /home/jovyan/work
}

# Acquire exclusive non-blocking lock (fall back to /tmp if /run/lock isn't writable)
if ! mkdir -p "$(dirname "$LOCK_FILE")" 2>/dev/null || ! touch "$LOCK_FILE" 2>/dev/null; then
  LOCK_FILE="/tmp/mitchell-tutorials-updater.lock"
fi
exec 9>"$LOCK_FILE"
if ! flock -n 9; then
  log "Another update is already running; skipping this tick."
  exit 0
fi

cd "$REPO_DIR"

# Avoid Git's "dubious ownership" error when systemd runs as root on a user-owned clone
if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  git config --global --add safe.directory "$REPO_DIR"
fi

if [[ "$TEST_ONLY" -eq 1 ]]; then
  run_notebook_suite "$KERNEL_IMAGE"
  log "All notebooks passed against ${KERNEL_IMAGE}!"
  exit 0
fi

CURRENT_BRANCH="$(git rev-parse --abbrev-ref HEAD)"
if [[ "$CURRENT_BRANCH" != "$BRANCH" ]]; then
  log "Repo is on branch '$CURRENT_BRANCH' (expected '$BRANCH'); skipping auto-update."
  exit 0
fi

if [[ -n "$(git status --porcelain --untracked-files=no)" ]]; then
  log "Working tree has local tracked modifications; skipping auto-update to avoid overwriting your work."
  exit 0
fi

git fetch --quiet origin "$BRANCH"
OLD_SHA="$(git rev-parse HEAD)"
NEW_SHA="$(git rev-parse FETCH_HEAD)"

NEED_KERNEL_BUILD=$FORCE_KERNEL
NEED_SPAWNER_BUILD=0
NEED_NOTEBOOK_VERIFY=0

if [[ "$OLD_SHA" == "$NEW_SHA" ]]; then
  if [[ "$FORCE_KERNEL" -eq 0 ]]; then
    exit 0
  fi
  log "Already at ${OLD_SHA:0:7}, proceeding due to --force-kernel."
else
  CHANGED_FILES="$(git diff --name-only "$OLD_SHA" "$NEW_SHA")"
  log "New commit(s) detected on origin/${BRANCH}: ${OLD_SHA:0:7} -> ${NEW_SHA:0:7}"

  if [[ "$DRY_RUN" -eq 1 ]]; then
    log "[dry-run] Would fast-forward HEAD to ${NEW_SHA:0:7}"
  else
    git merge --ff-only --quiet "$NEW_SHA"
  fi

  if grep -qE '^(tutorials/|server/Dockerfile\.julia-kernel$|server/Project\.toml$|server/precompile_workload\.jl$|server/write_kernelspec\.py$)' <<<"$CHANGED_FILES"; then
    NEED_KERNEL_BUILD=1
  fi

  if grep -qE '^(server/spawner/|server/docker-compose\.yml$)' <<<"$CHANGED_FILES"; then
    NEED_SPAWNER_BUILD=1
  fi

  if grep -qE '^((book|ssc)/.*\.ipynb|scripts/test_notebooks\.py)$' <<<"$CHANGED_FILES"; then
    NEED_NOTEBOOK_VERIFY=1
  fi

  if [[ "$NEED_KERNEL_BUILD" -eq 0 && "$NEED_SPAWNER_BUILD" -eq 0 && "$NEED_NOTEBOOK_VERIFY" -eq 0 ]]; then
    log "Only docs/markdown/CI files changed — no Docker rebuild needed."
    exit 0
  fi
fi

if [[ "$NEED_KERNEL_BUILD" -eq 1 ]]; then
  log "Building candidate kernel image ${CANDIDATE_IMAGE}..."
  if [[ "$DRY_RUN" -eq 1 ]]; then
    log "[dry-run] Would run: docker build -f server/Dockerfile.julia-kernel -t ${CANDIDATE_IMAGE} ."
  else
    docker build --build-arg GIT_SHA="$(git rev-parse HEAD)" -f server/Dockerfile.julia-kernel -t "$CANDIDATE_IMAGE" .
  fi

  if [[ "$SKIP_TESTS" -eq 0 ]]; then
    if ! run_notebook_suite "$CANDIDATE_IMAGE"; then
      log "ERROR: Notebook verification FAILED for ${CANDIDATE_IMAGE}! Keeping existing ${KERNEL_IMAGE} untouched."
      if [[ "$DRY_RUN" -eq 0 ]]; then
        docker rmi "$CANDIDATE_IMAGE" >/dev/null 2>&1 || true
      fi
      exit 1
    fi
  else
    log "Skipping notebook test gate (--skip-tests)."
  fi

  if [[ "$DRY_RUN" -eq 1 ]]; then
    log "[dry-run] Would promote ${CANDIDATE_IMAGE} -> ${KERNEL_IMAGE}"
  else
    docker tag "$CANDIDATE_IMAGE" "$KERNEL_IMAGE"
    docker rmi "$CANDIDATE_IMAGE" >/dev/null 2>&1 || true
    log "Promoted verified kernel image to ${KERNEL_IMAGE}!"
  fi
  # Candidate build already ran the full notebook test suite
  NEED_NOTEBOOK_VERIFY=0
fi

if [[ "$NEED_SPAWNER_BUILD" -eq 1 ]]; then
  log "Rebuilding and restarting mitchell-tutorial-spawner..."
  if [[ "$DRY_RUN" -eq 1 ]]; then
    log "[dry-run] Would run: (cd server && docker compose up -d --build spawner)"
  else
    (
      cd "${REPO_DIR}/server"
      if docker ps --format '{{.Names}}' | grep -qx 'mitchell-tutorial-cloudflared'; then
        docker compose --profile tunnel up -d --build spawner
      else
        docker compose up -d --build spawner
      fi
    )
    # Wait briefly and verify local /health endpoint
    healthy=0
    for _ in 1 2 3 4 5 6; do
      if curl -fsS http://127.0.0.1:8787/health >/dev/null 2>&1; then
        healthy=1
        break
      fi
      sleep 2
    done
    if [[ "$healthy" -eq 1 ]]; then
      log "Spawner updated and healthy at http://127.0.0.1:8787/health."
    else
      log "WARNING: Spawner restarted but /health did not respond within 12s; check docker compose logs."
      exit 1
    fi
  fi
fi

if [[ "$NEED_NOTEBOOK_VERIFY" -eq 1 && "$SKIP_TESTS" -eq 0 ]]; then
  log "Notebook file(s) changed — verifying all notebooks run cleanly on ${KERNEL_IMAGE}..."
  run_notebook_suite "$KERNEL_IMAGE"
  log "Post-deploy notebook verification passed!"
fi
