import sys
import os
import unittest
import sqlite3
from fastapi.testclient import TestClient
from unittest.mock import patch
import shutil

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from admin_server import MT5Config, User, app, update_mt5_config
from signal_service import SignalService
from config.manager import config_manager

class TestServerConfig(unittest.TestCase):
    def setUp(self):
        self.test_dir = "tests/tmp_config"
        if os.path.exists(self.test_dir):
            shutil.rmtree(self.test_dir)
        os.makedirs(self.test_dir, exist_ok=True)
        self.db_path = os.path.join(self.test_dir, "clients_test.db")
        
        # Initialize test database tables
        conn = sqlite3.connect(self.db_path)
        conn.execute("CREATE TABLE system_config (key TEXT PRIMARY KEY, value TEXT, type TEXT, updated_at TIMESTAMP, updated_by TEXT, version INTEGER DEFAULT 1)")
        conn.execute("CREATE TABLE config_audit (id INTEGER PRIMARY KEY AUTOINCREMENT, key TEXT, old_value TEXT, new_value TEXT, updated_at TIMESTAMP, updated_by TEXT, version INTEGER)")
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
        config_manager.set_runtime_override("db_clients", self.db_path)
        config_manager.set_runtime_override("mt5_paper_mode", True)
        config_manager.set_runtime_override("mt5_login", 0)
        config_manager.set_runtime_override("mt5_password", "")
        config_manager.set_runtime_override("mt5_server", "")
        app.state.disable_reconciliation_loop = True
        
        self.client = TestClient(app)
        
        # Authenticate
        auth_res = self.client.post("/api/token", data={"username": "admin", "password": "admin123"})
        self.token = auth_res.json()["access_token"]
        self.headers = {"Authorization": f"Bearer {self.token}"}
        
    def tearDown(self):
        self.patcher1.stop()
        self.patcher2.stop()
        if os.path.exists(self.test_dir):
            shutil.rmtree(self.test_dir)
        config_manager.clear_runtime_overrides()
        app.state.disable_reconciliation_loop = False

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
        new_risk = 4.5
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

        # 3. Verify Service refreshes centralized runtime config
        service = SignalService()
        service._load_dynamic_config()
        
        self.assertEqual(config_manager.get("risk_per_trade_percent"), new_risk)
        print(f"\n✅ Verified: Config manager updated to {config_manager.get('risk_per_trade_percent')}% (Expected {new_risk}%)")

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

    def test_redacted_mt5_password_does_not_overwrite_stored_secret(self):
        conn = sqlite3.connect(self.db_path)
        conn.executemany(
            """
            INSERT INTO system_config (key, value, type)
            VALUES (?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value, type = excluded.type
            """,
            [
                ("mt5_login", "12345", "int"),
                ("mt5_password", "existing-secret", "str"),
                ("mt5_server", "Demo-Server", "str"),
                ("mt5_paper_mode", "true", "bool"),
            ],
        )
        conn.commit()
        conn.close()
        config_manager.set_runtime_override("mt5_login", 12345)
        config_manager.set_runtime_override("mt5_password", "existing-secret")
        config_manager.set_runtime_override("mt5_server", "Demo-Server")

        import asyncio
        asyncio.run(update_mt5_config(
            MT5Config(login=None, password="********", server=None, paperMode=True),
            current_user=User(username="admin", role="admin"),
        ))

        conn = sqlite3.connect(self.db_path)
        password = conn.execute("SELECT value FROM system_config WHERE key='mt5_password'").fetchone()[0]
        conn.close()

        self.assertEqual(password, "existing-secret")

if __name__ == '__main__':
    unittest.main()
