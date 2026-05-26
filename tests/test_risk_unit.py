import pytest
import pandas as pd
import sqlite3
import os
from core.filters.risk_manager import RiskManager
from unittest.mock import patch, MagicMock

@pytest.fixture
def mock_db(tmp_path):
    db_path = tmp_path / "test_signals.db"
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE signals (timestamp TEXT, status TEXT, r_multiple REAL)")
    conn.close()
    return str(db_path)

def test_calculate_lot_size_basic():
    # Test EURUSD lot calculation (0.01 lot per $0.10 pip)
    # Account: $50, Risk: 2% ($1.00)
    # SL: 10 pips -> 10 * 0.10 = $1.00 -> 0.01 lot
    res = RiskManager.calculate_lot_size("EURUSD=X", 1.1010, 1.1000, balance=50.0, db_path="non_existent.db")
    assert res['lots'] == 0.01
    assert res['risk_cash'] == 1.0
    assert res['risk_percent'] == 2.0

def test_calculate_lot_size_jpy():
    # USDJPY: 100 multiplier for pips
    res = RiskManager.calculate_lot_size("USDJPY=X", 150.10, 150.00, balance=50.0, db_path="non_existent.db")
    # 0.10 dist = 10 pips. JPY pip val approx 0.065.
    # 1.0 / (0.065 * 10) * 0.01 = 0.0153 -> 0.02
    assert res['lots'] >= 0.01
    assert 'lots' in res

def test_calculate_lot_size_gold_indices():
    # Gold
    res = RiskManager.calculate_lot_size("GC=F", 2005, 2000, balance=200.0, db_path="non_existent.db")
    assert 'lots' in res
    # Nasdaq
    res = RiskManager.calculate_lot_size("IXIC", 15010, 15000, balance=200.0, db_path="non_existent.db")
    assert 'lots' in res

def test_calculate_lot_size_streaks(mock_db):
    # Test Win Streak (multiplier 1.25)
    # Using 1% base risk to leave room for the 1.25 multiplier without hitting the 2% safety cap
    conn = sqlite3.connect(mock_db)
    for i in range(3):
        conn.execute("INSERT INTO signals (timestamp, status) VALUES (?, 'WIN')", (f"2026-01-0{i}",))
    conn.commit()
    conn.close()
    
    # Balance 20,000, Risk 1% = $200. 100 pips = $10 per 0.01 lot. Base = 0.20 lots.
    res_base = RiskManager.calculate_lot_size("EURUSD=X", 1.1000, 1.0900, balance=20000.0, risk_pct_override=1.0, db_path="none.db")
    # Streak 1.25 * $200 = $250. $250 / 10 = 0.25 lots. (0.25 < 400 cap, so it passes)
    res_streak = RiskManager.calculate_lot_size("EURUSD=X", 1.1000, 1.0900, balance=20000.0, risk_pct_override=1.0, db_path=mock_db)
    assert res_streak['lots'] > res_base['lots']
    assert res_streak['lots'] == 0.25

    # Test Loss Streak (multiplier 0.75)
    conn = sqlite3.connect(mock_db)
    conn.execute("DELETE FROM signals")
    for i in range(2):
        conn.execute("INSERT INTO signals (timestamp, status) VALUES (?, 'LOSS')", (f"2026-01-0{i}",))
    conn.commit()
    conn.close()
    
    res_loss = RiskManager.calculate_lot_size("EURUSD=X", 1.1000, 1.0900, balance=20000.0, risk_pct_override=1.0, db_path=mock_db)
    assert res_loss['lots'] < res_base['lots']
    assert res_loss['lots'] == 0.15 # 0.75 * 0.20

def test_calculate_lot_size_exceptions():
    # Test DB error path (invalid SQL)
    res = RiskManager.calculate_lot_size("EURUSD=X", 1.1, 1.0, db_path="/dev/null")
    assert res['lots'] == 0.01 # Should default gracefully

def test_calculate_lot_size_jpy_and_others():
    # JPY
    res = RiskManager.calculate_lot_size("USDJPY=X", 150.01, 150.00, balance=50.0, db_path="none.db")
    assert res['pips'] == 1.0
    # Gold (V10.0 Fix: $1 move = 10 pips)
    res = RiskManager.calculate_lot_size("GC=F", 2001, 2000, balance=50.0, db_path="none.db")
    assert res['pips'] == 10.0

def test_calculate_layers():
    layers = RiskManager.calculate_layers(0.1, 1.1000, 1.0900, "BUY")
    assert len(layers) == 3
    assert layers[0]['lots'] == 0.04 # 40%
    assert layers[1]['lots'] == 0.04
    assert layers[2]['lots'] == 0.02 # 20%
    
    # Sell layers
    layers_sell = RiskManager.calculate_layers(0.1, 1.1000, 1.1100, "SELL")
    assert layers_sell[1]['price'] > 1.1000 # Pullback for sell is higher

def test_calculate_layers_a_plus():
    layers = RiskManager.calculate_layers(0.1, 1.1000, 1.0900, "BUY", quality="A+")
    assert layers[0]['lots'] == 0.05 # 50% for A+
    assert "50%" in layers[0]['label']

def test_calculate_kelly_fraction(mock_db):
    # Insert some WIN/LOSS trades
    conn = sqlite3.connect(mock_db)
    conn.execute("CREATE TABLE IF NOT EXISTS signals (status TEXT, r_multiple REAL, timestamp TEXT)")
    for _ in range(10):
        conn.execute("INSERT INTO signals (status, r_multiple, timestamp) VALUES ('WIN', 2.0, '2026-01-01')")
        conn.execute("INSERT INTO signals (status, r_multiple, timestamp) VALUES ('LOSS', 1.0, '2026-01-02')")
    conn.commit()
    conn.close()
    
    fraction = RiskManager._calculate_kelly_fraction(mock_db)
    assert 0.0 <= fraction <= 0.1 # Capped at 10%
    assert fraction > 0

def test_calculate_optimal_rr():
    # Test boosted R:R for Trending
    res = RiskManager.calculate_optimal_rr("EURUSD=X", 8.5, "TRENDING", 0.0010)
    assert res['tp1_rr'] > 1.5
    assert not res['is_friction_heavy']
    
    # Test reduced R:R for Choppy
    res_choppy = RiskManager.calculate_optimal_rr("EURUSD=X", 5.0, "CHOPPY", 0.0010)
    assert res_choppy['tp1_rr'] <= 1.5
    
    # Test Friction-Heavy detection (Friction > 35% of ATR)
    # Friction = 1.0 pip (0.0001). ATR = 0.0002 -> Friction is 50% of ATR.
    res_friction = RiskManager.calculate_optimal_rr("EURUSD=X", 5.0, "RANGING", 0.0002)
    assert res_friction['is_friction_heavy']
    assert res_friction['tp1_rr'] == 0
