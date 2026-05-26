import pytest
from fastapi.testclient import TestClient
from admin_server import app
from unittest.mock import patch
import sqlite3
import os
from datetime import datetime, timedelta

@pytest.fixture
def client():
    return TestClient(app)

@pytest.fixture(autouse=True)
def setup_test_dbs(tmp_path):
    # Use temporary databases for testing
    clients_db = str(tmp_path / "clients.db")
    signals_db = str(tmp_path / "signals.db")
    
    # Initialize clients DB
    conn = sqlite3.connect(clients_db)
    conn.execute("""
        CREATE TABLE clients (
            client_id INTEGER PRIMARY KEY,
            telegram_chat_id TEXT UNIQUE,
            account_balance REAL,
            risk_percent REAL DEFAULT 2.0,
            subscription_expiry TIMESTAMP,
            subscription_tier TEXT,
            is_active BOOLEAN DEFAULT 1,
            updated_at TIMESTAMP
        )
    """)
    conn.execute("INSERT INTO clients (telegram_chat_id, account_balance) VALUES ('123', 1000.0)")
    
    # Initialize system_config for Master Switch (V23.1)
    conn.execute("CREATE TABLE IF NOT EXISTS system_config (key TEXT PRIMARY KEY, value TEXT, type TEXT)")
    conn.execute("INSERT OR IGNORE INTO system_config VALUES ('system_status', 'ACTIVE', 'str')")
    
    conn.commit()
    conn.close()
    
    # Initialize signals DB
    conn = sqlite3.connect(signals_db)
    conn.execute("""
        CREATE TABLE signals (
            id INTEGER PRIMARY KEY,
            timestamp TIMESTAMP,
            symbol TEXT,
            direction TEXT,
            entry_price REAL,
            sl REAL,
            tp1 REAL,
            tp2 REAL,
            reasoning TEXT,
            timeframe TEXT,
            confidence REAL,
            trade_type TEXT,
            quality_score REAL,
            regime TEXT,
            expected_hold TEXT,
            risk_details TEXT,
            score_details TEXT,
            forensic_candles TEXT,
            forensic_events TEXT,
            gate_status TEXT,
            gate_reason TEXT
        )
    """)
    conn.commit()
    conn.close()
    
    # Initialize users DB (added for V22.1 JWT compatibility)
    users_db = clients_db # users table is in the same DB as clients by default in admin_server
    conn = sqlite3.connect(users_db)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS admin_users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE,
            password_hash TEXT
        )
    """)
    # admin/admin123
    import hashlib
    salt = "static_test_salt"
    pwd_hash = hashlib.sha256(("admin123" + salt).encode()).hexdigest()
    stored_val = f"{salt}${pwd_hash}"
    conn.execute("INSERT OR IGNORE INTO admin_users (username, password_hash) VALUES (?, ?)", ("admin", stored_val))
    conn.commit()
    conn.close()

    with patch('admin_server.DB_CLIENTS', clients_db), \
         patch('admin_server.DB_SIGNALS', signals_db), \
         patch('config.config.DB_CLIENTS', clients_db), \
         patch('config.config.DB_SIGNALS', signals_db):
        yield

@pytest.fixture
def auth_headers(client):
    # Login to get token
    response = client.post("/api/token", data={"username": "admin", "password": "admin123"})
    token = response.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}

def test_read_clients(client, auth_headers):
    response = client.get("/api/clients", headers=auth_headers)
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]['telegram_chat_id'] == '123'

def test_update_client(client, auth_headers):
    update_data = {
        "account_balance": 1500.0,
        "subscription_days": 30,
        "tier": "GOLD",
        "is_active": True
    }
    response = client.post("/api/clients/123", json=update_data, headers=auth_headers)
    assert response.status_code == 200
    
    # Verify update
    response = client.get("/api/clients", headers=auth_headers)
    updated = response.json()[0]
    assert updated['account_balance'] == 1500.0
    assert updated['subscription_tier'] == 'GOLD'
    assert updated['subscription_expiry'] is not None

def test_update_non_existent_client(client, auth_headers):
    response = client.post("/api/clients/999", json={"account_balance": 100}, headers=auth_headers)
    assert response.status_code == 404

def test_read_signals_empty(client, auth_headers):
    response = client.get("/api/signals", headers=auth_headers)
    assert response.status_code == 200
    assert response.json() == []

def test_get_stats(client, auth_headers):
    response = client.get("/api/stats", headers=auth_headers)
    assert response.status_code == 200
    data = response.json()
    assert data['active_clients'] == 1
    assert data['signals_today'] == 0
    assert 'server_time' in data

def test_update_client_all_fields(client, auth_headers):
    update_data = {
        "account_balance": 2000.0,
        "risk_percent": 3.5,
        "subscription_days": 10,
        "tier": "PLATINUM",
        "is_active": False
    }
    response = client.post("/api/clients/123", json=update_data, headers=auth_headers)
    assert response.status_code == 200
    
    # Verify update
    response = client.get("/api/clients", headers=auth_headers)
    updated = response.json()[0]
    assert updated['account_balance'] == 2000.0
    assert updated['risk_percent'] == 3.5
    assert updated['subscription_tier'] == 'PLATINUM'
    assert updated['is_active'] == 0

def test_update_client_no_fields(client, auth_headers):
    response = client.post("/api/clients/123", json={}, headers=auth_headers)
    assert response.status_code == 200

def test_get_signals_with_data(client, tmp_path, auth_headers):
    signals_db = str(tmp_path / "signals_test.db")
    # Insert a mock signal
    conn = sqlite3.connect(signals_db)
    conn.execute("""
        CREATE TABLE signals (
            id INTEGER PRIMARY KEY,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            symbol TEXT,
            direction TEXT,
            entry_price REAL,
            sl REAL,
            tp1 REAL,
            tp2 REAL,
            reasoning TEXT,
            timeframe TEXT,
            confidence REAL,
            result TEXT DEFAULT 'OPEN',
            closed_at TIMESTAMP,
            max_tp_reached INTEGER DEFAULT 0,
            trade_type TEXT,
            quality_score REAL,
            regime TEXT,
            expected_hold TEXT,
            risk_details TEXT,
            score_details TEXT,
            forensic_candles TEXT,
            forensic_events TEXT,
            gate_status TEXT,
            gate_reason TEXT
        )
    """)
    conn.execute("INSERT INTO signals (symbol, direction, entry_price, sl, tp1, tp2, confidence) VALUES ('EURUSD', 'BUY', 1.10, 1.09, 1.11, 1.12, 0.9)")
    conn.commit()
    conn.close()
    
    with patch('admin_server.DB_SIGNALS', signals_db):
        response = client.get("/api/signals", headers=auth_headers)
        assert response.status_code == 200
        assert len(response.json()) == 1
        assert response.json()[0]['symbol'] == 'EURUSD'

def test_daily_analytics(client, tmp_path, auth_headers):
    signals_db = str(tmp_path / "signals_analytics.db")
    conn = sqlite3.connect(signals_db)
    conn.execute("""
        CREATE TABLE signals (
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            symbol TEXT,
            direction TEXT,
            quality_score REAL,
            trade_type TEXT DEFAULT 'SCALP',
            result TEXT DEFAULT 'OPEN',
            max_tp_reached INTEGER DEFAULT 0
        )
    """)
    today = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    conn.execute("INSERT INTO signals (timestamp, symbol, direction, quality_score, trade_type) VALUES (?, ?, ?, ?, ?)", (today, 'EURUSD', 'BUY', 8.5, 'SCALP'))
    conn.execute("INSERT INTO signals (timestamp, symbol, direction, quality_score, trade_type) VALUES (?, ?, ?, ?, ?)", (today, 'EURUSD', 'BUY', 7.5, 'SCALP'))
    conn.execute("INSERT INTO signals (timestamp, symbol, direction, quality_score, trade_type) VALUES (?, ?, ?, ?, ?)", (today, 'GBPUSD', 'SELL', 6.0, 'SWING'))
    conn.commit()
    conn.close()

    with patch('admin_server.DB_SIGNALS', signals_db):
        response = client.get("/api/analytics/daily", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert data['total_signals'] == 3
        # Average of 8.5, 7.5, 6.0 = 22.0 / 3 = 7.333... -> rounded to 1 decimal in endpoint is 7.3
        assert data['avg_quality'] == 7.3
        assert data['bias']['BUY'] == 2
        assert data['bias']['SELL'] == 1
        assert data['assets'][0]['symbol'] == 'EURUSD'
        assert data['assets'][0]['count'] == 2

def test_toggle_signals(client, auth_headers):
    # Initial state is 1
    response = client.post("/api/clients/123/toggle-signals", headers=auth_headers)
    assert response.status_code == 200
    assert response.json()['is_active'] == 0
    
    response = client.post("/api/clients/123/toggle-signals", headers=auth_headers)
    assert response.status_code == 200
    assert response.json()['is_active'] == 1

def test_quick_extend(client, auth_headers):
    response = client.post("/api/clients/123/extend?days=15", headers=auth_headers)
    assert response.status_code == 200
    assert response.json()['status'] == "success"

def test_get_current_user_invalid_token(client):
    response = client.get("/api/clients", headers={"Authorization": "Bearer invalid"})
    assert response.status_code == 401

def test_login_invalid_creds(client):
    response = client.post("/api/token", data={"username": "admin", "password": "wrong"})
    assert response.status_code == 401

@pytest.mark.asyncio
async def test_ensure_db_schema_success(tmp_path):
    db = str(tmp_path / "schema_test.db")
    # Must exist for the function to proceed
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE signals (id INTEGER PRIMARY KEY)") # Base table
    conn.commit()
    conn.close()
    
    from admin_server import ensure_db_schema
    with patch('admin_server.DB_SIGNALS', db):
        ensure_db_schema()
        # Verify columns exist
        conn = sqlite3.connect(db)
        cursor = conn.execute("PRAGMA table_info(signals)")
        cols = [row[1] for row in cursor.fetchall()]
        assert 'trade_type' in cols
        conn.close()

