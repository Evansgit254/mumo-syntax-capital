#!/bin/bash

# Update installed systemd units to use the project virtualenv interpreter.
# Intended as a one-time recovery script for the VM deployment path.

set -euo pipefail

PROJECT_DIR="${1:-/home/evans/mumo-syntax-capital}"
SYSTEMD_DIR="${2:-/etc/systemd/system}"
VENV_PYTHON="$PROJECT_DIR/venv/bin/python"
UNITS=(
  mumo-signal-service.service
  mumo-admin-dashboard.service
  mumo-signal-tracker.service
  mumo-interactive-bot.service
)

if [[ ! -x "$VENV_PYTHON" ]]; then
  echo "Missing virtualenv interpreter: $VENV_PYTHON" >&2
  exit 1
fi

backup_ts="$(date +%Y%m%d_%H%M%S)"

for unit in "${UNITS[@]}"; do
  unit_path="$SYSTEMD_DIR/$unit"
  if [[ ! -f "$unit_path" ]]; then
    echo "Skipping missing unit: $unit_path"
    continue
  fi

  sudo cp "$unit_path" "$unit_path.bak.$backup_ts"
  sudo sed -i "s|^ExecStart=/usr/bin/python3 $PROJECT_DIR/|ExecStart=$VENV_PYTHON $PROJECT_DIR/|g" "$unit_path"
done

sudo systemctl daemon-reload
sudo systemctl restart mumo-signal-service mumo-admin-dashboard mumo-signal-tracker
sudo systemctl stop mumo-interactive-bot || true

sudo systemctl status mumo-signal-service mumo-admin-dashboard mumo-signal-tracker --no-pager -l
