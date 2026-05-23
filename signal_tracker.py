#!/usr/bin/env python3
"""
Signal Tracker Service for TradingExpert.
Watches open signals and updates their result (TP/SL) based on real-time price data.
"""
import asyncio
import sqlite3
import yfinance as yf
from datetime import datetime
import os
import signal
import sys

DB_PATH = "database/signals.db"
TRACKING_INTERVAL = 120  # Check every 2 minutes

def calculate_pips(symbol, entry, exit, direction):
    """V31.0: Precise institutional pip calculation."""
    try:
        # Check if JPY pair
        multiplier = 100 if "JPY" in symbol else 10000
        # Check if Gold/Oil/Crypto (usually 2-digits or 1-digit)
        if any(x in symbol for x in ["XAU", "GOLD", "GC=F", "XAG"]): multiplier = 10 
        if any(x in symbol for x in ["BTC", "ETH"]): multiplier = 1
        
        diff = (exit - entry) if direction == 'BUY' else (entry - exit)
        return round(diff * multiplier, 1)
    except:
        return 0.0

class SignalTracker:
    def __init__(self):
        self.running = True
        signal.signal(signal.SIGINT, self._shutdown)
        signal.signal(signal.SIGTERM, self._shutdown)

    def _shutdown(self, signum, frame):
        print("\n⏹️  Shutdown signal received. Stopping tracker...")
        self.running = False

    def get_db_connection(self):
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    async def track_once(self):
        """Perform one tracking cycle for all open signals."""
        conn = None
        try:
            conn = self.get_db_connection()
            # Find all open signals
            open_signals = conn.execute("SELECT * FROM signals WHERE result = 'OPEN'").fetchall()
            
            if not open_signals:
                return

            # Group by symbol to minimize API calls
            symbols = list(set([s['symbol'] for s in open_signals]))
            
            # Fetch latest prices for all symbols in the list
            # Note: yf.download is faster for batches but can be noisy
            prices = {}
            for symbol in symbols:
                try:
                    ticker = yf.Ticker(symbol)
                    # Get 2 bars of 1m data to ensure we have the most recent closed/current price
                    hist = ticker.history(period="1d", interval="1m")
                    if not hist.empty:
                        prices[symbol] = hist['Close'].iloc[-1]
                except Exception as e:
                    print(f"⚠️ Error fetching price for {symbol}: {e}")

            for sig in open_signals:
                symbol = sig['symbol']
                if symbol not in prices:
                    continue

                current_price = prices[symbol]
                direction = sig['direction']
                entry = sig['entry_price']
                sl = sig['sl']
                tp0 = sig['tp0'] # TP1 (Secure)
                tp1 = sig['tp1'] # TP2 (Growth)
                tp2 = sig['tp2'] # TP3 (Runner)
                max_tp = sig['max_tp_reached'] or 0
                
                new_result = 'OPEN'
                new_max_tp = max_tp
                closed_at = None
                new_sl = sl

                if direction == 'BUY':
                    if current_price <= sl:
                        if max_tp >= 1 and sl >= entry:
                            # It was secured at breakeven, so it's a win (partial)
                            new_result = f'TP{max_tp}'
                        else:
                            new_result = 'SL'
                        closed_at = datetime.now().isoformat()
                    elif current_price >= tp2:
                        new_result = 'TP3'
                        new_max_tp = 3
                        closed_at = datetime.now().isoformat()
                    elif current_price >= tp1:
                        new_max_tp = max(new_max_tp, 2)
                        new_sl = max(sl, entry) # V25.0 Secure at TP1
                    elif current_price >= tp0:
                        new_max_tp = max(new_max_tp, 1)
                        new_sl = max(sl, entry) # V25.0 Secure at TP1
                else: # SELL
                    if current_price >= sl:
                        if max_tp >= 1 and sl <= entry:
                            # It was secured at breakeven, so it's a win (partial)
                            new_result = f'TP{max_tp}'
                        else:
                            new_result = 'SL'
                        closed_at = datetime.now().isoformat()
                    elif current_price <= tp2:
                        new_result = 'TP3'
                        new_max_tp = 3
                        closed_at = datetime.now().isoformat()
                    elif current_price <= tp1:
                        new_max_tp = max(new_max_tp, 2)
                        new_sl = min(sl, entry) # V25.0 Secure at TP1
                    elif current_price <= tp0:
                        new_max_tp = max(new_max_tp, 1)
                        new_sl = min(sl, entry) # V25.0 Secure at TP1

                if new_result != 'OPEN' or new_max_tp != max_tp or new_sl != sl:
                    if new_result != 'OPEN':
                        status_str = new_result
                    else:
                        status_str = f"OPEN (Hit TP{new_max_tp}, SL moved to {new_sl:.5f})"

                    # V31.0: Settlement Logic (Pips & Paper Account)
                    pips = 0.0
                    if new_result != 'OPEN':
                        pips = calculate_pips(symbol, entry, current_price, direction)
                        
                    print(f"🎯 UPDATING {symbol} {direction}: {status_str} at {current_price:.5f} ({pips} pips)")
                    
                    conn.execute("""
                        UPDATE signals 
                        SET result = ?, max_tp_reached = ?, closed_at = ?, sl = ?, result_pips = ?
                        WHERE id = ?
                    """, (new_result, new_max_tp, closed_at, new_sl, pips, sig['id']))
                    
                    # If this was a paper trade closure, update paper balance
                    if new_result != 'OPEN' and sig.get('gate_status') == 'PASSED':
                        # Mapping pips to dollars (Simplified: $10 per pip for a standard lot)
                        import json
                        lot_size = 0.1 # Default mini-lot
                        try:
                            rd = json.loads(sig['risk_details'])
                            lot_size = rd.get('lot_size', 0.1)
                        except: pass
                        
                        dollar_gain = pips * (lot_size * 10)
                        conn.execute("UPDATE paper_account SET balance = balance + ?, equity = equity + ? WHERE id = 1", (dollar_gain, dollar_gain))
                        
                    conn.commit()

        except Exception as e:
            print(f"❌ Tracker cycle error: {e}")
        finally:
            if conn:
                conn.close()

    async def run(self):
        print("="*60)
        print("📊 SIGNAL TRACKER SERVICE STARTED")
        print("="*60)
        print(f"📡 Interval: {TRACKING_INTERVAL} seconds")
        print(f"🗄️ Database: {DB_PATH}")
        print("="*60)
        
        while self.running:
            start_time = datetime.now()
            await self.track_once()
            
            # Wait for next interval
            elapsed = (datetime.now() - start_time).total_seconds()
            sleep_time = max(1, TRACKING_INTERVAL - elapsed)
            await asyncio.sleep(sleep_time)

if __name__ == "__main__":
    tracker = SignalTracker()
    asyncio.run(tracker.run())
