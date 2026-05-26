#!/bin/bash

# SMC Institutional Trading System - Native Management & Rollback Script
# Lightweight alternative to Docker for venv-based deployments.

set -e

APP_DIR="/home/evans/Projects/smc-scalp-signals"
DB_DIR="$APP_DIR/database"
BACKUP_DIR="$APP_DIR/backups"
VENV_DIR="$APP_DIR/venv"

# ANSI Colors
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${GREEN}"
python3 "$APP_DIR/version.py"
echo -e "${NC}"

usage() {
    echo "Usage: $0 {backup|restore|update|rollback|status|check}"
    echo "  backup   - Snapshot the current signals database"
    echo "  restore  - Restore the database from the latest backup"
    echo "  update   - Pull latest code, run migrations, and snapshot"
    echo "  rollback - Revert to the previous Git version and restore DB"
    echo "  status   - Show current system version and Git state"
    echo "  check    - Run the 391-item test suite for verification"
    exit 1
}

case "$1" in
    backup)
        echo -e "${YELLOW}🔄 Creating database snapshot...${NC}"
        mkdir -p "$BACKUP_DIR"
        TIMESTAMP=$(date +%Y%m%d_%H%M%S)
        cp "$DB_DIR/signals.db" "$BACKUP_DIR/signals_backup_$TIMESTAMP.db"
        echo -e "${GREEN}✅ Backup saved to $BACKUP_DIR/signals_backup_$TIMESTAMP.db${NC}"
        ;;

    restore)
        echo -e "${YELLOW}⚠️  Restoring database from latest backup...${NC}"
        LATEST_BACKUP=$(ls -t "$BACKUP_DIR"/signals_backup_*.db | head -1)
        if [ -z "$LATEST_BACKUP" ]; then
            echo -e "${RED}❌ No backups found!${NC}"
            exit 1
        fi
        cp "$LATEST_BACKUP" "$DB_DIR/signals.db"
        echo -e "${GREEN}✅ Restored from $LATEST_BACKUP${NC}"
        ;;

    update)
        echo -e "${YELLOW}🚀 Starting System Update...${NC}"
        $0 backup
        echo "📥 Pulling latest code..."
        git pull
        echo "📦 Updating dependencies..."
        source "$VENV_DIR/bin/activate"
        pip install -r requirements.txt
        echo "🗄️  Running database migrations..."
        python3 migrations/004_setup_version_tracking.py
        echo -e "${GREEN}✅ Update successful! Run '$0 check' to verify logic.${NC}"
        ;;

    rollback)
        echo -e "${RED}🚨 EMERGENCY ROLLBACK INITIATED 🚨${NC}"
        echo "🔙 Reverting Git to previous state..."
        git reset --hard HEAD@{1}
        $0 restore
        echo -e "${GREEN}✅ Rollback complete. System returned to previous state.${NC}"
        ;;

    status)
        echo -e "${YELLOW}📊 System Status:${NC}"
        python3 "$APP_DIR/version.py"
        echo -e "Git Hash: $(git rev-parse --short HEAD)"
        echo -e "DB Migrations Table check:"
        sqlite3 "$DB_DIR/signals.db" "SELECT migration_name, applied_at FROM system_migrations ORDER BY id DESC LIMIT 1;"
        ;;

    check)
        echo -e "${YELLOW}🧪 Running Full System Verification...${NC}"
        source "$VENV_DIR/bin/activate"
        pytest -v
        ;;

    *)
        usage
        ;;
esac
