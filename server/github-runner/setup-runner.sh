#!/usr/bin/env bash
# One-command installer for the Mitchell Lab self-hosted GitHub Actions runner on 139.184.169.98.
#
# What this does:
#   1. Creates a dedicated non-root user (`gh-runner`) in the `docker` group (NO sudo access).
#   2. Downloads the official GitHub Actions Linux x64 runner into /opt/actions-runner.
#   3. Registers it for SiFTW/interactivetutorials with label `mitchell-server`.
#   4. Installs & starts it as a systemd service (outbound HTTPS only; zero open inbound ports;
#      never touches your existing production JupyterHub).
#   5. Optionally disables the old pull-only `mitchell-tutorials-updater.timer` so GitHub Actions
#      is the single, visible source of truth for building, testing, and deploying.
#
# Usage:
#   1. On GitHub: https://github.com/SiFTW/interactivetutorials/settings/actions/runners/new
#      Copy the temporary registration token (starts with A...).
#   2. On 139.184.169.98, run:
#      sudo bash server/github-runner/setup-runner.sh --token <YOUR_REGISTRATION_TOKEN>

set -euo pipefail

REPO_URL="https://github.com/SiFTW/interactivetutorials"
RUNNER_DIR="/opt/actions-runner"
RUNNER_USER="gh-runner"
RUNNER_NAME="mitchell-tutorial-server"
RUNNER_LABELS="mitchell-server"
RUNNER_TOKEN=""
KEEP_OLD_TIMER=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --token)
      RUNNER_TOKEN="${2:-}"
      shift 2
      ;;
    --name)
      RUNNER_NAME="${2:-}"
      shift 2
      ;;
    --dir)
      RUNNER_DIR="${2:-}"
      shift 2
      ;;
    --user)
      RUNNER_USER="${2:-}"
      shift 2
      ;;
    --keep-old-timer)
      KEEP_OLD_TIMER=1
      shift
      ;;
    -h|--help)
      sed -n '2,20p' "$0"
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      exit 2
      ;;
  esac
done

if [[ "${EUID}" -ne 0 ]]; then
  echo "Please run with sudo: sudo bash $0 --token <GITHUB_RUNNER_TOKEN>" >&2
  exit 1
fi

if [[ -z "${RUNNER_TOKEN}" ]]; then
  echo "Missing --token. Get a registration token from:" >&2
  echo "  ${REPO_URL}/settings/actions/runners/new" >&2
  exit 2
fi

if ! command -v docker >/dev/null 2>&1; then
  echo "Docker is not installed or not on PATH." >&2
  exit 1
fi

# 1. Create dedicated non-root runner user with Docker access only (no sudo)
if ! id -u "${RUNNER_USER}" >/dev/null 2>&1; then
  useradd --system --create-home --shell /bin/bash "${RUNNER_USER}"
  echo "Created user '${RUNNER_USER}'."
fi
usermod -aG docker "${RUNNER_USER}"

# 2. Fetch latest official actions/runner release for linux-x64
LATEST_TAG="$(curl -fsSL https://api.github.com/repos/actions/runner/releases/latest | python3 -c 'import sys,json; print(json.load(sys.stdin)["tag_name"])')"
VERSION="${LATEST_TAG#v}"
TARBALL="actions-runner-linux-x64-${VERSION}.tar.gz"
DOWNLOAD_URL="https://github.com/actions/runner/releases/download/${LATEST_TAG}/${TARBALL}"

mkdir -p "${RUNNER_DIR}"
chown -R "${RUNNER_USER}:${RUNNER_USER}" "${RUNNER_DIR}"

if [[ ! -x "${RUNNER_DIR}/config.sh" ]]; then
  echo "Downloading GitHub Actions Runner ${LATEST_TAG}..."
  curl -fsSL "${DOWNLOAD_URL}" -o "/tmp/${TARBALL}"
  tar -xzf "/tmp/${TARBALL}" -C "${RUNNER_DIR}"
  rm -f "/tmp/${TARBALL}"
  chown -R "${RUNNER_USER}:${RUNNER_USER}" "${RUNNER_DIR}"
fi

# 3. Configure runner non-interactively as RUNNER_USER
su - "${RUNNER_USER}" -c "cd '${RUNNER_DIR}' && ./config.sh \
  --unattended \
  --replace \
  --url '${REPO_URL}' \
  --token '${RUNNER_TOKEN}' \
  --name '${RUNNER_NAME}' \
  --labels '${RUNNER_LABELS}' \
  --work _work"

# 4. Install and start systemd service
(
  cd "${RUNNER_DIR}"
  ./svc.sh uninstall >/dev/null 2>&1 || true
  ./svc.sh install "${RUNNER_USER}"
  ./svc.sh start
  ./svc.sh status
)

# 5. Disable legacy blind systemd polling timer unless --keep-old-timer was passed
if [[ "${KEEP_OLD_TIMER}" -eq 0 ]] && systemctl list-unit-files | grep -q '^mitchell-tutorials-updater\.timer'; then
  echo "Disabling legacy mitchell-tutorials-updater.timer (replaced by GitHub Actions runner)..."
  systemctl disable --now mitchell-tutorials-updater.timer || true
fi

echo ""
echo "============================================================================"
echo "Self-hosted runner '${RUNNER_NAME}' (label: ${RUNNER_LABELS}) is LIVE!"
echo ""
echo "Recommended GitHub security check (public repository):"
echo "  ${REPO_URL}/settings/actions"
echo "  -> Fork pull request workflows from outside collaborators:"
echo "     Select 'Require approval for all outside collaborators'"
echo ""
echo "Every trusted PR now builds & tests ALL Julia and Python notebooks inside"
echo "the exact production Docker image on this server, and merging to main"
echo "promotes :latest + runs the live spawner smoke test automatically!"
echo "============================================================================"
