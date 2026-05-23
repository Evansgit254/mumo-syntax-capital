"""
CRT Strategy Forensic Backtest
=================================
Runs the Forensic CRT strategy over historical data.

Usage:
    python -m research.crt_comparison_backtest [days=60]
"""

import asyncio
import sys
import pandas as pd
import numpy as np
import concurrent.futures
from datetime import datetime
from config.config import DXY_SYMBOL, TNX_SYMBOL
from data.fetcher import DataFetcher
from indicators.calculations import IndicatorCalculator
from strategies.crt_strategy import CRTStrategy

# Exclude symbols that hang on Yahoo Finance intraday (BTC-USD, NZDUSD=X sometimes)
BACKTEST_SYMBOLS = ["EURUSD=X", "GBPUSD=X", "USDJPY=X", "GBPJPY=X", "AUDUSD=X", "GC=F", "CL=F"]

FETCH_TIMEOUT = 20  # seconds per symbol before skipping

def _fetch_symbol(sym, tf, period):
    """Blocking fetch — runs in a thread with timeout."""
    return DataFetcher.fetch_data(sym, tf, period=period)

SEPARATOR = "=" * 80
HALF_SEP  = "-" * 80

def simulate_trade(signal, m5_df, m5_i, lookahead=200):
    entry = signal["entry_price"]
    sl    = signal["sl"]
    tp1   = signal["tp0"]   # Equilibrium
    tp2   = signal["tp1"]   # Extreme
    tp3   = signal["tp2"]   # Extension
    sl_dist = abs(entry - sl)
    if sl_dist == 0:
        return None

    direction = signal["direction"]
    hit       = None
    pnl_r     = 0.0
    exit_tp   = None

    for j in range(m5_i + 1, min(m5_i + lookahead, len(m5_df))):
        fut = m5_df.iloc[j]

        if direction == "BUY":
            if fut["low"] <= sl:
                hit = "LOSS"; pnl_r = -1.0; break
            if fut["high"] >= tp3:
                hit = "TP3 (Ext)";  pnl_r = round((tp3 - entry) / sl_dist, 3); exit_tp = "TP3"; break
            if fut["high"] >= tp2:
                hit = "TP2 (Extreme)";  pnl_r = round((tp2 - entry) / sl_dist, 3); exit_tp = "TP2"; break
            if fut["high"] >= tp1:
                hit = "TP1 (Equil)";  pnl_r = round((tp1 - entry) / sl_dist, 3); exit_tp = "TP1"; break
        else:  # SELL
            if fut["high"] >= sl:
                hit = "LOSS"; pnl_r = -1.0; break
            if fut["low"] <= tp3:
                hit = "TP3 (Ext)";  pnl_r = round((entry - tp3) / sl_dist, 3); exit_tp = "TP3"; break
            if fut["low"] <= tp2:
                hit = "TP2 (Extreme)";  pnl_r = round((entry - tp2) / sl_dist, 3); exit_tp = "TP2"; break
            if fut["low"] <= tp1:
                hit = "TP1 (Equil)";  pnl_r = round((entry - tp1) / sl_dist, 3); exit_tp = "TP1"; break

    if hit is None:
        return None

    return {
        "result":    hit,
        "pnl_r":     pnl_r,
        "exit_tp":   exit_tp,
        "direction": direction,
        "win":       hit != "LOSS",
    }


def print_report(mode_label, trades):
    if not trades:
        print(f"\n{mode_label}: No trades resolved.")
        return

    df = pd.DataFrame(trades)
    total      = len(df)
    wins       = df["win"].sum()
    losses     = total - wins
    win_rate   = wins / total * 100
    total_r    = df["pnl_r"].sum()
    avg_r      = df["pnl_r"].mean()
    win_r_sum  = df[df["pnl_r"] > 0]["pnl_r"].sum()
    loss_r_sum = abs(df[df["pnl_r"] < 0]["pnl_r"].sum())
    pf         = win_r_sum / loss_r_sum if loss_r_sum > 0 else float("inf")
    expectancy = (win_rate/100 * avg_r) - ((1 - win_rate/100) * 1.0)

    buy_trades  = df[df["direction"] == "BUY"]
    sell_trades = df[df["direction"] == "SELL"]

    tp_dist = df["exit_tp"].value_counts().to_dict()

    print(f"\n{'─'*40}")
    print(f"  {mode_label}")
    print(f"{'─'*40}")
    print(f"  Total Trades  : {total}")
    print(f"  Wins / Losses : {wins} / {losses}")
    print(f"  Win Rate      : {win_rate:.1f}%")
    print(f"  Total P&L (R) : {total_r:+.2f}R")
    print(f"  Avg R/Trade   : {avg_r:+.3f}R")
    print(f"  Profit Factor : {pf:.2f}")
    print(f"  Expectancy    : {expectancy:+.3f}R")
    print(f"\n  Direction Split:")
    print(f"    BUY  trades : {len(buy_trades)}  (WR: {buy_trades['win'].mean()*100:.1f}%)" if len(buy_trades) > 0 else "    BUY  trades : 0")
    print(f"    SELL trades : {len(sell_trades)}  (WR: {sell_trades['win'].mean()*100:.1f}%)" if len(sell_trades) > 0 else "    SELL trades : 0")
    print(f"\n  Exit Distribution:")
    for label in ["TP1", "TP2", "TP3", "LOSS"]:
        count = tp_dist.get(label, 0)
        if label == "LOSS":
            count = losses
        bar = "█" * int(count / max(total, 1) * 20)
        print(f"    {label:<6}: {count:>4}  {bar}")

    print(f"\n  Per-Symbol Win Rate:")
    for sym, grp in df.groupby("symbol"):
        wr_s = grp["win"].mean() * 100
        print(f"    {sym:<14}: {len(grp):>4} trades  WR={wr_s:.1f}%  Total={grp['pnl_r'].sum():+.2f}R")


