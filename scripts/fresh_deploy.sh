#!/bin/bash
# fresh_deploy.sh - SMC Scalp Signals Production Deployment Script
# V33.0 Fresh Start Migration

set -e

BASE_DIR="/home/evans/smc-scalp-signals"
BACKUP_DIR="/home/evans/smc-backups/$(date +%Y-%m-%d_%H%M%S)"
REPO_URL="https://github.com/Evansgit254/smc-scalp-signals.git"

echo "🚀 Starting Fresh Production Deployment..."

# 1. Stop existing services
echo "🛑 Stopping services..."
systemctl --user stop smc-signal-service.service || true
systemctl --user stop smc-interactive-bot.service || true
systemctl --user stop smc-signal-tracker.service || true
systemctl --user stop smc-admin-dashboard.service || true

# 2. Backup old data
if [ -d "$BASE_DIR" ]; then
    echo "📦 Backing up old configuration and data to $BACKUP_DIR..."
    mkdir -p "$BACKUP_DIR"
    cp -r "$BASE_DIR/database" "$BACKUP_DIR/" 2>/dev/null || true
    cp "$BASE_DIR/.env" "$BACKUP_DIR/" 2>/dev/null || true
fi

# 3. Fresh Clone/Update
if [ ! -d "$BASE_DIR/.git" ]; then
    echo "📥 First time deployment. Cloning repository..."
    git clone "$REPO_URL" "$BASE_DIR"
else
    echo "🔄 Updating repository logic..."
    cd "$BASE_DIR"
    git fetch origin
    git reset --hard origin/main
fi

cd "$BASE_DIR"

# 4. Prepare Environment
if [ ! -f ".env" ]; then
    echo "📝 Initializing .env from backup or example..."
    if [ -f "$BACKUP_DIR/.env" ]; then
        cp "$BACKUP_DIR/.env" .
    else
        cp .env.example .env
        echo "⚠️  WARNING: .env created from example. Please update secrets manually!"
    fi
fi

# 5. Dependency Management
echo "🐍 Setting up Python environment..."
if [ ! -d "venv" ]; then
    python3 -m venv venv
fi
./venv/bin/pip install --upgrade pip
./venv/bin/pip install -r requirements.txt

# 6. Database Initialization (Fresh Start)
echo "🗄️ Initializing fresh databases..."
mkdir -p database
# We let the app self-initialize on start to ensure schema harmony

# 7. Service Deployment
echo "⚙️  Deploying systemd services..."
mkdir -p ~/.config/systemd/user
# Refine paths in service files during deployment
for srv in smc-*.service; do
    sed -i "s|WorkingDirectory=.*|WorkingDirectory=$BASE_DIR|g" "$srv"
    sed -i "s|Environment=\"PYTHONPATH=.*|Environment=\"PYTHONPATH=$BASE_DIR\"|g" "$srv"
    sed -i "s|ExecStart=.*|ExecStart=$BASE_DIR/venv/bin/python $BASE_DIR/$(echo $srv | sed 's/smc-//;s/.service/.py/')|g" "$srv"
    
    # Special cases for different entry points
    if [[ "$srv" == *"bot"* ]]; then
        sed -i "s|ExecStart=.*|ExecStart=$BASE_DIR/venv/bin/python $BASE_DIR/app/interactive_bot.py|g" "$srv"
    fi
    
    cp "$srv" ~/.config/systemd/user/
done

systemctl --user daemon-reload
systemctl --user enable smc-signal-service.service
systemctl --user enable smc-interactive-bot.service

# 8. Start & Verify
echo "🚀 Starting services..."
systemctl --user restart smc-signal-service.service
systemctl --user restart smc-interactive-bot.service

echo "✅ Deployment complete!"
echo "Check logs: journalctl --user -u smc-signal-service -f"
