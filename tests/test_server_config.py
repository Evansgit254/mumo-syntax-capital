import sys
import os
import unittest
import sqlite3
from fastapi.testclient import TestClient
from unittest.mock import patch
import shutil

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from admin_server import app, DB_CLIENTS
from signal_service import SignalService
import config.config as cfg

class TestServerConfig(unittest.TestCase):
    def setUp(self):
        self.test_dir = "tests/tmp_config"
        os.makedirs(self.test_dir, exist_ok=True)
        self.db_path = os.path.join(self.test_dir, "clients_test.db")
        
        # Initialize test database tables
        conn = sqlite3.connect(self.db_path)
        conn.execute("CREATE TABLE system_config (key TEXT PRIMARY KEY, value TEXT, type TEXT)")
        conn.execute("CREATE TABLE admin_users (username TEXT PRIMARY KEY, password_hash TEXT, last_login TEXT)")
        
        # Add default config
        defaults = [
            ("system_status", "ACTIVE", "str"),
            ("risk_per_trade", "2.0", "float")
        ]
        conn.executemany("INSERT INTO system_config (key, value, type) VALUES (?, ?, ?)", defaults)
        
        # Add admin user (admin/admin123)
        import hashlib
        salt = "test_salt"
        pwd_hash = hashlib.sha256(("admin123" + salt).encode()).hexdigest()
        conn.execute("INSERT INTO admin_users (username, password_hash) VALUES (?, ?)", ("admin", f"{salt}${pwd_hash}"))
        conn.commit()
        conn.close()

        # Patch DB_CLIENTS in config.config and admin_server
        self.patcher1 = patch('config.config.DB_CLIENTS', self.db_path)
        self.patcher2 = patch('admin_server.DB_CLIENTS', self.db_path)
        self.patcher1.start()
        self.patcher2.start()
        
        self.client = TestClient(app)
        
        # Authenticate
        auth_res = self.client.post("/api/token", data={"username": "admin", "password": "admin123"})
        self.token = auth_res.json()["access_token"]
        self.headers = {"Authorization": f"Bearer {self.token}"}
        
        self.original_risk = 2.0

    def tearDown(self):
        self.patcher1.stop()
        self.patcher2.stop()
        if os.path.exists(self.test_dir):
            shutil.rmtree(self.test_dir)
        
        # Reset in memory config
        import config.config as cfg
        cfg.RISK_PER_TRADE_PERCENT = self.original_risk

    def test_get_config(self):
        """Test retrieving configuration via API"""
        response = self.client.get("/api/config", headers=self.headers)
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("risk_per_trade", data)
        self.assertIn("system_status", data)

    def test_update_config_and_service_load(self):
        """Test updating config via API and verifying service loads it"""
        # 1. Update Config via API
        new_risk = 5.5
        response = self.client.post("/api/config", json={"key": "risk_per_trade", "value": str(new_risk)}, headers=self.headers)
        if response.status_code != 200:
            print(f"ERROR: {response.json()}")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["value"], str(new_risk))

        # 2. Verify in Database
        conn = sqlite3.connect(self.db_path)
        val = conn.execute("SELECT value FROM system_config WHERE key='risk_per_trade'").fetchone()[0]
        conn.close()
        self.assertEqual(float(val), new_risk)

        # 3. Verify Service loads it
        service = SignalService()
        # Mock telegram to avoid errors during init if not set, 
        # but SignalService init only sets self.telegram = TelegramService()
        # We just want to test _load_dynamic_config
        
        # Reset config module to default (simulating fresh start or pre-update state)
        cfg.RISK_PER_TRADE_PERCENT = 2.0 
        
        service._load_dynamic_config()
        
        self.assertEqual(cfg.RISK_PER_TRADE_PERCENT, new_risk)
        print(f"\n✅ Verified: Config module updated to {cfg.RISK_PER_TRADE_PERCENT}% (Expected {new_risk}%)")

    def test_ensure_defaults(self):
        """Test that missing defaults are inserted even if table exists"""
        # 1. Clear config table
        conn = sqlite3.connect(self.db_path)
        conn.execute("DELETE FROM system_config")
        
        # 2. Insert ONE random key (making count > 0)
        conn.execute("INSERT INTO system_config (key, value, type) VALUES ('custom_key', '123', 'int')")
        conn.commit()
        conn.close()
        
        # 3. Run ensure_config_table (via import or calling it if we made it importable)
        # Since it runs on import, we need to call it manually. 
        # But we need to import it properly. 
        from admin_server import ensure_config_table
        ensure_config_table()
        
        # 4. Verify defaults are back
        conn = sqlite3.connect(self.db_path)
        risk = conn.execute("SELECT value FROM system_config WHERE key='risk_per_trade'").fetchone()
        conn.close()
        
        self.assertIsNotNone(risk)
        self.assertEqual(float(risk[0]), 2.0)
        print("\n✅ Verified: Defaults backfilled successfully")

if __name__ == '__main__':
    unittest.main()
