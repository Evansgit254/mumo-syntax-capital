import json
import sqlite3
import os
import sys
from datetime import datetime
from fastapi.testclient import TestClient
from unittest.mock import patch

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from admin_server import app

DB_PATH = "database/signals_integration_test.db"

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

    # admin/admin123
    import hashlib
    salt = "static_test_salt"
    pwd_hash = hashlib.sha256(("admin123" + salt).encode()).hexdigest()
    stored_val = f"{salt}${pwd_hash}"
    conn.execute("INSERT INTO admin_users (username, password_hash) VALUES (?, ?)", ("admin", stored_val))
    
    today = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    
    # Insert Mock Signals
    signals = [
        # Win Scalp
        (today, 'EURUSD=X', 'BUY', 1.0800, 'SCALP', 8.5, 'TP3', 3),
        # Loss Scalp
        (today, 'GBPUSD=X', 'SELL', 1.2500, 'SCALP', 6.0, 'SL', 0),
        # Win Swing
        (today, 'NZDUSD=X', 'BUY', 0.6100, 'SWING', 9.0, 'TP2', 2),
        # Open Swing
        (today, 'AUDUSD=X', 'SELL', 0.6500, 'SWING', 7.5, 'OPEN', 0),
    ]
    
    for s in signals:
        conn.execute("""
            INSERT INTO signals (timestamp, symbol, direction, entry_price, trade_type, quality_score, result, max_tp_reached)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, s)
    
    conn.commit()
    conn.close()

def test_analytics_api():
    setup_test_db()
    
    with patch('admin_server.DB_SIGNALS', DB_PATH), \
         patch('admin_server.DB_CLIENTS', DB_PATH), \
         patch('config.config.DB_SIGNALS', DB_PATH), \
         patch('config.config.DB_CLIENTS', DB_PATH):
        
        client = TestClient(app)
        
        # Authenticate to get token (Standard Admin Credentials)
        auth_res = client.post("/api/token", data={"username": "admin", "password": "admin123"})
        token = auth_res.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}
    
        response = client.get("/api/analytics/daily", headers=headers)
        
        assert response.status_code == 200
        data = response.json()
        
        print("\n📊 API RESPONSE VERIFICATION:")
        print(json.dumps(data, indent=2))
        
        # Verify Scalp Stats
        scalp = data['stats_by_type']['SCALP']
        assert scalp['total'] == 2
        assert scalp['wins'] == 1
        assert scalp['losses'] == 1
        
        # Verify CRT Stats (Formerly SWING)
        swing = data['stats_by_type']['CRT']
        assert swing['total'] == 2
        assert swing['wins'] == 1 # NZDUSD Win
        
        # Verify Top Performer
        assert data['top_performer'] is not None
        
        print("\n✅ Analytics API Integration Test Passed!")
    
    if os.path.exists(DB_PATH): os.remove(DB_PATH)

if __name__ == "__main__":
    test_analytics_api()
