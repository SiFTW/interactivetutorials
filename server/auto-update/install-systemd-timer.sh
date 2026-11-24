#!/usr/bin/env bash
# Installs a lightweight systemd timer on 139.184.169.98 to poll GitHub every 2 minutes
# and rebuild the Julia tutorial kernel / spawner only when tutorials/ or server/ change.
#
# Run once with sudo from anywhere:
#   sudo bash /home/interactivetutorials/server/auto-update/install-systemd-timer.sh

set -euo pipefail

if [[ "${EUID}" -ne 0 ]]; then
  echo "Please run with sudo: sudo bash $0" >&2
  exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "${SCRIPT_DIR}/../.." && pwd)"
UPDATER_SCRIPT="${SCRIPT_DIR}/update-tutorial-server.sh"
INTERVAL="${UPDATE_INTERVAL:-2min}"

chmod +x "${UPDATER_SCRIPT}" "${SCRIPT_DIR}/install-systemd-timer.sh" "${SCRIPT_DIR}/uninstall-systemd-timer.sh"

cat >/etc/systemd/system/mitchell-tutorials-updater.service <<EOF
[Unit]
Description=Pull-only auto-updater for Mitchell Lab interactive Julia tutorials
After=network-online.target docker.service
Wants=network-online.target
Requires=docker.service

[Service]
Type=oneshot
Environment=REPO_DIR=${REPO_DIR}
ExecStart=${UPDATER_SCRIPT}
Nice=10
IOSchedulingClass=best-effort
IOSchedulingPriority=7
EOF

cat >/etc/systemd/system/mitchell-tutorials-updater.timer <<EOF
[Unit]
Description=Check GitHub every ${INTERVAL} for Mitchell Lab tutorial model/server updates

[Timer]
OnBootSec=1min
OnUnitActiveSec=${INTERVAL}
RandomizedDelaySec=15s
Persistent=false

[Install]
WantedBy=timers.target
EOF

systemctl daemon-reload
systemctl enable --now mitchell-tutorials-updater.timer

echo ""
echo "Installed and started mitchell-tutorials-updater.timer (checking every ${INTERVAL})."
echo "Repository directory: ${REPO_DIR}"
echo ""
echo "Useful commands:"
echo "  Check timer status:  systemctl list-timers mitchell-tutorials-updater.timer"
echo "  View update logs:    journalctl -u mitchell-tutorials-updater.service -n 50 --no-pager"
echo "  Trigger a check now: sudo systemctl start mitchell-tutorials-updater.service"
echo "  Uninstall later:     sudo bash ${SCRIPT_DIR}/uninstall-systemd-timer.sh"
