import pytest
import sqlite3
import os
from unittest.mock import patch, MagicMock
from datetime import datetime
from signal_tracker import SignalTracker

DB_TEST = "database/signals_tracker_test.db"

@pytest.fixture
def mock_db(tmp_path):
    db_test = str(tmp_path / "signals_test.db")
    conn = sqlite3.connect(db_test)
    conn.execute("""
        CREATE TABLE signals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TIMESTAMP,
            symbol TEXT,
            direction TEXT,
            entry_price REAL,
            sl REAL,
            tp0 REAL,
            tp1 REAL,
            tp2 REAL,
            result TEXT DEFAULT 'OPEN',
            max_tp_reached INTEGER DEFAULT 0,
            closed_at TIMESTAMP,
            result_pips REAL DEFAULT 0.0,
            gate_status TEXT DEFAULT 'PASSED',
            risk_details TEXT DEFAULT '{}',
            status TEXT DEFAULT 'OPEN',
            result_price REAL,
            outcome TEXT
        )
    """)
    
    # Sample BUY signal
    conn.execute("""
        INSERT INTO signals (symbol, direction, entry_price, sl, tp0, tp1, tp2, result, max_tp_reached)
        VALUES ('EURUSD=X', 'BUY', 1.1000, 1.0900, 1.1050, 1.1100, 1.1200, 'OPEN', 0)
    """)
    
    # Sample SELL signal
    conn.execute("""
        INSERT INTO signals (symbol, direction, entry_price, sl, tp0, tp1, tp2, result, max_tp_reached)
        VALUES ('GBPUSD=X', 'SELL', 1.3000, 1.3100, 1.2950, 1.2900, 1.2800, 'OPEN', 0)
    """)
    
    conn.execute("""
        CREATE TABLE IF NOT EXISTS paper_account (
            id INTEGER PRIMARY KEY DEFAULT 1,
            balance REAL DEFAULT 100000.0,
            equity REAL DEFAULT 100000.0,
            last_daily_reset_date TEXT
        )
    """)
    conn.execute("INSERT OR IGNORE INTO paper_account (id, balance, equity) VALUES (1, 100000.0, 100000.0)")
    conn.commit()
    conn.close()
    return db_test

@pytest.mark.asyncio
async def test_track_once_buy_sl(mock_db):
    tracker = SignalTracker()
    with patch('signal_tracker.DB_PATH', mock_db):
        # Mock yfinance to return price at SL
        with patch('yfinance.Ticker') as mock_ticker:
            import pandas as pd
            # Create a real DataFrame to ensure iloc and indexing work perfectly
            mock_data = pd.DataFrame({'Close': [1.0850]}, index=[datetime.now()])
            mock_ticker.return_value.history.return_value = mock_data
            
            await tracker.track_once()
            
            # Verify update in DB
            conn = sqlite3.connect(mock_db)
            conn.row_factory = sqlite3.Row
            sig = conn.execute("SELECT * FROM signals WHERE symbol = 'EURUSD=X'").fetchone()
            assert sig['result'] == 'SL'
            assert sig['closed_at'] is not None
            conn.close()

@pytest.mark.asyncio
async def test_track_once_buy_tp3(mock_db):
    tracker = SignalTracker()
    with patch('signal_tracker.DB_PATH', mock_db):
        with patch('yfinance.Ticker') as mock_ticker:
            import pandas as pd
            mock_data = pd.DataFrame({'Close': [1.1250]}, index=[datetime.now()])
            mock_ticker.return_value.history.return_value = mock_data
            
            await tracker.track_once()
            
            conn = sqlite3.connect(mock_db)
            conn.row_factory = sqlite3.Row
            sig = conn.execute("SELECT * FROM signals WHERE symbol = 'EURUSD=X'").fetchone()
            assert sig['result'] == 'TP3'
            assert sig['max_tp_reached'] == 3
            assert sig['closed_at'] is not None
            conn.close()

@pytest.mark.asyncio
async def test_track_once_buy_tp1_hold(mock_db):
    tracker = SignalTracker()
    with patch('signal_tracker.DB_PATH', mock_db):
        with patch('yfinance.Ticker') as mock_ticker:
            import pandas as pd
            mock_data = pd.DataFrame({'Close': [1.1070]}, index=[datetime.now()])
            mock_ticker.return_value.history.return_value = mock_data
            
            await tracker.track_once()
            
            conn = sqlite3.connect(mock_db)
            conn.row_factory = sqlite3.Row
            sig = conn.execute("SELECT * FROM signals WHERE symbol = 'EURUSD=X'").fetchone()
            assert sig['result'] == 'OPEN'
            assert sig['max_tp_reached'] == 1
            conn.close()

@pytest.mark.asyncio
async def test_track_once_sell_tp2(mock_db):
    tracker = SignalTracker()
    with patch('signal_tracker.DB_PATH', mock_db):
        with patch('yfinance.Ticker') as mock_ticker:
            import pandas as pd
            mock_data = pd.DataFrame({'Close': [1.2850]}, index=[datetime.now()])
            mock_ticker.return_value.history.return_value = mock_data
            
            await tracker.track_once()
            
            conn = sqlite3.connect(mock_db)
            conn.row_factory = sqlite3.Row
            sig = conn.execute("SELECT * FROM signals WHERE symbol = 'GBPUSD=X'").fetchone()
            assert sig['result'] == 'OPEN'
            assert sig['max_tp_reached'] == 2
            conn.close()

