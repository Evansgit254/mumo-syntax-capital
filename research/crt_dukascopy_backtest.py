"""
CRT Strategy — Dukascopy Extended Backtest
==========================================
Uses Dukascopy M1 CSV data (years of history) when available,
falls back to Yahoo Finance M15 data (60-day cap) otherwise.

HOW TO GET DUKASCOPY DATA (FREE, goes back to 2003):
  1. Go to: https://www.dukascopy.com/swiss/english/marketwatch/historical/
  2. Select a pair (e.g. EUR/USD), select M1 timeframe
  3. Set your date range (recommend 2023-01-01 to today for 2+ years)
  4. Download → save CSV to:
       data/dukascopy/EURUSD/EURUSD_Candlestick_1_M_BID_01.01.2023-04.05.2025.csv

SUPPORTED DUKASCOPY SYMBOLS:
  Forex:  EURUSD, GBPUSD, USDJPY, GBPJPY, AUDUSD, USDCAD, NZDUSD
  Gold:   XAUUSD  (-> GC=F in the strategy)
  Oil:    XTIUSD  (-> CL=F in the strategy)

Run:
  python3 -m research.crt_dukascopy_backtest           # uses last 365d from CSVs
  python3 -m research.crt_dukascopy_backtest 180        # uses last 180d from CSVs
"""

import os
# Research override: lower quality gate for historical backtesting.
# Live default (7.0) requires rr_ratio >= 2.1R — too strict for 2024 market conditions.
# 4.0 → requires rr_ratio >= 1.2R, matching our 1.0R minimum entry threshold.
os.environ.setdefault("MIN_QUALITY_SCORE", "4.0")

import sys
import asyncio
from datetime import datetime


import pandas as pd

from strategies.crt_strategy import CRTStrategy
from data.dukascopy_loader import DukascopyLoader
from data.fetcher import DataFetcher
from indicators.calculations import IndicatorCalculator

SEPARATOR = "=" * 80

BACKTEST_SYMBOLS = [
    "EURUSD=X",
    "GBPUSD=X",
    "USDJPY=X",
    "AUDUSD=X",
    "GC=F",
    "CL=F",
]

DXY_SYMBOL = "DX-Y.NYB"


# ─────────────────────────────────────────────────────────────────────────────
# Trade Simulation — ICT Breakeven Mechanic
# ─────────────────────────────────────────────────────────────────────────────

def simulate_trade(signal, entry_df, entry_i, lookahead=200):
    """
    Simulate CRT trade with ICT breakeven mechanic:
      - At TP0 (equilibrium): move SL to BE and let trade run
      - At TP1 (opposite extreme): full win
      - At TP2 (extension): runner win
      - SL hit before TP0: full loss
      - SL hit after TP0: breakeven (0R)
    """
    direction   = signal["direction"]
    entry_price = signal["entry_price"]
    sl          = signal["sl"]
    tp0         = signal["tp0"]
    tp1         = signal["tp1"]
    tp2         = signal["tp2"]

    sl_dist = abs(entry_price - sl)
    if sl_dist <= 0:
        return None

    future_bars  = entry_df.iloc[entry_i + 1: entry_i + 1 + lookahead]
    if future_bars.empty:
        return None

    be_triggered = False

    for _, bar in future_bars.iterrows():
        high = bar["high"]
        low  = bar["low"]

        if direction == "BUY":
            if not be_triggered and high >= tp0:
                be_triggered = True
                sl = entry_price
            if high >= tp2:
                return {"exit": "TP3 (Extension)", "pnl_r": abs(tp2 - entry_price) / sl_dist}
            if high >= tp1:
                return {"exit": "TP2 (Extreme)",   "pnl_r": abs(tp1 - entry_price) / sl_dist}
            if low <= sl:
                return {"exit": "BE" if be_triggered else "LOSS",
                        "pnl_r": 0.0 if be_triggered else -1.0}
        else:
            if not be_triggered and low <= tp0:
                be_triggered = True
                sl = entry_price
            if low <= tp2:
                return {"exit": "TP3 (Extension)", "pnl_r": abs(entry_price - tp2) / sl_dist}
            if low <= tp1:
                return {"exit": "TP2 (Extreme)",   "pnl_r": abs(entry_price - tp1) / sl_dist}
            if high >= sl:
                return {"exit": "BE" if be_triggered else "LOSS",
                        "pnl_r": 0.0 if be_triggered else -1.0}

    return None


