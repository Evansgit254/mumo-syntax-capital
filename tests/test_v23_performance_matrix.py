import json
import sqlite3
import os
import sys
from datetime import datetime, timedelta
from fastapi.testclient import TestClient
from unittest.mock import patch

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from admin_server import app

DB_PATH = "database/matrix_test.db"

def setup_test_db():
    if os.path.exists(DB_PATH): os.remove(DB_PATH)
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE signals (
            id INTEGER PRIMARY KEY,
            timestamp TIMESTAMP,
            symbol TEXT,
            direction TEXT,
            entry_price REAL,
            trade_type TEXT,
            quality_score REAL,
            result TEXT,
            max_tp_reached INTEGER DEFAULT 0,
            closed_at TIMESTAMP
        )
    """)

    conn.execute("""
        CREATE TABLE admin_users (
            username TEXT PRIMARY KEY,
            password_hash TEXT,
            last_login TEXT
        )
    """)

    conn.execute("""
        CREATE TABLE system_config (
            key TEXT PRIMARY KEY,
            value TEXT,
            type TEXT
        )
    """)

    # admin/admin123
    import hashlib
    salt = "static_test_salt"
    pwd_hash = hashlib.sha256(("admin123" + salt).encode()).hexdigest()
    stored_val = f"{salt}${pwd_hash}"
    conn.execute("INSERT INTO admin_users (username, password_hash) VALUES (?, ?)", ("admin", stored_val))
    
    now = datetime.utcnow()
    
    # Mock Signals for Matrix Verification
    signals = [
        # EURUSD: 1 Scalp Win, 1 Scalp Loss
        (now.isoformat(), 'EURUSD=X', 'BUY', 1.0800, 'SCALP', 8.5, 'TP3', 3),
        ((now - timedelta(minutes=10)).isoformat(), 'EURUSD=X', 'SELL', 1.0810, 'SCALP', 6.0, 'SL', 0),
        
        # GBPJPY: 1 Session Clock Win
        (now.isoformat(), 'GBPJPY=X', 'SELL', 180.00, 'SESSION_CLOCK', 8.5, 'TP1', 1),
        
        # OIL: 1 Advanced Pattern Win
        (now.isoformat(), 'CL=F', 'BUY', 70.00, 'ADVANCED_PATTERN', 9.5, 'TP2', 2),
        
        # BTC: 1 Swing Open
        (now.isoformat(), 'BTC-USD', 'BUY', 60000.0, 'SWING', 7.0, 'OPEN', 0),
    ]
    
    for s in signals:
        conn.execute("""
            INSERT INTO signals (timestamp, symbol, direction, entry_price, trade_type, quality_score, result, max_tp_reached)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, s)
    
    conn.commit()
    conn.close()

def test_strategy_symbol_breakdown():
    setup_test_db()
    
    with patch('admin_server.DB_SIGNALS', DB_PATH), \
         patch('admin_server.DB_CLIENTS', DB_PATH), \
         patch('config.config.DB_SIGNALS', DB_PATH), \
         patch('config.config.DB_CLIENTS', DB_PATH):
        
        client = TestClient(app)
        
        # Authenticate
        auth_res = client.post("/api/token", data={"username": "admin", "password": "admin123"})
        token = auth_res.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}
    
        response = client.get("/api/analytics/daily", headers=headers)
        assert response.status_code == 200
        data = response.json()
        
        matrix = data['strategy_symbol_breakdown']
        assert len(matrix) > 0
        
        # 1. Verify EURUSD Scalp (2 total, 1 win, 1 loss)
        eurusd_scalp = next((r for r in matrix if r['symbol'] == 'EURUSD=X' and r['trade_type'] == 'SCALP'), None)
        assert eurusd_scalp is not None
        assert eurusd_scalp['total'] == 2
        assert eurusd_scalp['wins'] == 1
        assert eurusd_scalp['losses'] == 1
        
        # 2. Verify GBPJPY Session Clock (1 total, 1 win)
        gbpjpy_clock = next((r for r in matrix if r['symbol'] == 'GBPJPY=X' and r['trade_type'] == 'SESSION_CLOCK'), None)
        assert gbpjpy_clock is not None
        assert gbpjpy_clock['total'] == 1
        assert gbpjpy_clock['wins'] == 1
        
        # 3. Verify BTC Swing (1 total, 1 open)
        btc_swing = next((r for r in matrix if r['symbol'] == 'BTC-USD' and r['trade_type'] == 'CRT'), None)
        assert btc_swing is not None
        assert btc_swing['total'] == 1
        assert btc_swing['open'] == 1
        assert btc_swing['wins'] == 0
        
        print("\n✅ Strategy-Symbol Performance Matrix API Test Passed!")
    
    # if os.path.exists(DB_PATH): os.remove(DB_PATH)

if __name__ == "__main__":
    test_strategy_symbol_breakdown()