@pytest.mark.asyncio
async def test_track_once_buy_tp2_hold(mock_db):
    tracker = SignalTracker()
    with patch('signal_tracker.DB_PATH', mock_db):
        with patch('yfinance.Ticker') as mock_ticker:
            mock_hist = MagicMock()
            import pandas as pd
            mock_hist.empty = False
            mock_hist.__getitem__.return_value = pd.Series([1.1150], index=[datetime.now()]) # Above TP2 but below TP3
            mock_ticker.return_value.history.return_value = mock_hist
            
            await tracker.track_once()
            
            conn = sqlite3.connect(mock_db)
            conn.row_factory = sqlite3.Row
            sig = conn.execute("SELECT * FROM signals WHERE symbol = 'EURUSD=X'").fetchone()
            assert sig['result'] == 'OPEN'
            assert sig['max_tp_reached'] == 2
            conn.close()

@pytest.mark.asyncio
async def test_track_once_sell_sl(mock_db):
    tracker = SignalTracker()
    with patch('signal_tracker.DB_PATH', mock_db):
        with patch('yfinance.Ticker') as mock_ticker:
            import pandas as pd
            mock_data = pd.DataFrame({'Close': [1.3150]}, index=[datetime.now()])
            mock_ticker.return_value.history.return_value = mock_data
            
            await tracker.track_once()
            
            conn = sqlite3.connect(mock_db)
            conn.row_factory = sqlite3.Row
            sig = conn.execute("SELECT * FROM signals WHERE symbol = 'GBPUSD=X'").fetchone()
            assert sig['result'] == 'SL'
            assert sig['closed_at'] is not None
            conn.close()

@pytest.mark.asyncio
async def test_track_once_sell_tp1_hold(mock_db):
    tracker = SignalTracker()
    with patch('signal_tracker.DB_PATH', mock_db):
        with patch('yfinance.Ticker') as mock_ticker:
            import pandas as pd
            mock_data = pd.DataFrame({'Close': [1.2930]}, index=[datetime.now()])
            mock_ticker.return_value.history.return_value = mock_data
            
            await tracker.track_once()
            
            conn = sqlite3.connect(mock_db)
            conn.row_factory = sqlite3.Row
            sig = conn.execute("SELECT * FROM signals WHERE symbol = 'GBPUSD=X'").fetchone()
            assert sig['result'] == 'OPEN'
            assert sig['max_tp_reached'] == 1
            conn.close()

@pytest.mark.asyncio
async def test_track_once_price_fetch_error(mock_db):
    tracker = SignalTracker()
    with patch('signal_tracker.DB_PATH', mock_db):
        with patch('yfinance.Ticker') as mock_ticker:
            mock_ticker.return_value.history.side_effect = Exception("API Error")
            await tracker.track_once()
            # Just verify it doesn't crash and result remains OPEN
            conn = sqlite3.connect(mock_db)
            conn.row_factory = sqlite3.Row
            sig = conn.execute("SELECT * FROM signals WHERE symbol = 'EURUSD=X'").fetchone()
            assert sig['result'] == 'OPEN'
            conn.close()

@pytest.mark.asyncio
async def test_track_once_symbol_missing_in_prices(mock_db):
    tracker = SignalTracker()
    with patch('signal_tracker.DB_PATH', mock_db):
        with patch('yfinance.Ticker') as mock_ticker:
            mock_hist = MagicMock()
            mock_hist.empty = True # Simulates missing price
            mock_ticker.return_value.history.return_value = mock_hist
            
            await tracker.track_once()
            
            conn = sqlite3.connect(mock_db)
            conn.row_factory = sqlite3.Row
            sig = conn.execute("SELECT * FROM signals WHERE symbol = 'EURUSD=X'").fetchone()
            assert sig['result'] == 'OPEN'
            conn.close()

@pytest.mark.asyncio
async def test_run_loop_test(mock_db):
    tracker = SignalTracker()
    tracker.running = True
    with patch('signal_tracker.DB_PATH', mock_db), \
         patch('signal_tracker.TRACKING_INTERVAL', 0.1), \
         patch.object(tracker, 'track_once', side_effect=lambda: setattr(tracker, 'running', False)):
        # Above side effect stops the loop after first iteration
        await tracker.run()
        assert tracker.running == False

@pytest.mark.asyncio
async def test_track_once_sell_tp3(mock_db):
    tracker = SignalTracker()
    with patch('signal_tracker.DB_PATH', mock_db):
        with patch('yfinance.Ticker') as mock_ticker:
            import pandas as pd
            mock_data = pd.DataFrame({'Close': [1.2750]}, index=[datetime.now()])
            mock_ticker.return_value.history.return_value = mock_data
            
            await tracker.track_once()
            
            conn = sqlite3.connect(mock_db)
            conn.row_factory = sqlite3.Row
            sig = conn.execute("SELECT * FROM signals WHERE symbol = 'GBPUSD=X'").fetchone()
            assert sig['result'] == 'TP3'
            assert sig['max_tp_reached'] == 3
            conn.close()
