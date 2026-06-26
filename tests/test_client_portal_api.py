import hashlib
import os
import sqlite3
from datetime import datetime, timedelta
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from admin_server import app


def _legacy_hash(password: str) -> str:
    salt = "static_test_salt"
    pwd_hash = hashlib.sha256((password + salt).encode()).hexdigest()
    return f"{salt}${pwd_hash}"


@pytest.fixture
def portal_dbs(tmp_path):
    clients_db = str(tmp_path / "clients.db")
    signals_db = str(tmp_path / "signals.db")

    conn = sqlite3.connect(clients_db)
    conn.execute("""
        CREATE TABLE clients (
            client_id INTEGER PRIMARY KEY AUTOINCREMENT,
            telegram_chat_id TEXT UNIQUE NOT NULL,
            account_balance REAL NOT NULL,
            risk_percent REAL DEFAULT 2.0,
            subscription_expiry TIMESTAMP,
            subscription_tier TEXT DEFAULT 'BASIC',
            is_active BOOLEAN DEFAULT 1,
            dashboard_access BOOLEAN DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.execute("""
        CREATE TABLE admin_users (
            username TEXT PRIMARY KEY,
            password_hash TEXT,
            last_login TEXT,
            role TEXT DEFAULT 'admin'
        )
    """)
    conn.execute("""
        CREATE TABLE client_signal_entitlements (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            telegram_chat_id TEXT NOT NULL,
            signal_id INTEGER NOT NULL,
            signal_uid TEXT,
            delivery_status TEXT DEFAULT 'ENTITLED',
            delivery_channel TEXT DEFAULT 'telegram',
            tier_at_delivery TEXT,
            created_at TEXT NOT NULL,
            delivered_at TEXT,
            UNIQUE(telegram_chat_id, signal_id)
        )
    """)
    active_expiry = (datetime.utcnow() + timedelta(days=30)).strftime("%Y-%m-%d %H:%M:%S")
    expired = (datetime.utcnow() - timedelta(days=1)).strftime("%Y-%m-%d %H:%M:%S")
    conn.execute(
        "INSERT INTO admin_users (username, password_hash, role) VALUES (?, ?, ?)",
        ("CLIENT_A", _legacy_hash("clientpass"), "client"),
    )
    conn.execute(
        "INSERT INTO admin_users (username, password_hash, role) VALUES (?, ?, ?)",
        ("CLIENT_B", _legacy_hash("clientpass"), "client"),
    )
    conn.execute(
        "INSERT INTO admin_users (username, password_hash, role) VALUES (?, ?, ?)",
        ("CLIENT_C", _legacy_hash("clientpass"), "client"),
    )
    conn.execute(
        "INSERT INTO admin_users (username, password_hash, role) VALUES (?, ?, ?)",
        ("admin", _legacy_hash("adminpass"), "admin"),
    )
    conn.execute("""
        INSERT INTO clients (
            telegram_chat_id, account_balance, subscription_expiry,
            subscription_tier, is_active, dashboard_access
        )
        VALUES (?, ?, ?, ?, ?, ?)
    """, ("CLIENT_A", 1000.0, active_expiry, "PRO", 1, 1))
    conn.execute("""
        INSERT INTO clients (
            telegram_chat_id, account_balance, subscription_expiry,
            subscription_tier, is_active, dashboard_access
        )
        VALUES (?, ?, ?, ?, ?, ?)
    """, ("CLIENT_B", 1000.0, expired, "PRO", 1, 1))
    conn.execute("""
        INSERT INTO clients (
            telegram_chat_id, account_balance, subscription_expiry,
            subscription_tier, is_active, dashboard_access
        )
        VALUES (?, ?, ?, ?, ?, ?)
    """, ("CLIENT_C", 1000.0, active_expiry, "PRO", 1, 1))
    conn.execute("""
        INSERT INTO client_signal_entitlements (
            telegram_chat_id, signal_id, signal_uid, delivery_status,
            delivery_channel, tier_at_delivery, created_at, delivered_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, ("CLIENT_A", 1, "sig-1", "SENT", "telegram", "PRO", datetime.utcnow().isoformat(), datetime.utcnow().isoformat()))
    conn.commit()
    conn.close()

    conn = sqlite3.connect(signals_db)
    conn.execute("""
        CREATE TABLE signals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT,
            symbol TEXT,
            direction TEXT,
            entry_price REAL,
            sl REAL,
            tp1 REAL,
            tp2 REAL,
            reasoning TEXT,
            timeframe TEXT,
            confidence REAL,
            status TEXT,
            result TEXT,
            outcome TEXT,
            closed_at TEXT,
            result_pips REAL,
            forensic_events TEXT,
            score_details TEXT
        )
    """)
    conn.execute("""
        INSERT INTO signals (
            timestamp, symbol, direction, entry_price, sl, tp1, tp2,
            reasoning, timeframe, confidence, status, result, outcome, result_pips,
            forensic_events, score_details
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        datetime.utcnow().isoformat(),
        "XAUUSD",
        "BUY",
        2330.5,
        2320.0,
        2340.0,
        2350.0,
        "Momentum is aligned with buyer pressure.",
        "M15",
        8.1,
        "OPEN",
        None,
        None,
        None,
        "[{\"internal\": true}]",
        "{\"debug\": true}",
    ))
    conn.commit()
    conn.close()

    return clients_db, signals_db


def _token(client: TestClient, username: str, password: str = "clientpass") -> dict:
    response = client.post("/api/token", data={"username": username, "password": password})
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def test_active_client_can_read_simplified_signal_feed(portal_dbs):
    clients_db, signals_db = portal_dbs
    with patch("admin_server.DB_CLIENTS", clients_db), patch("admin_server.DB_SIGNALS", signals_db):
        client = TestClient(app)
        headers = _token(client, "CLIENT_A")

        response = client.get("/api/client/signals", headers=headers)

    assert response.status_code == 200
    body = response.json()
    assert body["subscription"]["state"] == "active"
    assert body["signals"][0]["symbol"] == "XAUUSD"
    assert body["signals"][0]["take_profits"] == [2340.0, 2350.0]
    assert "forensic_events" not in body["signals"][0]
    assert "score_details" not in body["signals"][0]


def test_expired_client_gets_subscription_state_without_signal_leakage(portal_dbs):
    clients_db, signals_db = portal_dbs
    with patch("admin_server.DB_CLIENTS", clients_db), patch("admin_server.DB_SIGNALS", signals_db):
        client = TestClient(app)
        headers = _token(client, "CLIENT_B")

        list_response = client.get("/api/client/signals", headers=headers)
        detail_response = client.get("/api/client/signals/1", headers=headers)

    assert list_response.status_code == 200
    assert list_response.json()["signals"] == []
    assert list_response.json()["subscription"]["state"] == "expired"
    assert detail_response.status_code == 403
    assert detail_response.json()["detail"]["code"] == "subscription_required"


def test_active_client_cannot_read_unentitled_signal(portal_dbs):
    clients_db, signals_db = portal_dbs
    with patch("admin_server.DB_CLIENTS", clients_db), patch("admin_server.DB_SIGNALS", signals_db):
        client = TestClient(app)
        headers = _token(client, "CLIENT_C")

        list_response = client.get("/api/client/signals", headers=headers)
        detail_response = client.get("/api/client/signals/1", headers=headers)

    assert list_response.status_code == 200
    assert list_response.json()["subscription"]["state"] == "active"
    assert list_response.json()["signals"] == []
    assert detail_response.status_code == 404


def test_client_role_cannot_call_admin_endpoints(portal_dbs):
    clients_db, signals_db = portal_dbs
    with patch("admin_server.DB_CLIENTS", clients_db), patch("admin_server.DB_SIGNALS", signals_db):
        client = TestClient(app)
        headers = _token(client, "CLIENT_A")

        response = client.get("/api/clients", headers=headers)

    assert response.status_code == 403


def test_client_preferences_are_scoped_to_authenticated_client(portal_dbs):
    clients_db, signals_db = portal_dbs
    with patch("admin_server.DB_CLIENTS", clients_db), patch("admin_server.DB_SIGNALS", signals_db):
        client = TestClient(app)
        headers = _token(client, "CLIENT_A")

        response = client.post(
            "/api/client/preferences",
            json={"telegram_enabled": True, "timezone": "Africa/Nairobi"},
            headers=headers,
        )

    assert response.status_code == 200
    assert response.json()["preferences"]["telegram_enabled"] is True

    conn = sqlite3.connect(clients_db)
    saved = conn.execute(
        "SELECT telegram_chat_id, preferences_json FROM client_preferences"
    ).fetchall()
    conn.close()
    assert len(saved) == 1
    assert saved[0][0] == "CLIENT_A"
