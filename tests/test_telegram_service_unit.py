import pytest
import sqlite3
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch, AsyncMock
from config.manager import config_manager
from alerts.service import TelegramService

@pytest.fixture(autouse=True)
def reset_config_overrides():
    config_manager.clear_runtime_overrides()
    yield
    config_manager.clear_runtime_overrides()

@pytest.fixture
def telegram_service():
    config_manager.set_runtime_override("telegram_bot_token", "fake_token")
    config_manager.set_runtime_override("telegram_chat_id", "fake_id")
    service = TelegramService()
    service.bot = AsyncMock()
    return service

@pytest.mark.asyncio
async def test_send_signal_success(telegram_service):
    telegram_service.bot.send_message.return_value = MagicMock()
    success = await telegram_service.send_signal("Test Message")
    assert success is True
    assert telegram_service.bot.send_message.called

@pytest.mark.asyncio
async def test_send_signal_failure(telegram_service):
    telegram_service.bot.send_message.side_effect = Exception("API Error")
    success = await telegram_service.send_signal("Test Message")
    assert success is False

@pytest.mark.asyncio
async def test_broadcast_personalized_signal_single_mode(telegram_service):
    config_manager.set_runtime_override("multi_client_mode", False)
    await telegram_service.broadcast_personalized_signal({'symbol': 'BTC', 'direction': 'BUY'})
    assert telegram_service.bot.send_message.called

@pytest.mark.asyncio
async def test_format_signal_assets(telegram_service):
    # Test JPY
    jpy_sig = {'symbol': 'USDJPY', 'entry_price': 150.0, 'sl': 149.0, 'tp0': 151.0}
    msg_jpy = telegram_service.format_signal(jpy_sig)
    assert msg_jpy is not None
    
    # Test XAU/BTC (pip_divisor=10)
    xau_sig = {'symbol': 'XAUUSD', 'entry_price': 2000.0, 'sl': 1990.0, 'tp0': 2010.0}
    msg_xau = telegram_service.format_signal(xau_sig)
    assert msg_xau is not None
    
    # Test fallback
    plain_sig = {'symbol': 'EURUSD', 'entry_price': 1.1000, 'sl': 1.0900, 'tp0': 1.1100}
    msg_plain = telegram_service.format_signal(plain_sig)
    assert msg_plain is not None

@pytest.mark.asyncio
async def test_send_text_failure(telegram_service):
    telegram_service.bot.send_message.side_effect = Exception("Text Fail")
    success = await telegram_service.send_text("Hello")
    assert success is False

@pytest.mark.asyncio
async def test_broadcast_personalized_signal_skipped_logic(telegram_service):
    config_manager.set_runtime_override("multi_client_mode", True)
    with patch('core.client_manager.ClientManager') as MockManager:
        mock_manager_instance = MockManager.return_value
        # One client active, one inactive
        mock_manager_instance.get_all_active_clients.return_value = [
            {'telegram_chat_id': 'active', 'account_balance': 1000.0, 'risk_percent': 2.0},
            {'telegram_chat_id': 'inactive', 'account_balance': 500.0, 'risk_percent': 2.0}
        ]
        mock_manager_instance.is_subscription_active.side_effect = [True, False]

        await telegram_service.broadcast_personalized_signal({
            'symbol': 'BTC', 'direction': 'BUY', 'entry_price': 60000, 'sl': 59000,
            'tp0': 61000, 'tp1': 62000, 'tp2': 63000, 'timeframe': 'H1',
            'trade_type': 'CRT', 'quality_score': 0.8, 'expected_hold': '4h'
        })
        assert telegram_service.bot.send_message.call_count == 1


@pytest.mark.asyncio
async def test_broadcast_records_client_signal_entitlement(telegram_service, tmp_path):
    clients_db = str(tmp_path / "clients.db")
    config_manager.set_runtime_override("multi_client_mode", True)
    config_manager.set_runtime_override("db_clients", clients_db)

    conn = sqlite3.connect(clients_db)
    conn.execute("""
        CREATE TABLE clients (
            client_id INTEGER PRIMARY KEY AUTOINCREMENT,
            telegram_chat_id TEXT UNIQUE NOT NULL,
            account_balance REAL NOT NULL,
            risk_percent REAL DEFAULT 2.0,
            max_concurrent_trades INTEGER DEFAULT 4,
            subscription_expiry TIMESTAMP,
            subscription_tier TEXT DEFAULT 'BASIC',
            is_active BOOLEAN DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            dashboard_access BOOLEAN DEFAULT 1
        )
    """)
    conn.execute("""
        INSERT INTO clients (
            telegram_chat_id, account_balance, risk_percent,
            subscription_expiry, subscription_tier, is_active
        )
        VALUES (?, ?, ?, ?, ?, ?)
    """, (
        "active-client",
        1000.0,
        2.0,
        (datetime.utcnow() + timedelta(days=7)).strftime("%Y-%m-%d %H:%M:%S"),
        "PRO",
        1,
    ))
    conn.commit()
    conn.close()

    with patch.object(telegram_service, "send_text", new=AsyncMock(return_value=True)):
        await telegram_service.broadcast_personalized_signal({
            "id": 42,
            "signal_uid": "signal-42",
            "symbol": "BTC",
            "direction": "BUY",
            "entry_price": 60000,
            "sl": 59000,
            "tp0": 61000,
            "tp1": 62000,
            "tp2": 63000,
            "timeframe": "H1",
            "trade_type": "CRT",
            "quality_score": 8.0,
            "expected_hold": "4h",
        })

    conn = sqlite3.connect(clients_db)
    row = conn.execute("""
        SELECT telegram_chat_id, signal_id, delivery_status, delivered_at
        FROM client_signal_entitlements
    """).fetchone()
    conn.close()

    assert row == ("active-client", 42, "SENT", row[3])
    assert row[3] is not None
