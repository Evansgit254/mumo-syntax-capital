import pandas as pd
import numpy as np
import sqlite3
import asyncio
import os
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Any
from config.config import SYMBOLS, DB_SIGNALS, DB_CLIENTS
from indicators.calculations import IndicatorCalculator
from core.execution_gate import ExecutionGate

class BacktestEngine:
    """
    Institutional-grade Backtest Simulation Engine.
    Engineered for high-fidelity signal verification and data integrity.
    """
    
    def __init__(self, start_date: str, end_date: str, symbols: List[str] = SYMBOLS):
        self.start_date = start_date
        self.end_date = end_date
        self.symbols = symbols
        self.results_db = os.path.abspath("database/backtest_results.db")
        self._run_conn: Optional[sqlite3.Connection] = None
        self._initialize_database()
        
    def _initialize_database(self) -> None:
        """Ensures schema integrity for simulation results."""
        os.makedirs(os.path.dirname(self.results_db), exist_ok=True)
        with sqlite3.connect(self.results_db) as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS backtest_runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_name TEXT,
                    start_date TEXT,
                    end_date TEXT,
                    total_trades INTEGER,
                    win_rate REAL,
                    net_pips REAL,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
                );
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
                );
                CREATE TABLE IF NOT EXISTS trade_reservations (
                    symbol TEXT PRIMARY KEY,
                    direction TEXT,
                    signal_uid TEXT,
                    status TEXT DEFAULT 'ACTIVE',
                    created_at TEXT,
                    updated_at TEXT
                );
            """)
            # Cleanup past aborted runs (ghost trades/reservations that pollute new runs)
            conn.execute("UPDATE backtest_signals SET result = 'CLOSED', closed_at = timestamp WHERE result = 'OPEN' AND (closed_at IS NULL OR closed_at = '')")
            conn.execute("DELETE FROM trade_reservations")
            conn.commit()

    async def run(self, progress_callback: Optional[Any] = None) -> Dict[str, Any]:
        """
        Executes a high-fidelity simulation across multiple timeframes.
        """
        self._emit_progress(progress_callback, 0.01, "Initializing data load")
        all_data = await self._fetch_all_symbol_data(progress_callback)
        if not all_data:
            return {"error": "Insufficient data available for this range."}

        # Initialize the active institutional baseline only.
        from strategies.crt_strategy import CRTStrategy
        from strategies.advanced_pattern_strategy import AdvancedPatternStrategy

        strategies = [
            CRTStrategy(),
            AdvancedPatternStrategy(),
        ]
        
        performance = {"total_pips": 0.0, "wins": 0, "signals": []}
        self._run_conn = sqlite3.connect(self.results_db, timeout=30)
        self._run_conn.execute("PRAGMA journal_mode=WAL")
        self._run_conn.execute("PRAGMA busy_timeout=30000")
        try:
            run_id = self._create_run_header()
            
            # Build the master simulation timeline
            timeline = self._build_simulation_timeline(all_data)
            print(f"\n🚀 Simulation Active: {len(timeline)} cycles across {len(strategies)} strategies.")
            if not timeline:
                return {"error": "No simulation timestamps available for this range."}
            self._emit_progress(progress_callback, 0.20, f"Simulating {len(timeline):,} market bars")

            for i, ts in enumerate(timeline):
                if progress_callback and i % 100 == 0:
                    pct = 0.20 + (i / len(timeline) * 0.78)
                    self._emit_progress(progress_callback, pct, f"Simulating bar {i + 1:,}/{len(timeline):,}")
                    await asyncio.sleep(0)

                for symbol, tfs in all_data.items():
                    if ts not in tfs['entry'].index:
                        continue
                    
                    # Snapshot context for this specific bar
                    entry_df = tfs['entry']
                    idx_entry = entry_df.index.get_loc(ts)
                    if idx_entry < 100: continue

                    idx_h1 = tfs['h1'].index.searchsorted(ts, side='right')
                    idx_d1 = tfs['d1'].index.searchsorted(ts, side='right')
                    data_bundle = {
                        'entry': entry_df.iloc[:idx_entry+1],
                        'm5': entry_df.iloc[:idx_entry+1],
                        'h1': tfs['h1'].iloc[:idx_h1],
                        'd1': tfs['d1'].iloc[:idx_d1]
                    }
                    
                    # Add M15 if available for CRT fallback
                    if 'm15' in tfs:
                        idx_m15 = tfs['m15'].index.searchsorted(ts, side='right')
                        data_bundle['m15'] = tfs['m15'].iloc[:idx_m15]

                    for strategy in strategies:
                        signal = await strategy.analyze(symbol, data_bundle, [], {})
                        if not signal:
                            continue

                        # Inject current volatility context for ExecutionGate
                        if 'atr' in entry_df.columns and 'atr_avg' in entry_df.columns:
                            signal['current_atr'] = entry_df['atr'].iloc[idx_entry]
                            signal['avg_atr'] = entry_df['atr_avg'].iloc[idx_entry]
                        else:
                            signal['current_atr'] = 1.0
                            signal['avg_atr'] = 1.0

                        signal['run_id'] = run_id

                        # Execute Gate Validation
                        gate = ExecutionGate.validate(
                            signal, self.results_db, DB_CLIENTS, 
                            table_name='backtest_signals', current_ts=ts
                        )

                        trade_record = self._create_trade_record(run_id, strategy, symbol, ts, signal, gate)
                        
                        if gate['status'] == 'PASSED':
                            outcome = self._simulate_exit(entry_df.iloc[idx_entry+1:], signal)
                            trade_record.update({
                                'result': outcome['result'],
                                'result_pips': outcome['pips'],
                                'closed_at': outcome['closed_at']
                            })
                            if outcome['result'] == 'TP1': performance['wins'] += 1
                            performance['total_pips'] += outcome['pips']

                        performance['signals'].append(trade_record)
                        self._persist_signal(trade_record)
                
                await asyncio.sleep(0)

            self._emit_progress(progress_callback, 0.99, "Finalizing run metrics")
            self._finalize_run(run_id, performance)
            resolved = [s for s in performance['signals'] if s['result'] in ('TP1', 'SL')]
            self._emit_progress(progress_callback, 1.0, "Backtest complete")
            return {
                "run_id": run_id,
                "total_trades": len(resolved),
                "win_rate": (performance['wins'] / len(resolved) * 100) if resolved else 0,
                "net_pips": performance['total_pips']
            }
        finally:
            if self._run_conn is not None:
                self._run_conn.close()
                self._run_conn = None

    def _emit_progress(self, progress_callback: Optional[Any], progress: float, message: str) -> None:
        """Reports progress with a message while preserving legacy one-argument callbacks."""
        if not progress_callback:
            return
        progress = max(0.0, min(float(progress), 1.0))
        try:
            progress_callback(progress, message)
        except TypeError:
            progress_callback(progress)

    def _create_trade_record(self, run_id: int, strategy: Any, symbol: str, ts: datetime, signal: Dict, gate: Dict) -> Dict:
        return {
            'run_id': run_id,
            'strategy_name': strategy.get_name(),
            'symbol': symbol,
            'direction': signal['direction'],
            'entry_price': signal['entry_price'],
            'sl': signal['sl'],
            'tp1': signal['tp1'],
            'result': 'BLOCKED' if gate['status'] == 'BLOCKED' else 'OPEN',
            'result_pips': 0.0,
            'gate_status': gate['status'],
            'gate_reason': gate['reason'],
            'regime': signal.get('regime', 'UNKNOWN'),
            'quality_score': signal.get('quality_score', 0.0),
            'timestamp': ts.isoformat(),
            'closed_at': ts.isoformat() if gate['status'] == 'BLOCKED' else None
        }

    def _simulate_exit(self, future_df: pd.DataFrame, signal: Dict) -> Dict:
        """
        Models exit conditions with realistic execution friction (Spread + Slippage).
        Binary TP1/SL model — measures the core CRT mean-reversion edge.
        """
        from config.config import SPREAD_PIPS, SLIPPAGE_PIPS
        if future_df.empty:
            return {'result': 'OPEN', 'pips': 0, 'closed_at': None}

        # Conversion Logic (V5.3.0 Standard)
        is_jpy = "JPY" in signal.get('symbol', '')
        is_crypto = any(coin in signal.get('symbol', '') for coin in ["BTC", "ETH", "SOL", "BNB"])
        
        if is_jpy:
            pip_value = 0.01
        elif is_crypto:
            pip_value = 1.0
        else:
            pip_value = 0.0001
        
        # Total execution friction in price points
        total_friction = (SPREAD_PIPS + SLIPPAGE_PIPS) * pip_value

        entry, sl, tp = float(signal['entry_price']), float(signal['sl']), float(signal['tp1'])
        direction = signal['direction'].upper()
        
        # Original risk for R-multiple calculation
        risk = abs(entry - sl)
        if risk <= 0: return {'result': 'ERROR', 'pips': 0, 'closed_at': None}

        for ts, row in future_df.iterrows():
            high, low = row['high'], row['low']
            
            if direction == 'BUY':
                # BUY SL is bid-based. Slippage effectively moves SL "closer" to entry in bid terms.
                # BUY TP is ask-based. Spread makes TP "farther" from current bid.
                if low <= (sl + total_friction): 
                    return {'result': 'SL', 'pips': -1.0, 'closed_at': ts.isoformat()}
                if high >= (tp + total_friction): 
                    net_tp_win = abs(tp - entry) - total_friction
                    return {'result': 'TP1', 'pips': net_tp_win / risk, 'closed_at': ts.isoformat()}
            else:
                # SELL SL is ask-based. Spread moves SL "closer" to entry in ask terms.
                # SELL TP is bid-based. Slippage makes TP "farther" from current bid.
                if high >= (sl - total_friction): 
                    return {'result': 'SL', 'pips': -1.0, 'closed_at': ts.isoformat()}
                if low <= (tp - total_friction): 
                    net_tp_win = abs(entry - tp) - total_friction
                    return {'result': 'TP1', 'pips': net_tp_win / risk, 'closed_at': ts.isoformat()}
                
        return {'result': 'OPEN', 'pips': 0, 'closed_at': None}

    def _build_simulation_timeline(self, data: Dict) -> List[datetime]:
        """Aggregates all timestamps for unified master timeline."""
        ts_set = set()
        for sym in data.values():
            filtered = sym['entry'].index[(sym['entry'].index >= self.start_date) & (sym['entry'].index <= self.end_date)]
            ts_set.update(filtered)
        return sorted(list(ts_set))

    async def _fetch_all_symbol_data(self, progress_callback: Optional[Any] = None) -> Dict[str, Dict[str, pd.DataFrame]]:
        """Handles MTF data loading with fallback logic."""
        from data.fetcher import DataFetcher
        from data.deep_fetcher import DeepDataFetcher
        processed = {}
        
        # Define ranges (padded for indicator warmup)
        start_dt = datetime.strptime(self.start_date, '%Y-%m-%d')
        h1_start = (start_dt - timedelta(days=30)).strftime('%Y-%m-%d')
        # Removed the 59-day hard clamp to allow deep history fetching
        m5_start = (start_dt - timedelta(days=5)).strftime('%Y-%m-%d')
        d1_start = (start_dt - timedelta(days=730)).strftime('%Y-%m-%d')
        fetch_end = (datetime.strptime(self.end_date, '%Y-%m-%d') + timedelta(days=2)).strftime('%Y-%m-%d')

        is_deep_history = (datetime.now() - datetime.strptime(m5_start, '%Y-%m-%d')).days > 58

        import time as _time
        total_symbols = len(self.symbols)
        for idx, symbol in enumerate(self.symbols, 1):
            try:
                sym_start = _time.time()
                print(f"\n📡 [{idx}/{total_symbols}] Loading {symbol}...")
                symbol_base = 0.02 + ((idx - 1) / max(total_symbols, 1) * 0.18)
                symbol_step = 0.18 / max(total_symbols, 1)
                self._emit_progress(progress_callback, symbol_base, f"Loading {symbol} ({idx}/{total_symbols})")

                if is_deep_history:
                    print(f"   ├─ M5 (Dukascopy local)...", end="", flush=True)
                    self._emit_progress(progress_callback, symbol_base + symbol_step * 0.15, f"Loading {symbol} M5 Dukascopy data")
                    m5 = await DeepDataFetcher.fetch_range_async(symbol, "5m", m5_start, fetch_end)
                    print(f" {len(m5) if m5 is not None else 0:,} bars")
                    print(f"   ├─ M15 (Dukascopy local)...", end="", flush=True)
                    self._emit_progress(progress_callback, symbol_base + symbol_step * 0.30, f"Loading {symbol} M15 Dukascopy data")
                    m15 = await DeepDataFetcher.fetch_range_async(symbol, "15m", m5_start, fetch_end)
                    print(f" {len(m15) if m15 is not None else 0:,} bars")
                else:
                    print(f"   ├─ M5 (yfinance)...", end="", flush=True)
                    self._emit_progress(progress_callback, symbol_base + symbol_step * 0.15, f"Loading {symbol} M5 market data")
                    m5 = await DataFetcher.fetch_range_async(symbol, "5m", m5_start, fetch_end)
                    print(f" {len(m5) if m5 is not None else 0:,} bars")
                    print(f"   ├─ M15 (yfinance)...", end="", flush=True)
                    self._emit_progress(progress_callback, symbol_base + symbol_step * 0.30, f"Loading {symbol} M15 market data")
                    m15 = await DataFetcher.fetch_range_async(symbol, "15m", m5_start, fetch_end)
                    print(f" {len(m15) if m15 is not None else 0:,} bars")
                    
                if is_deep_history:
                    print(f"   ├─ H1 (Dukascopy local)...", end="", flush=True)
                    self._emit_progress(progress_callback, symbol_base + symbol_step * 0.45, f"Loading {symbol} H1 Dukascopy data")
                    h1 = await DeepDataFetcher.fetch_range_async(symbol, "1h", h1_start, fetch_end)
                else:
                    print(f"   ├─ H1 (yfinance)...", end="", flush=True)
                    self._emit_progress(progress_callback, symbol_base + symbol_step * 0.45, f"Loading {symbol} H1 market data")
                    h1 = await DataFetcher.fetch_range_async(symbol, "1h", h1_start, fetch_end)
                print(f" {len(h1) if h1 is not None else 0:,} bars")
                if is_deep_history:
                    print(f"   ├─ D1 (Dukascopy local)...", end="", flush=True)
                    self._emit_progress(progress_callback, symbol_base + symbol_step * 0.60, f"Loading {symbol} D1 Dukascopy data")
                    d1 = await DeepDataFetcher.fetch_range_async(symbol, "1d", d1_start, fetch_end)
                else:
                    print(f"   ├─ D1 (yfinance)...", end="", flush=True)
                    self._emit_progress(progress_callback, symbol_base + symbol_step * 0.60, f"Loading {symbol} D1 market data")
                    d1 = await DataFetcher.fetch_range_async(symbol, "1d", d1_start, fetch_end)
                print(f" {len(d1) if d1 is not None else 0:,} bars")
                
                if h1 is None or d1 is None or h1.empty or d1.empty:
                    print(f"   └─ ⚠️  Skipped (missing H1/D1 data)")
                    continue

                if m5 is None or m5.empty:
                    print(f"   └─ ⚠️  Skipped (M5 data missing — drop CSVs into data/dukascopy/)")
                    continue

                # Strict M5 enforce
                entry_df = m5 
                entry_tf = "5m"

                print(f"   ├─ Computing indicators...", end="", flush=True)
                self._emit_progress(progress_callback, symbol_base + symbol_step * 0.80, f"Computing {symbol} indicators")
                processed[symbol] = {
                    'entry': IndicatorCalculator.add_indicators(entry_df, entry_tf),
                    'h1': IndicatorCalculator.add_indicators(h1, "1h"),
                    'd1': IndicatorCalculator.add_indicators(d1, "1d")
                }
                if m15 is not None and not m15.empty:
                    processed[symbol]['m15'] = IndicatorCalculator.add_indicators(m15, "15m")
                elapsed = _time.time() - sym_start
                print(f" done ({elapsed:.1f}s)")
                print(f"   └─ ✅ {symbol} ready")
                self._emit_progress(progress_callback, symbol_base + symbol_step, f"{symbol} ready")

            except Exception as e:
                import traceback
                print(f"   └─ ❌ Data Fetch Error [{symbol}]: {str(e)}")
                # traceback.print_exc()
        print(f"\n📊 Data loaded for {len(processed)}/{total_symbols} symbols. Starting simulation...\n")
        return processed

    def _create_run_header(self) -> int:
        if self._run_conn is not None:
            cursor = self._run_conn.execute("INSERT INTO backtest_runs (run_name, start_date, end_date) VALUES (?,?,?)",
                                            ("Institutional Audit", self.start_date, self.end_date))
            self._run_conn.commit()
            return cursor.lastrowid
        with sqlite3.connect(self.results_db) as conn:
            return conn.execute("INSERT INTO backtest_runs (run_name, start_date, end_date) VALUES (?,?,?)",
                                ("Institutional Audit", self.start_date, self.end_date)).lastrowid

    def _persist_signal(self, t: Dict) -> None:
        conn = self._run_conn
        if conn is not None:
            conn.execute("""
                INSERT INTO backtest_signals (
                    run_id, strategy_name, symbol, direction, entry_price, sl, tp1, 
                    result, result_pips, gate_status, gate_reason, regime, quality_score, timestamp, closed_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, (t['run_id'], t['strategy_name'], t['symbol'], t['direction'], t['entry_price'], 
                  t['sl'], t['tp1'], t['result'], t['result_pips'], t['gate_status'], 
                  t['gate_reason'], t['regime'], t['quality_score'], t['timestamp'], t['closed_at']))
            conn.commit()
            return
        with sqlite3.connect(self.results_db) as conn:
            conn.execute("""
                INSERT INTO backtest_signals (
                    run_id, strategy_name, symbol, direction, entry_price, sl, tp1, 
                    result, result_pips, gate_status, gate_reason, regime, quality_score, timestamp, closed_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, (t['run_id'], t['strategy_name'], t['symbol'], t['direction'], t['entry_price'], 
                  t['sl'], t['tp1'], t['result'], t['result_pips'], t['gate_status'], 
                  t['gate_reason'], t['regime'], t['quality_score'], t['timestamp'], t['closed_at']))

    def _finalize_run(self, run_id: int, perf: Dict) -> None:
        # Only count resolved trades (TP1/SL) — excludes OPEN/CLOSED/ERROR which skew stats
        resolved = [s for s in perf['signals'] if s['result'] in ('TP1', 'SL')]
        wr = (perf['wins'] / len(resolved) * 100) if resolved else 0
        if self._run_conn is not None:
            self._run_conn.execute("UPDATE backtest_runs SET total_trades = ?, win_rate = ?, net_pips = ? WHERE id = ?",
                                   (len(resolved), wr, perf['total_pips'], run_id))
            self._run_conn.commit()
            return
        with sqlite3.connect(self.results_db) as conn:
            conn.execute("UPDATE backtest_runs SET total_trades = ?, win_rate = ?, net_pips = ? WHERE id = ?",
                        (len(resolved), wr, perf['total_pips'], run_id))
