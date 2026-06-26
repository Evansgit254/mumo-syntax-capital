import pytest
import asyncio
import sqlite3
from unittest.mock import patch, MagicMock, AsyncMock
from config.manager import config_manager
from core.trade_executor import TradeExecutor
from core.db_utils import ensure_base_tables

@pytest.fixture(autouse=True)
def reset_config_overrides():
    config_manager.clear_runtime_overrides()
    yield
    config_manager.clear_runtime_overrides()

@pytest.fixture
def executor():
    config_manager.set_runtime_override("mt5_auto_trade", True)
    config_manager.set_runtime_override("mt5_paper_mode", True)
    ex = TradeExecutor()
    return ex

@pytest.fixture
def temp_signals_db(tmp_path):
    db_path = tmp_path / "signals.db"
    conn = sqlite3.connect(db_path)
    ensure_base_tables(conn)
    conn.execute("""
        CREATE TABLE signals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            signal_uid TEXT,
            symbol TEXT,
            direction TEXT,
            entry_price REAL,
            sl REAL,
            tp1 REAL,
            trade_type TEXT,
            timestamp TEXT,
            status TEXT,
            result TEXT,
            execution_status TEXT,
            broker_order_id TEXT,
            broker_position_id TEXT,
            requested_price REAL,
            requested_lot_size REAL,
            fill_price REAL,
            filled_lot_size REAL,
            slippage_pips REAL,
            execution_error TEXT,
            score_details TEXT DEFAULT '{}',
            closed_at TEXT
        )
    """)
    conn.commit()
    conn.close()
    config_manager.set_runtime_override("db_signals", str(db_path))
    return db_path

@pytest.mark.asyncio
async def test_paper_trade_execution(executor):
    signal = {
        "symbol": "EURUSD=X",
        "direction": "BUY",
        "entry_price": 1.0550,
        "lot_size": 0.05,
        "sl": 1.0500,
        "tp1": 1.0600,
        "timestamp": "2026-04-20T12:00:00Z"
    }
    
    config_manager.set_runtime_override("mt5_symbol_suffix", "c")
    with patch("core.trade_executor._executor", executor):
        result = await executor.execute_trade(signal)

        assert result["status"] == "PAPER_EXECUTED"
        assert result["symbol"] == "EURUSDc"  # Testing the suffix addition
        assert result["direction"] == "BUY"

@pytest.mark.asyncio
async def test_auto_trade_disabled(executor):
    config_manager.set_runtime_override("mt5_auto_trade", False)
    
    signal = {"symbol": "EURUSD=X"}
    result = await executor.execute_trade(signal)
    
    assert result["status"] == "skipped"
    assert "MT5_AUTO_TRADE=false" in result["reason"]

@pytest.mark.asyncio
async def test_missing_entry_price_blocks_execution(executor):
    signal = {
        "symbol": "EURUSD=X",
        "direction": "BUY",
        "lot_size": 0.05,
        "sl": 1.0500,
        "tp1": 1.0600,
    }

    with patch.object(executor, "_persist_execution_state") as mock_persist:
        result = await executor.execute_trade(signal)

    assert result["status"] == "error"
    assert "entry_price" in result["reason"]
    mock_persist.assert_called_once()

@pytest.mark.asyncio
async def test_live_execution_requires_approval_and_terminal_creds(temp_signals_db):
    config_manager.set_runtime_override("mt5_auto_trade", True)
    config_manager.set_runtime_override("mt5_paper_mode", False)
    config_manager.set_runtime_override("live_trading_approved", False)
    config_manager.set_runtime_override("data_provider", "yfinance")
    config_manager.set_runtime_override("mt5_login", 12345)
    config_manager.set_runtime_override("mt5_password", "pass")
    config_manager.set_runtime_override("mt5_server", "server")
    executor = TradeExecutor()

    result = await executor.execute_trade({
        "symbol": "EURUSD=X",
        "direction": "BUY",
        "entry_price": 1.0550,
        "lot_size": 0.05,
        "sl": 1.0500,
        "tp1": 1.0600,
        "timestamp": "2026-04-20T12:00:00Z",
    })

    assert result["status"] == "blocked"
    assert "live_trading_approved=false" in result["reason"]


@pytest.mark.asyncio
async def test_paper_positions_do_not_connect_to_mt5(temp_signals_db):
    config_manager.set_runtime_override("mt5_paper_mode", True)
    config_manager.set_runtime_override("mt5_auto_trade", False)

    with sqlite3.connect(temp_signals_db) as conn:
        conn.execute("""
            INSERT INTO signals (
                id, signal_uid, symbol, direction, entry_price, sl, tp1,
                timestamp, execution_status, status, filled_lot_size
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            99,
            "paper-99",
            "XAUUSD",
            "BUY",
            2330.5,
            2320.0,
            2340.0,
            "2026-06-25T10:00:00",
            "PAPER_EXECUTED",
            "PAPER_EXECUTED",
            0.1,
        ))
        conn.commit()

    executor = TradeExecutor()
    with patch.object(executor._direct_engine, "connect", side_effect=AssertionError("MT5 should not be touched")):
        positions = await executor.get_open_positions()

    assert positions == [{
        "id": 99,
        "ticket": 99,
        "signal_uid": "paper-99",
        "symbol": "XAUUSD",
        "direction": "BUY",
        "lot_size": 0.1,
        "open_price": 2330.5,
        "current_price": 2330.5,
        "profit": 0.0,
        "sl": 2320.0,
        "tp": 2340.0,
        "open_time": "2026-06-25T10:00:00",
        "mode": "PAPER",
    }]
