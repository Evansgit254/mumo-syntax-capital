#!/bin/bash
echo "🚀 Deploying Trading Services..."

# Copy service files to systemd user directory
mkdir -p ~/.config/systemd/user
cp mumo-*.service ~/.config/systemd/user/
cp monitoring/*.service ~/.config/systemd/user/ 2>/dev/null || true

# Reload systemd
systemctl --user daemon-reload

# Enable and start core services
systemctl --user enable mumo-signal-service.service
systemctl --user start mumo-signal-service.service

systemctl --user enable mumo-interactive-bot.service
systemctl --user start mumo-interactive-bot.service

systemctl --user enable mumo-health-watchdog.service
systemctl --user start mumo-health-watchdog.service

# Enable lingering so services run when evans logs out
sudo loginctl enable-linger evans

echo "✅ Deployment complete. Checking status..."
systemctl --user status mumo-signal-service.service --no-pager | head -n 5
