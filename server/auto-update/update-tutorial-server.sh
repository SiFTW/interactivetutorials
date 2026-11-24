#!/usr/bin/env bash
# Pull-only auto-updater for Mitchell Lab interactive tutorials on 139.184.169.98.
#
# Safety guarantees:
# - Zero credentials leave the server (read-only `git fetch` from public GitHub repo).
# - Uses an exclusive file lock so overlapping timer ticks never run concurrent builds.
# - Refuses to overwrite local uncommitted changes (uses `git merge --ff-only`).
# - Rebuilds ONLY what changed:
#     * tutorials/ or Julia kernel files -> `docker build` kernel image (~5s cached)
#     * server/spawner/ or docker-compose.yml -> `docker compose up -d --build spawner`
#     * book/, ssc/, docs -> skips Docker completely (Netlify handles those)
# - Strictly scoped to `mitchell-lab/julia-tutorial-kernel:latest` and the
#   `mitchell-tutorials` Docker Compose project; never touches JupyterHub.
#
# Usage:
#   ./update-tutorial-server.sh               # normal pull + selective rebuild
#   ./update-tutorial-server.sh --dry-run     # print what would run without docker changes
#   ./update-tutorial-server.sh --force-kernel # force a cached kernel image rebuild now

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="${REPO_DIR:-$(cd "${SCRIPT_DIR}/../.." && pwd)}"
BRANCH="${UPDATE_BRANCH:-main}"
KERNEL_IMAGE="${KERNEL_IMAGE:-mitchell-lab/julia-tutorial-kernel:latest}"
LOCK_FILE="${LOCK_FILE:-/run/lock/mitchell-tutorials-updater.lock}"

DRY_RUN=0
FORCE_KERNEL=0

for arg in "$@"; do
  case "$arg" in
    --dry-run) DRY_RUN=1 ;;
    --force-kernel) FORCE_KERNEL=1 ;;
    -h|--help)
      sed -n '2,20p' "$0"
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

  if [[ "$NEED_KERNEL_BUILD" -eq 0 && "$NEED_SPAWNER_BUILD" -eq 0 ]]; then
    log "Only book/docs/CI files changed — no Docker rebuild needed."
    exit 0
  fi
fi

if [[ "$NEED_KERNEL_BUILD" -eq 1 ]]; then
  log "Rebuilding kernel image ${KERNEL_IMAGE}..."
  if [[ "$DRY_RUN" -eq 1 ]]; then
    log "[dry-run] Would run: docker build -f server/Dockerfile.julia-kernel -t ${KERNEL_IMAGE} ."
  else
    docker build -f server/Dockerfile.julia-kernel -t "$KERNEL_IMAGE" .
    log "Kernel image ${KERNEL_IMAGE} rebuilt successfully."
  fi
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
    log "Spawner updated successfully."
  fi
fi
