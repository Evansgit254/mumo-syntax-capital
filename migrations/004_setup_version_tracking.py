import sqlite3
import os
import sys
from datetime import datetime

# Path to versioning file to coordinate DB version with Code version
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
try:
    from version import get_version
except ImportError:
    def get_version(): return "5.1.0" # Fallback

DB_PATH = "database/signals.db"

def migrate():
    """
    Creates a 'system_versions' table to track migration history.
    This enables rolling back or checking current schema state without manual SQL.
    """
    if not os.path.exists("database"):
        os.makedirs("database")

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # 1. Ensure version tracking table exists
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS system_migrations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            version TEXT NOT NULL,
            migration_name TEXT NOT NULL,
            applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    # 2. Check if this specific migration has already been run
    cursor.execute("SELECT id FROM system_migrations WHERE migration_name = '004_setup_version_tracking'")
    if cursor.fetchone():
        print("ℹ️  Migration 004 already applied. Skipping.")
        conn.close()
        return

    print("🔄 Applying migration 004: Version Tracking Infrastructure...")
    
    # In a real system, we might add a 'config' table if it doesn't exist
    # Here we just initialize the tracking for current code version
    current_ver = get_version()
    
    cursor.execute(
        "INSERT INTO system_migrations (version, migration_name) VALUES (?, ?)",
        (current_ver, '004_setup_version_tracking')
    )
    
    conn.commit()
    conn.close()
    print(f"✅ Version tracking initialized at {current_ver}")

if __name__ == "__main__":
    migrate()
