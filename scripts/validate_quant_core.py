#!/usr/bin/env python3
"""
QuantCore Validation Script (V35.1r)
=====================================
Runs QuantCoreStrategy in isolation against the last 30 days.
Only integrate into live engine if WR > 50% and avg_win > 1.2R.

Usage:
    python scripts/validate_quant_core.py [--days 30]
"""
import asyncio
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from config.config import SYMBOLS
from data.fetcher import DataFetcher
from indicators.calculations import IndicatorCalculator
from strategies.quant_core_strategy import QuantCoreStrategy

async def validate_quant_core(days: int = 30):
    print(f"🔬 QUANT CORE VALIDATION (Last {days} days)")
    print("=" * 70)
    
    fetcher = DataFetcher()
    strategy = QuantCoreStrategy()
    
    start_date = (datetime.now() - timedelta(days=days + 15)).strftime("%Y-%m-%d")
    end_date = datetime.now().strftime("%Y-%m-%d")
    
    all_data = {}
    for symbol in SYMBOLS:
        print(f"  Fetching {symbol}...")
        m5_df = fetcher.fetch_range(symbol, "5m", start_date, end_date)
        h1_df = fetcher.fetch_range(symbol, "1h", start_date, end_date)
        
        if m5_df is None or m5_df.empty or h1_df is None or h1_df.empty:
            continue
            
        all_data[symbol] = {
            'm5': IndicatorCalculator.add_indicators(m5_df, "5m"),
            'h1': IndicatorCalculator.add_indicators(h1_df, "1h")
        }
    
    if not all_data:
        print("❌ No data loaded.")
        return
    
    trades = []
    
    for symbol, data in all_data.items():
        print(f"  Testing {symbol}...")
        m5_df = data['m5']
        
        for i in range(200, len(m5_df) - 1):
            ts = m5_df.index[i]
            m5_state = m5_df.iloc[:i+1]
            
            data_bundle = {'m5': m5_state, 'h1': data['h1']}
            
            signal = await strategy.analyze(symbol, data_bundle, [], {})
            
            if signal:
                entry = signal['entry_price']
                sl = signal['sl']
                tp = signal['tp0']
                sl_dist = abs(entry - sl)
                if sl_dist == 0:
                    continue
                
                # Simulate outcome
                hit = None
                pnl_r = 0.0
                lookahead = 200  # ~16 hours of M5 bars
                for j in range(i + 1, min(i + lookahead, len(m5_df))):
                    fut = m5_df.iloc[j]
                    if signal['direction'] == "BUY":
                        if fut['low'] <= sl:
                            hit = "LOSS"; pnl_r = -1.0; break
                        if fut['high'] >= tp:
                            hit = "WIN"; pnl_r = (tp - entry) / sl_dist; break
                    else:
                        if fut['high'] >= sl:
                            hit = "LOSS"; pnl_r = -1.0; break
                        if fut['low'] <= tp:
                            hit = "WIN"; pnl_r = (entry - tp) / sl_dist; break
                
                if hit:
                    trades.append({
                        'ts': ts, 'symbol': symbol,
                        'direction': signal['direction'],
                        'res': hit, 'r': pnl_r
                    })
    
    if not trades:
        print("\n⚠️  No trades generated. QuantCore may need factor tuning.")
        return
    
    df = pd.DataFrame(trades)
    total = len(df)
    wins = (df['res'] == 'WIN').sum()
    losses = (df['res'] == 'LOSS').sum()
    wr = wins / total * 100
    total_r = df['r'].sum()
    avg_win = df[df['r'] > 0]['r'].mean() if wins > 0 else 0
    avg_loss = df[df['r'] < 0]['r'].mean() if losses > 0 else 0
    
    print("\n" + "=" * 70)
    print(f"📊 QUANT CORE VALIDATION RESULTS")
    print("=" * 70)
    print(f"  Total Trades:  {total}")
    print(f"  Win Rate:      {wr:.1f}%")
    print(f"  Net R:         {total_r:.2f}R")
    print(f"  Avg Win:       {avg_win:.3f}R")
    print(f"  Avg Loss:      {avg_loss:.3f}R")
    print("=" * 70)
    
    # Per-symbol breakdown
    print(f"\n{'SYMBOL':<12} | {'N':>5} | {'WR':>7} | {'NET R':>8}")
    print("-" * 40)
    for sym in df['symbol'].unique():
        sub = df[df['symbol'] == sym]
        sym_wr = (sub['res'] == 'WIN').mean() * 100
        print(f"{sym:<12} | {len(sub):>5} | {sym_wr:>6.1f}% | {sub['r'].sum():>7.2f}R")
    
    # Verdict
    print("\n" + "=" * 70)
    if wr > 50 and avg_win > 1.2:
        print("✅ VERDICT: PASS — QuantCore is ready for live integration.")
    elif wr > 45:
        print("⚠️  VERDICT: MARGINAL — Consider further tuning before live deployment.")
    else:
        print("🔴 VERDICT: FAIL — Do NOT integrate. WR too low for profitability.")
    print("=" * 70)

if __name__ == "__main__":
    d = 30
    if len(sys.argv) > 1:
        for arg in sys.argv[1:]:
            if arg.startswith("--days"):
                d = int(sys.argv[sys.argv.index(arg) + 1])
    asyncio.run(validate_quant_core(d))
