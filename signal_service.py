#!/usr/bin/env python3
"""
Continuous Signal Service for Pure Quant Trading System.
Runs every 5 minutes, generates signals, and sends to Telegram.

Usage:
    python signal_service.py              # Normal mode
    python signal_service.py --test       # Test mode (one cycle)
"""
import asyncio
import signal
import sys
import hashlib
from datetime import datetime, timedelta
from typing import Set, Tuple

from app.generate_signals import generate_signals
from alerts.service import TelegramService
from core.signal_formatter import SignalFormatter
from core.market_regime import detect_regime, apply_regime_filter

# Configuration
SIGNAL_INTERVAL = 300  # 5 minutes in seconds
DEDUP_WINDOW_HOURS = 0.75  # Don't resend same signal within 45 mins (User request: 30m-1h)
MAX_RETRIES = 3
RETRY_DELAY = 30  # seconds


class SignalService:
    """Continuous signal generation and Telegram delivery service."""
    
    def __init__(self):
        self.telegram = TelegramService()
        self.sent_signals: dict[str, datetime] = {}  # hash -> timestamp
        self.running = True
        self.is_paused = False
        self.cycle_count = 0
        
        # Set up signal handlers for graceful shutdown
        signal.signal(signal.SIGINT, self._shutdown)
        signal.signal(signal.SIGTERM, self._shutdown)
    
    def _shutdown(self, signum, frame):
        """Handle shutdown signals gracefully."""
        print(f"\n⏹️  Shutdown signal received. Completing current cycle...")
        self.running = False
    
    def _signal_hash(self, signal_data: dict) -> str:
        """
        Generate unique hash for a signal to detect duplicates.
        Strict: Only based on Symbol, Direction, and Timeframe to prevent price-bounce flooding.
        """
        key_parts = [
            signal_data.get('symbol', ''),
            signal_data.get('direction', ''),
            signal_data.get('timeframe', '')
        ]
        return hashlib.md5('|'.join(key_parts).encode()).hexdigest()[:12]
    
    def _cleanup_old_signals(self):
        """Remove signals older than DEDUP_WINDOW from tracking."""
        cutoff = datetime.now() - timedelta(hours=DEDUP_WINDOW_HOURS)
        self.sent_signals = {
            h: ts for h, ts in self.sent_signals.items() 
            if ts > cutoff
        }
    
    def _is_duplicate(self, signal_data: dict) -> bool:
        """Check if signal was already sent recently."""
        sig_hash = self._signal_hash(signal_data)
        return sig_hash in self.sent_signals
    
    def _mark_sent(self, signal_data: dict):
        """Mark signal as sent to prevent duplicates."""
        sig_hash = self._signal_hash(signal_data)
        self.sent_signals[sig_hash] = datetime.now()

    def _load_dynamic_config(self):
        """Load configuration overrides from database"""
        import sqlite3
        import config.config as cfg
        from config.config import DB_CLIENTS
        
        # Mapping for keys that don't match config variable names exactly
        key_mapping = {
            "risk_per_trade": "RISK_PER_TRADE_PERCENT",
            "news_filter_minutes": "NEWS_WASH_ZONE"
        }
        
        try:
            conn = sqlite3.connect(DB_CLIENTS)
            conn.row_factory = sqlite3.Row
            rows = conn.execute("SELECT key, value, type FROM system_config").fetchall()
            conn.close()
            
            print("⚙️  Loading dynamic configuration...")
            for row in rows:
                key = row['key']
                val = row['value']
                
                # Type conversion
                if row['type'] == 'int': val = int(val)
                elif row['type'] == 'float': val = float(val)
                elif row['type'] == 'bool': val = (val.lower() == 'true')
                
                # Determine target variable name
                target_var = key_mapping.get(key, key.upper())
                
                # Apply to config module if exists
                if hasattr(cfg, target_var):
                    setattr(cfg, target_var, val)
                    print(f"   🔹 {target_var} = {val}")
                
                # Special handling for system status
                if key == 'system_status':
                    self.is_paused = (val != 'ACTIVE')
                        
        except Exception as e:
            print(f"⚠️  Failed to load dynamic config: {e}")
    
    async def run_cycle(self) -> Tuple[int, int]:
        """
        Run one signal generation cycle.
        Returns: (total_signals, sent_count)
        """
        self.cycle_count += 1
        print(f"\n{'='*60}")
        print(f"🔄 CYCLE #{self.cycle_count} - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"{'='*60}")

        # V23.2: Dynamic Market Regime Detection (before config load)
        try:
            from data.fetcher import DataFetcher
            from indicators.calculations import IndicatorCalculator
            from config.config import SYMBOLS, DB_CLIENTS
            import asyncio as _aio
            fetcher = DataFetcher()
            h1_map = {}
            # Sample first 4 symbols for speed (representative)
            for sym in list(SYMBOLS)[:4]:
                try:
                    raw = await fetcher.fetch_data_async(sym, "1h", period="30d")
                    if raw is not None and not raw.empty:
                        h1_map[sym] = IndicatorCalculator.add_indicators(raw, "1h")
                except Exception:
                    pass
            regime_result = detect_regime(h1_map)
            apply_regime_filter(regime_result, DB_CLIENTS)
        except Exception as e:
            print(f"⚠️  Regime detection skipped: {e}")

        # V19.0: Dynamic Configuration Loading (after regime sets threshold)
        self._load_dynamic_config()
        
        if self.is_paused:
            print("⏸️  System is PAUSED via Server Config. Skipping cycle.")
            return 0, 0
            
        # Cleanup old tracked signals
        self._cleanup_old_signals()
        
        # Generate signals
        try:
            signals = await generate_signals()
        except Exception as e:
            print(f"❌ Error generating signals: {e}")
            return 0, 0
        
        if not signals:
            print("📭 No signals generated this cycle.")
            return 0, 0
        
        # Send to Telegram (with deduplication)
        sent_count = 0
        skipped = 0
        
        for signal_type, signal_data in signals:
            # Check for duplicates
            if self._is_duplicate(signal_data):
                skipped += 1
                print(f"⏭️  Skipped duplicate: {signal_data.get('symbol')} {signal_data.get('direction')}")
                continue
            
            # Format and broadcast (V11.0 Personalized Multi-Client)
            try:
                # V17.4: Generate reasoning once for consistency
                from core.signal_formatter import SignalFormatter
                if 'reasoning' not in signal_data:
                    signal_data['reasoning'] = SignalFormatter.generate_reasoning(signal_data)
                
                # V31.0: Execution Gate — validate before any action
                from core.execution_gate import ExecutionGate
                from config.config import DB_SIGNALS, DB_CLIENTS
                gate_result = ExecutionGate.validate(signal_data, DB_SIGNALS, DB_CLIENTS)
                signal_data['gate_status'] = gate_result['status']
                signal_data['gate_reason'] = gate_result['reason']
                
                gate_tag = "🟢 PASSED" if gate_result['status'] == 'PASSED' else f"🔴 BLOCKED ({gate_result['reason']})"
                print(f"  ⛩️  Gate: {signal_data.get('symbol')} → {gate_tag}")

                # V17.2: Log to database FIRST for dashboard reliability
                self._log_to_database(signal_data)
                self._mark_sent(signal_data)
                
                # Broadcast after logging
                await self.telegram.broadcast_personalized_signal(signal_data)

                # V31.0: Only execute trades that PASS the gate
                if gate_result['status'] == 'PASSED':
                    from config.config import MT5_AUTO_TRADE
                    if MT5_AUTO_TRADE:
                        try:
                            from core.trade_executor import get_executor
                            executor = get_executor()
                            trade_result = await executor.execute_trade(signal_data)
                            mode_tag = "📝 PAPER" if trade_result.get("status") == "paper" else "✅ LIVE"
                            print(f"  {mode_tag} Trade: {signal_data.get('direction')} {signal_data.get('symbol')} → {trade_result.get('status')}")
                        except Exception as te:
                            print(f"  ⚠️  Trade execution error: {te}")

                sent_count += 1

                
                # Small delay to avoid API flood
                await asyncio.sleep(1)
                
            except Exception as e:
                print(f"❌ Error during signal processing/delivery: {e}")
        
        print(f"\n📊 Cycle summary: {sent_count} sent, {skipped} duplicates skipped")
        return len(signals), sent_count
    
    def _log_to_database(self, signal_data: dict):
        """Log signal to database for dashboard display."""
        import sqlite3
        import os
        from datetime import datetime
        
        db_path = "database/signals.db"
        
        # V18.1: Self-Healing Schema - Ensure all columns exist before insert
        conn = None
        try:
            conn = sqlite3.connect(db_path)
            conn.execute("PRAGMA journal_mode=WAL")  # Enable WAL mode for concurrency
            cursor = conn.cursor()
            required_cols = [
                ("trade_type", "TEXT DEFAULT 'SCALP'"),
                ("quality_score", "REAL DEFAULT 0.0"),
                ("regime", "TEXT DEFAULT 'UNKNOWN'"),
                ("expected_hold", "TEXT DEFAULT 'UNKNOWN'"),
                ("risk_details", "TEXT DEFAULT '{}'"),
                ("score_details", "TEXT DEFAULT '{}'"),
                ("result", "TEXT DEFAULT 'OPEN'"),
                ("closed_at", "TIMESTAMP"),
                ("max_tp_reached", "INTEGER DEFAULT 0")
            ]
            for col_name, col_def in required_cols:
                try:
                    cursor.execute(f"ALTER TABLE signals ADD COLUMN {col_name} {col_def}")
                except sqlite3.OperationalError:
                    pass
            conn.commit()
        except Exception as e:
            print(f"⚠️  Schema check failed: {e}")
        finally:
            if conn:
                conn.close()
            
        conn = None
        try:
            conn = sqlite3.connect(db_path)
            conn.execute("PRAGMA journal_mode=WAL")
            
            # V18.0: Full Signal Fidelity - Store all metadata
            import json
            
            # V18.2: Robustly sanitize data for JSON serialization (handles booleans and numpy)
            def sanitize_for_json(data):
                if isinstance(data, dict):
                    return {str(k): sanitize_for_json(v) for k, v in data.items()}
                elif isinstance(data, (list, tuple, set)):
                    return [sanitize_for_json(item) for item in data]
                elif isinstance(data, bool):
                    return int(data)
                elif isinstance(data, (int, float, str)) or data is None:
                    return data
                elif hasattr(data, 'item') and callable(getattr(data, 'item', None)):
                    # Handle numpy scalars like np.bool_, np.float64, etc.
                    try:
                        return sanitize_for_json(data.item())
                    except:
                        return str(data)
                return str(data)
            
            risk_json = json.dumps(sanitize_for_json(signal_data.get('risk_details', {})))
            score_json = json.dumps(sanitize_for_json(signal_data.get('score_details', {})))
            
            conn.execute("""
                INSERT INTO signals (
                    timestamp, symbol, direction, entry_price, 
                    sl, tp0, tp1, tp2, reasoning, timeframe, confidence,
                    trade_type, quality_score, regime, expected_hold, risk_details, score_details,
                    forensic_candles, forensic_events, gate_status, gate_reason
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                datetime.now().isoformat(),
                signal_data.get('symbol', 'UNKNOWN'),
                signal_data.get('direction', 'UNKNOWN'),
                signal_data.get('entry_price', 0.0),
                signal_data.get('sl', 0.0),
                signal_data.get('tp0', 0.0),
                signal_data.get('tp1', 0.0),
                signal_data.get('tp2', 0.0),
                signal_data.get('reasoning', '')[:5000],
                signal_data.get('timeframe', 'M5'),
                signal_data.get('confidence', 0.0),
                signal_data.get('trade_type', 'INSTITUTIONAL'),
                signal_data.get('quality_score', 0.0),
                signal_data.get('regime', 'UNKNOWN'),
                signal_data.get('expected_hold', 'UNKNOWN'),
                risk_json,
                score_json,
                json.dumps(sanitize_for_json(signal_data.get('forensic_candles', []))),
                json.dumps(sanitize_for_json(signal_data.get('forensic_events', []))),
                signal_data.get('gate_status', 'UNKNOWN'),
                signal_data.get('gate_reason', 'UNKNOWN')
            ))
            conn.commit()
        except Exception as e:
            print(f"⚠️  Failed to log signal to database: {e}")
        finally:
            if conn:
                conn.close()

    
    async def run(self, test_mode: bool = False):
        """
        Main service loop. Runs continuously until shutdown.
        
        Args:
            test_mode: If True, run only one cycle then exit
        """
        print("="*60)
        print("🚀 PURE QUANT SIGNAL SERVICE STARTED")
        print("="*60)
        print(f"📡 Interval: {SIGNAL_INTERVAL} seconds")
        print(f"🔄 Dedup window: {DEDUP_WINDOW_HOURS} hours")
        print(f"📱 Telegram: {'Configured' if self.telegram.bot else 'NOT CONFIGURED'}")
        print("="*60)
        
        if not self.telegram.bot:
            print("⚠️  WARNING: Telegram not configured. Signals will be generated but not broadcast.")
        
        while self.running:
            try:
                # Run signal cycle
                total, sent = await self.run_cycle()
                
                # Test mode: exit after one cycle
                if test_mode:
                    print("\n✅ Test cycle complete. Exiting.")
                    break
                
                # Calculate wait time (align to next 5-min mark if possible)
                now = datetime.now()
                next_run = now + timedelta(seconds=SIGNAL_INTERVAL)
                # Align to 5-minute candle close
                next_run = next_run.replace(second=15, microsecond=0)  # 15 sec after candle close
                wait_seconds = max(60, (next_run - now).total_seconds())
                
                print(f"\n⏳ Next cycle at {next_run.strftime('%H:%M:%S')} (waiting {int(wait_seconds)}s)")
                
                # Wait with graceful shutdown check
                for _ in range(int(wait_seconds)):
                    if not self.running:
                        break
                    await asyncio.sleep(1)
                    
            except Exception as e:
                print(f"❌ Cycle error: {e}")
                if not test_mode:
                    print(f"⏳ Retrying in {RETRY_DELAY} seconds...")
                    await asyncio.sleep(RETRY_DELAY)
                else:
                    break
        
        print("\n👋 Signal service stopped gracefully.")


async def main():
    test_mode = '--test' in sys.argv
    service = SignalService()
    await service.run(test_mode=test_mode)


if __name__ == "__main__":
    asyncio.run(main())
