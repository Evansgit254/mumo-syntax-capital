import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import sqlite3
import json
import asyncio
from typing import List, Dict, Optional
from config.config import SYMBOLS, DB_SIGNALS, DB_CLIENTS
from indicators.calculations import IndicatorCalculator
from strategies.crt_strategy import CRTStrategy
from core.market_regime import detect_regime
from core.execution_gate import ExecutionGate

class BacktestEngine:
    """
    V32.0: Institutional Backtesting Engine.
    Simulates historical execution using actual candlestick data.
    """
    
    def __init__(self, start_date: str, end_date: str, symbols: List[str] = SYMBOLS):
        self.start_date = start_date
        self.end_date = end_date
        self.symbols = symbols
        self.results_db = "database/backtest_results.db"
        self._ensure_db()
        
    def _ensure_db(self):
        """Create backtest results table."""
        with sqlite3.connect(self.results_db) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS backtest_runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_name TEXT,
                    start_date TEXT,
                    end_date TEXT,
                    total_trades INTEGER,
                    win_rate REAL,
                    net_pips REAL,
                    max_drawdown REAL,
                    sharpe_ratio REAL,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS backtest_signals (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id INTEGER,
                    strategy_name TEXT,
                    symbol TEXT,
                    direction TEXT,
                    entry_price REAL,
                    sl REAL,
                    tp1 REAL,
                    result TEXT,
                    result_pips REAL,
                    gate_status TEXT,
                    gate_reason TEXT,
                    regime TEXT,
                    quality_score REAL,
                    timestamp TEXT,
                    closed_at TEXT
                )
            """)

    async def run(self, progress_callback=None):
        """Run the backtest across all symbols with proper MTF alignment."""
        from data.fetcher import DataFetcher
        fetcher = DataFetcher()
        
        print(f"📥 Loading historical MTF data for {self.symbols}...")
        
        all_data = {}
        for symbol in self.symbols:
            # Fetch all required timeframes
            m5_df = await fetcher.fetch_data_async(symbol, "5m", period="60d")
            h1_df = await fetcher.fetch_data_async(symbol, "1h", period="60d")
            d1_df = await fetcher.fetch_data_async(symbol, "1d", period="2y")
            
            if m5_df is not None and not m5_df.empty:
                # Pre-calculate indicators
                all_data[symbol] = {
                    'm5': IndicatorCalculator.add_indicators(m5_df, "5m"),
                    'h1': IndicatorCalculator.add_indicators(h1_df, "1h"),
                    'd1': IndicatorCalculator.add_indicators(d1_df, "1d")
                }
        
        if not all_data:
            return {"error": "No historical data found"}

        from strategies.smc_liquidity_sweep import SMCLiquiditySweepStrategy
        from strategies.advanced_pattern_strategy import AdvancedPatternStrategy
        from strategies.session_clock_strategy import SessionClockStrategy

        # Initialize strategies
        active_strategies = [
            CRTStrategy(),
            SMCLiquiditySweepStrategy(),
            AdvancedPatternStrategy(),
            SessionClockStrategy()
        ]
        
        run_id = self._start_run_record()
        total_pips = 0
        wins = 0
        trades = []
        
        # Use M5 as the master timeline, filtered by target dates
        common_m5_index = []
        for d in all_data.values():
            filtered_idx = d['m5'].index[(d['m5'].index >= self.start_date) & (d['m5'].index <= self.end_date)]
            common_m5_index.extend(filtered_idx)
        common_m5_index = sorted(list(set(common_m5_index)))
        
        if not common_m5_index:
            return {"error": "No data found for the specified date range"}

        print(f"🚀 Simulating {len(common_m5_index)} M5 cycles across {len(active_strategies)} strategies...")
        
        for i, ts in enumerate(common_m5_index):
            if progress_callback and i % 100 == 0:
                progress_callback(i / len(common_m5_index))
                await asyncio.sleep(0) # Yield to event loop to keep API responsive
            
            for symbol, tfs in all_data.items():
                m5_full = tfs['m5']
                if ts not in m5_full.index: continue
                
                idx_m5 = m5_full.index.get_loc(ts)
                if idx_m5 < 100: continue
                
                # Align timeframes
                h1_full = tfs['h1']
                h1_visible = h1_full[h1_full.index <= ts]
                if len(h1_visible) < 20: continue
                
                d1_full = tfs['d1']
                d1_visible = d1_full[d1_full.index <= ts]
                
                data_bundle = {
                    'm5': m5_full.iloc[max(0, idx_m5-200):idx_m5+1],
                    'h1': h1_visible,
                    'd1': d1_visible
                }
                
                # Run all enabled strategies
                for strategy in active_strategies:
                    signal = await strategy.analyze(symbol, data_bundle, [], {})
                    
                    if signal:
                        # 4. Gate Enforcement (No Pyramiding & Cooling Period)
                        # Don't trade if already in symbol OR if we traded this symbol in last 4 hours
                        last_trade = next((t for t in reversed(trades) if t['symbol'] == symbol), None)
                        if last_trade:
                            if last_trade['result'] == 'OPEN':
                                continue
                            
                            # Cooling period: 4 hours
                            last_ts = datetime.fromisoformat(last_trade['timestamp'])
                            if (ts - last_ts).total_seconds() < 4 * 3600:
                                continue

                        print(f"\n🎯 {strategy.get_name()} SIGNAL: {ts} {symbol} {signal['direction']} @ {signal['entry_price']}")
                        # 5. Outcome Simulation using future M5 data
                        outcome = self._simulate_outcome(m5_full.iloc[idx_m5+1:], signal)
                        
                        trades.append({
                            'run_id': run_id,
                            'strategy_name': strategy.get_name(),
                            'symbol': symbol,
                            'direction': signal['direction'],
                            'entry_price': signal['entry_price'],
                            'sl': signal['sl'],
                            'tp1': signal['tp1'],
                            'result': outcome['result'],
                            'result_pips': outcome['pips'],
                            'gate_status': 'PASSED',
                            'gate_reason': 'BACKTEST',
                            'regime': signal.get('regime', 'UNKNOWN'),
                            'quality_score': signal.get('quality_score', 0),
                            'timestamp': ts.isoformat(),
                            'closed_at': outcome['closed_at']
                        })
                        
                        if outcome['pips'] > 0: wins += 1
                        total_pips += outcome['pips']
            
            await asyncio.sleep(0) # Yield again after symbol loop

        self._save_signals(trades)
        self._finalize_run_record(run_id, len(trades), wins, total_pips)
        
        return {
            "run_id": run_id,
            "total_trades": len(trades),
            "win_rate": (wins / len(trades) * 100) if trades else 0,
            "net_pips": total_pips
        }

    def _simulate_outcome(self, future_df: pd.DataFrame, signal: dict) -> dict:
        """Checks subsequent candles for SL or TP hits with R-multiple reporting."""
        entry = signal['entry_price']
        sl = signal['sl']
        tp = signal['tp1']
        direction = signal['direction']
        symbol = signal['symbol']
        
        # Risk in price units
        risk_price = abs(entry - sl)
        if risk_price == 0: return {'result': 'ERROR', 'pips': 0, 'closed_at': None}

        for ts, row in future_df.iterrows():
            high = row['high']
            low = row['low']
            
            if direction == 'BUY':
                # Check if both hit in the same bar
                if low <= sl and high >= tp:
                    # Tie-breaker: use candle direction or 50/50
                    # For conservative backtesting, we can still favor SL or use a mid-point
                    # but let's use the bar's Close vs Open to guess the path
                    if row['close'] > row['open']: # Bullish bar, likely hit TP first or closed high
                         return {'result': 'TP1', 'pips': abs(tp - entry) / risk_price, 'closed_at': ts.isoformat()}
                    else:
                         return {'result': 'SL', 'pips': -1.0, 'closed_at': ts.isoformat()}
                
                if low <= sl: return {'result': 'SL', 'pips': -1.0, 'closed_at': ts.isoformat()}
                if high >= tp: return {'result': 'TP1', 'pips': abs(tp - entry) / risk_price, 'closed_at': ts.isoformat()}
            else:
                if high >= sl and low <= tp:
                    if row['close'] < row['open']: # Bearish bar
                        return {'result': 'TP1', 'pips': abs(entry - tp) / risk_price, 'closed_at': ts.isoformat()}
                    else:
                        return {'result': 'SL', 'pips': -1.0, 'closed_at': ts.isoformat()}

                if high >= sl: return {'result': 'SL', 'pips': -1.0, 'closed_at': ts.isoformat()}
                if low <= tp: return {'result': 'TP1', 'pips': abs(entry - tp) / risk_price, 'closed_at': ts.isoformat()}
                
        return {'result': 'OPEN', 'pips': 0, 'closed_at': None}

    def _start_run_record(self) -> int:
        with sqlite3.connect(self.results_db) as conn:
            cursor = conn.cursor()
            cursor.execute("INSERT INTO backtest_runs (run_name, start_date, end_date) VALUES (?, ?, ?)",
                         ("Historical Logic Test", self.start_date, self.end_date))
            return cursor.lastrowid

    def _save_signals(self, trades: List[dict]):
        with sqlite3.connect(self.results_db) as conn:
            for t in trades:
                conn.execute("""
                    INSERT INTO backtest_signals (
                        run_id, strategy_name, symbol, direction, entry_price, sl, tp1, 
                        result, result_pips, gate_status, gate_reason, 
                        regime, quality_score, timestamp, closed_at
                    ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """, (
                    t['run_id'], t.get('strategy_name', 'UNKNOWN'), t['symbol'], t['direction'], t['entry_price'], 
                    t['sl'], t['tp1'], t['result'], t['result_pips'], 
                    t['gate_status'], t['gate_reason'], t['regime'], 
                    t['quality_score'], t['timestamp'], t['closed_at']
                ))

    def _finalize_run_record(self, run_id: int, total: int, wins: int, pips: float):
        wr = (wins / total * 100) if total > 0 else 0
        with sqlite3.connect(self.results_db) as conn:
            conn.execute("""
                UPDATE backtest_runs SET
                    total_trades = ?, win_rate = ?, net_pips = ?,
                    max_drawdown = 0.0, sharpe_ratio = 1.0
                WHERE id = ?
            """, (total, wr, pips, run_id))
