"""
Client Management System for Multi-Client Signal Service

Handles client registration, balance tracking, and personalized risk calculations.
"""
import sqlite3
import os
from datetime import datetime
from typing import Optional, Dict, List

class ClientManager:
    def __init__(self, db_path: str = "database/clients.db"):
        self.db_path = db_path
        self._init_database()
    
    def _init_database(self):
        """Initialize the client database with schema."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS clients (
                client_id INTEGER PRIMARY KEY AUTOINCREMENT,
                telegram_chat_id TEXT UNIQUE NOT NULL,
                account_balance REAL NOT NULL,
                risk_percent REAL DEFAULT 2.0,
                max_concurrent_trades INTEGER DEFAULT 4,
                subscription_expiry TIMESTAMP,
                subscription_tier TEXT DEFAULT 'BASIC',
                is_active BOOLEAN DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        
        # Add new columns if they don't exist (Migration)
        for col_name, col_def in [
            ("subscription_expiry", "TIMESTAMP"),
            ("subscription_tier", "TEXT DEFAULT 'BASIC'"),
            ("dashboard_access", "BOOLEAN DEFAULT 0"),
        ]:
            try:
                cursor.execute(f"ALTER TABLE clients ADD COLUMN {col_name} {col_def}")
            except sqlite3.OperationalError:
                # Column already exists
                pass
        
        conn.commit()
        conn.close()

    
    def register_client(self, telegram_chat_id: str, account_balance: float, 
                       risk_percent: float = 2.0) -> Dict:
        """
        Register a new client.
        
        Args:
            telegram_chat_id: Telegram chat ID (unique identifier)
            account_balance: Initial account balance
            risk_percent: Risk percentage per trade (default 2.0%)
        
        Returns:
            Dict with client information
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        try:
            cursor.execute("""
                INSERT INTO clients (telegram_chat_id, account_balance, risk_percent)
                VALUES (?, ?, ?)
            """, (telegram_chat_id, account_balance, risk_percent))
            
            conn.commit()
            client_id = cursor.lastrowid
            
            return {
                'client_id': client_id,
                'telegram_chat_id': telegram_chat_id,
                'account_balance': account_balance,
                'risk_percent': risk_percent,
                'status': 'registered'
            }
        except sqlite3.IntegrityError:
            return {'status': 'error', 'message': 'Client already registered'}
        finally:
            conn.close()
    
    def get_client(self, telegram_chat_id: str) -> Optional[Dict]:
        """Get client information by Telegram chat ID."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT client_id, telegram_chat_id, account_balance, risk_percent, 
                   max_concurrent_trades, is_active
            FROM clients
            WHERE telegram_chat_id = ? AND is_active = 1
        """, (telegram_chat_id,))
        
        row = cursor.fetchone()
        conn.close()
        
        if row:
            return {
                'client_id': row[0],
                'telegram_chat_id': row[1],
                'account_balance': row[2],
                'risk_percent': row[3],
                'max_concurrent_trades': row[4],
                'is_active': bool(row[5])
            }
        return None
    
    def get_all_active_clients(self) -> List[Dict]:
        """Get all active clients."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT client_id, telegram_chat_id, account_balance, risk_percent, 
                   max_concurrent_trades
            FROM clients
            WHERE is_active = 1
        """)
        
        clients = []
        for row in cursor.fetchall():
            clients.append({
                'client_id': row[0],
                'telegram_chat_id': row[1],
                'account_balance': row[2],
                'risk_percent': row[3],
                'max_concurrent_trades': row[4]
            })
        
        conn.close()
        return clients
    
    def update_balance(self, telegram_chat_id: str, new_balance: float) -> Dict:
        """Update client's account balance."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute("""
            UPDATE clients
            SET account_balance = ?, updated_at = ?
            WHERE telegram_chat_id = ?
        """, (new_balance, datetime.now(), telegram_chat_id))
        
        conn.commit()
        affected = cursor.rowcount
        conn.close()
        
        if affected > 0:
            return {'status': 'success', 'new_balance': new_balance}
        return {'status': 'error', 'message': 'Client not found'}
    
    def update_risk_percent(self, telegram_chat_id: str, risk_percent: float) -> Dict:
        """Update client's risk percentage."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute("""
            UPDATE clients
            SET risk_percent = ?, updated_at = ?
            WHERE telegram_chat_id = ?
        """, (risk_percent, datetime.now(), telegram_chat_id))
        
        conn.commit()
        affected = cursor.rowcount
        conn.close()
        
        if affected > 0:
            return {'status': 'success', 'risk_percent': risk_percent}
        return {'status': 'error', 'message': 'Client not found'}
    
    def deactivate_client(self, telegram_chat_id: str) -> Dict:
        """Deactivate a client (soft delete)."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute("""
            UPDATE clients
            SET is_active = 0, updated_at = ?
            WHERE telegram_chat_id = ?
        """, (datetime.now(), telegram_chat_id))
        
        conn.commit()
        affected = cursor.rowcount
        conn.close()
        
        if affected > 0:
            return {'status': 'success', 'message': 'Client deactivated'}
        return {'status': 'error', 'message': 'Client not found'}
    
    def get_client_count(self) -> int:
        """Get total number of active clients."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute("SELECT COUNT(*) FROM clients WHERE is_active = 1")
        count = cursor.fetchone()[0]
        
        conn.close()
        return count

    def update_subscription(self, telegram_chat_id: str, days: int, tier: str = "BASIC") -> Dict:
        """
        Extends or starts a subscription.
        """
        from datetime import timedelta
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Get current expiry
        cursor.execute("SELECT subscription_expiry FROM clients WHERE telegram_chat_id = ?", (telegram_chat_id,))
        row = cursor.fetchone()
        
        if not row:
            conn.close()
            return {'status': 'error', 'message': 'Client not found'}
            
        current_expiry_str = row[0]
        now = datetime.now()
        
        if current_expiry_str:
            current_expiry = datetime.strptime(current_expiry_str, "%Y-%m-%d %H:%M:%S.%f") if "." in current_expiry_str else datetime.strptime(current_expiry_str, "%Y-%m-%d %H:%M:%S")
            start_date = max(now, current_expiry)
        else:
            start_date = now
            
        new_expiry = start_date + timedelta(days=days)
        
        cursor.execute("""
            UPDATE clients 
            SET subscription_expiry = ?, subscription_tier = ?, updated_at = ?
            WHERE telegram_chat_id = ?
        """, (new_expiry, tier, now, telegram_chat_id))
        
        conn.commit()
        conn.close()
        return {'status': 'success', 'new_expiry': new_expiry.strftime("%Y-%m-%d %H:%M:%S"), 'tier': tier}

    def is_subscription_active(self, telegram_chat_id: str) -> bool:
        """
        Checks if a client's subscription is still valid.
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute("SELECT subscription_expiry FROM clients WHERE telegram_chat_id = ?", (telegram_chat_id,))
        row = cursor.fetchone()
        conn.close()
        
        if not row or not row[0]:
            return False
            
        expiry_str = row[0]
        try:
            expiry = datetime.strptime(expiry_str, "%Y-%m-%d %H:%M:%S.%f") if "." in expiry_str else datetime.strptime(expiry_str, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            # Handle standard YYYY-MM-DD format if stored like that
            expiry = datetime.strptime(expiry_str, "%Y-%m-%d")
            
        return expiry > datetime.now()