# ─────────────────────────────────────────────────────────────────────────────
# Data Loading
# ─────────────────────────────────────────────────────────────────────────────

def _yf_fetch(symbol, interval, period=None, start=None, end=None):
    try:
        if start and end:
            return DataFetcher.fetch_range(symbol, interval, start, end)
        return DataFetcher.fetch_data(symbol, interval, period=period)
    except Exception:
        return None


def load_symbol_data(symbol, days, loader):
    """
    Load data for one symbol.

    When Dukascopy CSVs are present, resample the same M1 data to BOTH
    H1 and M15 so reference range and entry timeframe are perfectly in sync.
    """
    duka_avail  = loader.list_available_symbols()
    entry_df    = None
    h1_df       = None
    d1_df_raw   = None

    # ── Priority 1: Dukascopy — resample same M1 CSV to H1, M15, D1 ──────────
    if symbol in duka_avail:
        h1_duka  = loader.load(symbol, timeframe="1h")
        m15_duka = loader.load(symbol, timeframe="15min")
        d1_duka  = loader.load(symbol, timeframe="1d")

        if h1_duka is not None and not h1_duka.empty and \
           m15_duka is not None and not m15_duka.empty:

            # Ensure UTC-aware index on all timeframes
            for df in [h1_duka, m15_duka] + ([d1_duka] if d1_duka is not None else []):
                if df.index.tz is None:
                    df.index = df.index.tz_localize("UTC")

            # Slice last `days` from the CSV end date — H1 and M15 will match
            csv_end     = h1_duka.index[-1]
            slice_start = csv_end - pd.Timedelta(days=days)

            h1_df    = h1_duka[h1_duka.index   >= slice_start]
            entry_df = m15_duka[m15_duka.index >= slice_start]

            if d1_duka is not None:
                d1_start  = csv_end - pd.Timedelta(days=days + 210)
                d1_df_raw = d1_duka[d1_duka.index >= d1_start]

            if entry_df.empty:
                h1_df = None
                entry_df = None
            else:
                csv_start   = h1_duka.index[0]
                entry_label = (
                    f"M15 Dukascopy [{csv_start.date()}→{csv_end.date()}]"
                    f" last {days}d = {len(entry_df):,} M15 / {len(h1_df):,} H1"
                )


    # ── Priority 2: Yahoo Finance M15 (live 60-day window) ───────────────────
    if entry_df is None:
        yf_df = _yf_fetch(symbol, "15m", period="60d")
        if yf_df is not None and not yf_df.empty:
            entry_df    = yf_df
            entry_label = f"M15 Yahoo ({len(entry_df):,} bars)"

    # ── Priority 3: Yahoo Finance M5 fallback ─────────────────────────────────
    if entry_df is None or entry_df.empty:
        yf_df = _yf_fetch(symbol, "5m", period="58d")
        if yf_df is not None and not yf_df.empty:
            entry_df    = yf_df
            entry_label = f"M5 Yahoo fallback ({len(entry_df):,} bars)"

    if entry_df is None or entry_df.empty:
        return None

    # ── H1 data: fall back to Yahoo finite period if not fetched yet ──────────
    if h1_df is None:
        h1_df = _yf_fetch(symbol, "1h", period=f"{min(days, 729)}d")
    if h1_df is None or h1_df.empty:
        return None

    # ── D1 data ───────────────────────────────────────────────────────────────
    if d1_df_raw is None:
        d1_df_raw = _yf_fetch(symbol, "1d", period="400d")

    d1_processed = None
    if d1_df_raw is not None and not d1_df_raw.empty:
        d1_processed = IndicatorCalculator.add_indicators(d1_df_raw, "1d")
        if d1_processed is None:
            d1_processed = d1_df_raw   # raw fallback when indicators need 200+ bars

    return {
        "h1":          IndicatorCalculator.add_indicators(h1_df, "1h"),
        "entry_df":    IndicatorCalculator.add_indicators(entry_df, "15m"),
        "entry_label": entry_label,
        "d1":          d1_processed,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Main Backtest Loop
# ─────────────────────────────────────────────────────────────────────────────

async def run_dukascopy_backtest(days=365):
    loader       = DukascopyLoader(base_dir="data/dukascopy")
    duka_symbols = loader.list_available_symbols()

    print(SEPARATOR)
    print(f"  CRT STRATEGY V4 — EXTENDED BACKTEST")
    print(f"  Run Date  : {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    if duka_symbols:
        print(f"  Dukascopy : {duka_symbols}")
        print(f"  Mode      : Historical (last {days}d from CSV end date)")
    else:
        print(f"  Dukascopy : No CSVs found — using Yahoo Finance M15 (60d)")
        print(f"\n📂 To get Dukascopy data:")
        print("   1. https://www.dukascopy.com/swiss/english/marketwatch/historical/")
        print("   2. Select symbol → M1 → date range → Download CSV")
        print("   3. Save to: data/dukascopy/EURUSD/  (or GBPUSD/, XAUUSD/, etc.)")
    print(SEPARATOR)

    print("\n📥 Loading market data...")
    all_data = {}
    for symbol in BACKTEST_SYMBOLS:
        print(f"  {symbol:12s} ... ", end="", flush=True)
        sym_data = load_symbol_data(symbol, days, loader)
        if sym_data is None:
            print("❌ SKIP")
            continue
        all_data[symbol] = sym_data
        h1_bars = len(sym_data["h1"]) if sym_data["h1"] is not None else 0
        print(f"✅  H1:{h1_bars}  |  {sym_data['entry_label']}")

    if not all_data:
        print("❌ No data loaded.")
        return

    # Historical backtest: do NOT load live DXY/TNX market context.
    # Using current 2026 DXY data to filter 2024 trades creates systematic bias:
    # if DXY is bullish TODAY, ALL historical EUR/USD BUY signals would be blocked.
    # Empty context → MacroFilter returns NEUTRAL → both directions tradeable.
    market_context = {}


    strat  = CRTStrategy()
    trades = []

    print(f"\n⚙️  Running simulation ({len(all_data)} symbols)...")

    for symbol, sym_data in all_data.items():
        h1_df    = sym_data["h1"]
        entry_df = sym_data["entry_df"]
        d1_data  = sym_data["d1"]

        if h1_df is None or entry_df is None:
            print(f"  [{symbol}] skipped — missing data")
            continue

        entry_sorted    = entry_df.sort_index()
        sym_trades      = []
        last_signal_bar = -5

        for i in range(5, len(h1_df)):
            h1_state  = h1_df.iloc[:i + 1]
            curr_time = h1_state.index[-1]

            entry_slice = entry_sorted[entry_sorted.index <= curr_time]
            if len(entry_slice) < 6:
                continue

            # Slice D1 to curr_time to avoid look-ahead bias.
            # Without this, df_d1.iloc[-1] always returns the last CSV bar
            # (e.g. 2024-12-31), locking D1 bias to December even in January.
            d1_slice = None
            if d1_data is not None:
                d1_mask = d1_data.index <= curr_time
                d1_slice = d1_data[d1_mask] if d1_mask.any() else None

            signal = await strat.analyze(
                symbol,
                {"h1": h1_state, "m15": entry_slice, "d1": d1_slice},
                [],
                market_context,
            )


            if signal and (i - last_signal_bar) >= 3:
                entry_i = len(entry_slice) - 1
                result  = simulate_trade(signal, entry_sorted, entry_i)
                if result:
                    result.update({
                        "symbol":      symbol,
                        "direction":   signal["direction"],
                        "entry_time":  curr_time,
                        "entry_price": signal["entry_price"],
                        "fvg_used":    signal.get("fvg_used", False),
                        "daily_bias":  signal.get("daily_bias", "NEUTRAL"),
                    })
                    sym_trades.append(result)
                    trades.append(result)
                    last_signal_bar = i

        print(f"  [{symbol:12s}] {len(sym_trades)} trades")

    # ── Results ───────────────────────────────────────────────────────────────
    total = len(trades)
    print(f"\n✅ Simulation complete. Total resolved: {total} trades.\n")

    if not total:
        print("No trades resolved.")
        return

    wins   = [t for t in trades if t["pnl_r"] > 0]
    losses = [t for t in trades if t["pnl_r"] < 0]
    bes    = [t for t in trades if t["pnl_r"] == 0]
    total_pnl = sum(t["pnl_r"] for t in trades)
    win_r  = sum(t["pnl_r"] for t in wins)
    loss_r = abs(sum(t["pnl_r"] for t in losses))
    pf     = win_r / loss_r if loss_r > 0 else float("inf")
    wr     = len(wins) / total * 100
    avg_r  = total_pnl / total

    buys      = [t for t in trades if t["direction"] == "BUY"]
    sells     = [t for t in trades if t["direction"] == "SELL"]
    buy_wr    = len([t for t in buys  if t["pnl_r"] > 0]) / max(1, len(buys))  * 100
    sell_wr   = len([t for t in sells if t["pnl_r"] > 0]) / max(1, len(sells)) * 100
    fvg_trades = [t for t in trades if t.get("fvg_used")]
    reg_trades = [t for t in trades if not t.get("fvg_used")]

    exit_counts = {}
    for t in trades:
        exit_counts[t["exit"]] = exit_counts.get(t["exit"], 0) + 1

    print("─" * 56)
    print("  CRT V4 — Extended Backtest Results (ICT Mechanics)")
    print("─" * 56)
    print(f"  Total Trades       : {total}")
    print(f"  Wins / BE / Losses : {len(wins)} / {len(bes)} / {len(losses)}")
    print(f"  Win Rate           : {wr:.1f}%")
    print(f"  Total P&L (R)      : {total_pnl:+.2f}R")
    print(f"  Avg R/Trade        : {avg_r:+.3f}R")
    print(f"  Profit Factor      : {pf:.2f}")
    print()
    print(f"  BUY  trades : {len(buys):3d}  (WR: {buy_wr:.1f}%)")
    print(f"  SELL trades : {len(sells):3d}  (WR: {sell_wr:.1f}%)")
    print()
    print("  Exit Distribution:")
    for exit_type, cnt in sorted(exit_counts.items()):
        print(f"    {exit_type:20s}: {cnt:3d}  {'█' * cnt}")
    print()
    print("  Per-Symbol:")
    for sym in BACKTEST_SYMBOLS:
        st = [t for t in trades if t["symbol"] == sym]
        if not st:
            continue
        sw  = [t for t in st if t["pnl_r"] > 0]
        wd  = len(sw) / len(st) * 100
        pnl = sum(t["pnl_r"] for t in st)
        fvg = sum(1 for t in st if t.get("fvg_used"))
        print(f"    {sym:12s}  {len(st):3d} trades  WR={wd:.0f}%  P&L={pnl:+.2f}R  FVG={fvg}/{len(st)}")
    print()
    if fvg_trades:
        fvg_wr = len([t for t in fvg_trades if t["pnl_r"] > 0]) / len(fvg_trades) * 100
        reg_wr = len([t for t in reg_trades if t["pnl_r"] > 0]) / max(1, len(reg_trades)) * 100
        print(f"  FVG Entry WR : {fvg_wr:.1f}%  ({len(fvg_trades)} trades)")
        print(f"  MSS Entry WR : {reg_wr:.1f}%  ({len(reg_trades)} trades)")


if __name__ == "__main__":
    days = int(sys.argv[1]) if len(sys.argv) > 1 else 365
    asyncio.run(run_dukascopy_backtest(days))
