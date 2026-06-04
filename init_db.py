"""
Initialize the clients.db with required tables for backtest execution.
The backtest engine needs system_config table for ExecutionGate thresholds.
"""
import sqlite3
import os

DB_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "database")
os.makedirs(DB_DIR, exist_ok=True)

clients_db = os.path.join(DB_DIR, "clients.db")

print(f"Initializing {clients_db}...")

with sqlite3.connect(clients_db) as conn:
    # system_config table (required by ExecutionGate._get_thresholds)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS system_config (
            key TEXT PRIMARY KEY,
            value TEXT,
            type TEXT DEFAULT 'string',
            updated_at TEXT
        )
    """)
    
    # weight_overrides table (required by ExecutionGate._get_thresholds)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS weight_overrides (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_type TEXT,
            multiplier REAL DEFAULT 1.0,
            is_active INTEGER DEFAULT 1
        )
    """)
    
    # Insert default config values
    defaults = [
        ("MIN_QUALITY_SCORE", "7.0", "float"),
        ("MIN_EXECUTION_QUALITY", "5.0", "float"),
        ("MAX_CORRELATED_EXPOSURE", "2", "int"),
        ("MAX_STRATEGY_EXPOSURE", "3", "int"),
        ("MAX_SESSION_EXPOSURE", "4", "int"),
        ("data_provider", "yfinance", "string"),
        ("system_status", "ACTIVE", "string"),
    ]
    
    for key, value, type_ in defaults:
        conn.execute(
            "INSERT OR IGNORE INTO system_config (key, value, type) VALUES (?, ?, ?)",
            (key, value, type_)
        )
    
    conn.commit()

print("✅ clients.db initialized successfully")
print(f"   Tables: system_config, weight_overrides")

# Also initialize signals.db (required by AlphaCombiner forensic multiplier)
signals_db = os.path.join(DB_DIR, "signals.db")
print(f"\nInitializing {signals_db}...")

with sqlite3.connect(signals_db) as conn:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS signals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            strategy TEXT,
            strategy_name TEXT,
            symbol TEXT,
            direction TEXT,
            timeframe TEXT,
            entry_price REAL,
            sl REAL,
            tp1 REAL,
            tp2 REAL,
            result TEXT,
            result_pips REAL,
            status TEXT DEFAULT 'OPEN',
            gate_status TEXT,
            gate_reason TEXT,
            regime TEXT,
            quality_score REAL,
            confidence REAL,
            forensic_events TEXT,
            timestamp TEXT,
            closed_at TEXT,
            run_id INTEGER
        )
    """)
    
    conn.execute("""
        CREATE TABLE IF NOT EXISTS paper_account (
            id INTEGER PRIMARY KEY,
            balance REAL DEFAULT 200.0,
            equity REAL DEFAULT 200.0,
            updated_at TEXT
        )
    """)
    
    conn.execute(
        "INSERT OR IGNORE INTO paper_account (id, balance, equity) VALUES (1, 200.0, 200.0)"
    )
    
    conn.commit()

print("✅ signals.db initialized successfully")
print("   Tables: signals, paper_account")
print("\n🎯 Database initialization complete. Ready for backtest.")
