#!/usr/bin/env bash
# Cleanly stops and removes the Mitchell Lab tutorial pull-only systemd updater.

set -euo pipefail

if [[ "${EUID}" -ne 0 ]]; then
  echo "Please run with sudo: sudo bash $0" >&2
  exit 1
fi

systemctl disable --now mitchell-tutorials-updater.timer 2>/dev/null || true
rm -f /etc/systemd/system/mitchell-tutorials-updater.timer \
      /etc/systemd/system/mitchell-tutorials-updater.service
systemctl daemon-reload

echo "Removed mitchell-tutorials-updater timer and service."