async def run_comparison(days=60):
    m5_period = f"{min(days, 58)}d"
    h1_period = f"{days}d"
    d1_period = f"{min(days + 100, 200)}d"   # Extra D1 history for bias calculation

    print(SEPARATOR)
    print(f"  FORENSIC CRT STRATEGY V4  (ICT-Backed, {days} days)")
    print(f"  Run Date: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(SEPARATOR)

    print("\n📥 Loading market data...")
    all_data = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        for symbol in BACKTEST_SYMBOLS:
            print(f"  Fetching {symbol}...", end="", flush=True)
            try:
                fut_m5 = pool.submit(_fetch_symbol, symbol, "5m", m5_period)
                m5_df = fut_m5.result(timeout=FETCH_TIMEOUT)
                fut_h1 = pool.submit(_fetch_symbol, symbol, "1h", h1_period)
                h1_df = fut_h1.result(timeout=FETCH_TIMEOUT)
                fut_d1 = pool.submit(_fetch_symbol, symbol, "1d", d1_period)
                d1_df = fut_d1.result(timeout=FETCH_TIMEOUT)
            except concurrent.futures.TimeoutError:
                print(" ⏱ TIMEOUT (skipped)")
                continue
            if m5_df is None or m5_df.empty or h1_df is None or h1_df.empty:
                print(" ❌ SKIP")
                continue
            d1_ready = d1_df is not None and not d1_df.empty
            d1_processed = IndicatorCalculator.add_indicators(d1_df, "1d") if d1_ready else None
            all_data[symbol] = {
                "m5": IndicatorCalculator.add_indicators(m5_df, "5m"),
                "h1": IndicatorCalculator.add_indicators(h1_df, "1h"),
                # Pass indicator-enriched D1 if possible, else raw price data
                "d1": d1_processed if d1_processed is not None else (d1_df if d1_ready else None),
            }
            d1_bars = len(d1_df) if d1_ready else 0
            print(f" ✅ H1:{len(h1_df)} bars  M5:{len(m5_df)} bars  D1:{d1_bars} bars")

    if not all_data:
        print("❌ No data loaded. Exiting.")
        return

    market_context = {}
    try:
        dxy_df = DataFetcher.fetch_data(DXY_SYMBOL, "1h", period=h1_period)
        if dxy_df is not None and not dxy_df.empty:
            market_context["DXY"] = IndicatorCalculator.add_indicators(dxy_df, "1h")
    except Exception:
        pass

    strat = CRTStrategy()
    trades = []

    print(f"\n⚙️  Running simulation ({len(all_data)} symbols × {days}d H1 bars)...")
    total_symbols = len(all_data)
    for idx, (symbol, data) in enumerate(all_data.items(), 1):
        print(f"  [{idx}/{total_symbols}] {symbol}...", end="", flush=True)
        h1_df = data["h1"]
        m5_df = data["m5"]
        sym_trades = 0

        # H1-based loop — fast: ~1200 iterations per symbol
        # At each H1 bar we pass M5 bars up to that H1 start time.
        # scan_bars = last 24 M5 bars in strategy, which are within H1[-2] window.
        for i in range(200, len(h1_df) - 1):
            ts = h1_df.index[i]
            m5_i = m5_df.index.get_indexer([ts], method="ffill")[0]
            if m5_i < 50:
                continue

            h1_state = h1_df.iloc[:i+1]
            m5_state = m5_df.iloc[:m5_i+1]

            # Pass D1 data (full history — it's static context, not look-ahead)
            d1_data = all_data[symbol].get("d1")
            signal = await strat.analyze(
                symbol,
                {"h1": h1_state, "m5": m5_state, "d1": d1_data},
                [],
                market_context,
            )
            if signal:
                trade = simulate_trade(signal, m5_df, m5_i)
                if trade:
                    trade["symbol"] = symbol
                    trade["ts"]     = ts
                    trades.append(trade)
                    sym_trades += 1

        print(f" {sym_trades} trades")

    print(f"\n✅ Simulation complete. Total resolved: {len(trades)} trades.")
    print_report("FORENSIC CRT V3 (Sweep+MSS, No Look-Ahead)", trades)

if __name__ == "__main__":
    days = int(sys.argv[1]) if len(sys.argv) > 1 else 60
    asyncio.run(run_comparison(days))

