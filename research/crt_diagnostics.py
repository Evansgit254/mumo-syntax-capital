"""
CRT Signal Diagnostics — counts rejections at each filter stage
Usage: python3 -m research.crt_diagnostics [days]
"""
import sys
import asyncio
from datetime import datetime

import pandas as pd

from data.dukascopy_loader import DukascopyLoader
from data.fetcher import DataFetcher
from indicators.calculations import IndicatorCalculator

SYMBOL = "EURUSD=X"
DAYS   = int(sys.argv[1]) if len(sys.argv) > 1 else 60   # Backtest window from CSV


def _load_dukascopy(symbol, days, loader):
    h1_duka  = loader.load(symbol, timeframe="1h")
    m15_duka = loader.load(symbol, timeframe="15min")
    d1_duka  = loader.load(symbol, timeframe="1d")
    for df in [h1_duka, m15_duka, d1_duka]:
        if df is not None and df.index.tz is None:
            df.index = df.index.tz_localize("UTC")
    csv_end     = h1_duka.index[-1]
    slice_start = csv_end - pd.Timedelta(days=days)
    h1   = IndicatorCalculator.add_indicators(h1_duka[h1_duka.index >= slice_start], "1h")
    m15  = IndicatorCalculator.add_indicators(m15_duka[m15_duka.index >= slice_start], "15m")
    d1   = d1_duka  # raw for bias fallback
    return h1, m15, d1


async def run_diagnostics():
    loader = DukascopyLoader(base_dir="data/dukascopy")
    h1_df, m15_df, d1_df = _load_dukascopy(SYMBOL, DAYS, loader)

    counts = {
        "h1_bars_scanned":     0,
        "killzone_pass":       0,
        "range_pass":          0,
        "atr_ok":              0,
        "scan_has_data":       0,
        "sweep_found":         0,
        "mss_found":           0,
        "d1_bias_pass":        0,
        "ema_position_pass":   0,
        "ema_slope_pass":      0,
        "rr_pass":             0,
        "signal_generated":    0,
    }

    m15_sorted = m15_df.sort_index()

    for i in range(5, len(h1_df)):
        counts["h1_bars_scanned"] += 1
        h1_state  = h1_df.iloc[:i + 1]
        curr_time = h1_state.index[-1]

        # Killzone
        hour = curr_time.hour
        if not (7 <= hour < 11 or 12 <= hour < 16):
            continue
        counts["killzone_pass"] += 1

        # Reference candle
        if len(h1_state) < 4:
            continue
        ref_h1  = h1_state.iloc[-2]
        curr_h1 = h1_state.iloc[-1]
        atr_h1  = curr_h1.get("atr")
        if atr_h1 is None or atr_h1 <= 0:
            continue
        counts["atr_ok"] += 1

        ref_high   = ref_h1["high"]
        ref_low    = ref_h1["low"]
        range_size = ref_high - ref_low
        if range_size < atr_h1 * 0.40 or range_size > atr_h1 * 2.5:
            continue
        counts["range_pass"] += 1

        # M15 scan slice
        entry_slice = m15_sorted[m15_sorted.index <= curr_time]
        if len(entry_slice) < 6:
            continue
        scan_bars = entry_slice.iloc[-16:]
        counts["scan_has_data"] += 1

        highs  = scan_bars["high"].values
        lows   = scan_bars["low"].values
        opens  = scan_bars["open"].values
        closes = scan_bars["close"].values

        sweep_ok = False
        mss_ok   = False
        direction = None
        entry_price = None

        for j in range(3, len(scan_bars)):
            if j < len(scan_bars) - 3:
                continue
            c_h, c_l, c_o, c_c = highs[j], lows[j], opens[j], closes[j]
            c_range = c_h - c_l
            if c_range <= 0:
                continue
            body = abs(c_c - c_o)

            prev_lows  = lows[:j]
            prev_highs = highs[:j]

            swept_lows = [l for l in prev_lows if l < ref_low]
            if swept_lows and (ref_low - min(swept_lows)) >= atr_h1 * 0.10:
                sweep_ok = True
                if (c_c > ref_low + range_size * 0.10 and c_c > c_o
                        and (c_h - c_c) / c_range < 0.35 and body / c_range > 0.45):
                    mss_ok = True; direction = "BUY"; entry_price = c_c; break

            swept_highs = [h for h in prev_highs if h > ref_high]
            if swept_highs and (max(swept_highs) - ref_high) >= atr_h1 * 0.10:
                sweep_ok = True
                if (c_c < ref_high - range_size * 0.10 and c_c < c_o
                        and (c_c - c_l) / c_range < 0.35 and body / c_range > 0.45):
                    mss_ok = True; direction = "SELL"; entry_price = c_c; break

        if sweep_ok:
            counts["sweep_found"] += 1
        if mss_ok:
            counts["mss_found"] += 1

        if not mss_ok or not direction or entry_price is None:
            continue

        # D1 bias
        d1_bias = None
        if d1_df is not None and len(d1_df) >= 6:
            d1_slice = d1_df[d1_df.index <= curr_time]
            if len(d1_slice) >= 6:
                last = d1_slice.iloc[-1]
                c = last.get("close", last.get("Close", 0))
                o = last.get("open",  last.get("Open",  0))
                ema = last.get("ema_trend") or last.get("ema_200")
                if not ema:
                    ema = d1_slice["close"].iloc[-5:].mean() if "close" in d1_slice.columns \
                          else d1_slice["Close"].iloc[-5:].mean()
                if c and ema:
                    if c > ema and c > o:   d1_bias = "BUY"
                    elif c < ema and c < o: d1_bias = "SELL"

        if d1_bias is not None and d1_bias != direction:
            continue
        counts["d1_bias_pass"] += 1

        # EMA200 position gate
        ema_200 = curr_h1.get("ema_200") or curr_h1.get("ema_trend")
        if ema_200 and ema_200 > 0:
            if direction == "BUY"  and entry_price < ema_200 * 0.997:
                continue
            if direction == "SELL" and entry_price > ema_200 * 1.001:
                continue
        counts["ema_position_pass"] += 1

        # EMA slope gate
        slope_blocked = False
        if ema_200 and len(h1_state) >= 6:
            ema_prev = h1_state.iloc[-6].get("ema_trend") or h1_state.iloc[-6].get("ema_200")
            if ema_prev and ema_prev > 0:
                rising  = ema_200 > ema_prev * 1.00005
                falling = ema_200 < ema_prev * 0.99995
                if direction == "SELL" and rising:   slope_blocked = True
                if direction == "BUY"  and falling:  slope_blocked = True
        if slope_blocked:
            continue
        counts["ema_slope_pass"] += 1

        # R:R check (simplified — use ref_high/low as TP1)
        sl_dist = abs(entry_price - (ref_low * 0.9990 if direction=="BUY" else ref_high * 1.0010))
        if sl_dist <= 0:
            continue
        tp1 = ref_high if direction == "BUY" else ref_low
        reward = abs(tp1 - entry_price)
        if reward >= sl_dist * 1.5:
            counts["rr_pass"] += 1
            counts["signal_generated"] += 1

    print(f"\n{'='*55}")
    print(f"  CRT SIGNAL DIAGNOSTICS — {SYMBOL}  ({DAYS}d from CSV end)")
    print(f"  Period: {h1_df.index[0].date()} → {h1_df.index[-1].date()}")
    print(f"{'='*55}")
    total = counts["h1_bars_scanned"]
    for key, val in counts.items():
        pct = f"  ({val/total*100:.1f}%)" if total > 0 and key != "h1_bars_scanned" else ""
        label = key.replace("_", " ").title()
        print(f"  {label:28s}: {val:6,}{pct}")
    print()
    print("  ── BOTTLENECK ANALYSIS ──")
    kz       = counts["killzone_pass"]
    after_kz = counts["range_pass"]
    print(f"  Killzone filter cuts:     {total - kz:,} bars ({(total-kz)/total*100:.0f}%)")
    if kz:
        print(f"  Bad range cuts:           {kz - after_kz:,} bars ({(kz-after_kz)/kz*100:.0f}% of KZ bars)")
    if counts["scan_has_data"]:
        print(f"  No sweep/MSS cuts:        {counts['scan_has_data'] - counts['mss_found']:,}")
    if counts["mss_found"]:
        d1_cut   = counts["mss_found"] - counts["d1_bias_pass"]
        ema_cut  = counts["d1_bias_pass"] - counts["ema_position_pass"]
        slope_cut= counts["ema_position_pass"] - counts["ema_slope_pass"]
        rr_cut   = counts["ema_slope_pass"] - counts["rr_pass"]
        print(f"  D1 bias filter cuts:      {d1_cut:,}  ({d1_cut/counts['mss_found']*100:.0f}% of MSS signals)")
        print(f"  EMA position cuts:        {ema_cut:,}  ({ema_cut/counts['mss_found']*100:.0f}%)")
        print(f"  EMA slope gate cuts:      {slope_cut:,}  ({slope_cut/counts['mss_found']*100:.0f}%)")
        print(f"  R:R gate cuts:            {rr_cut:,}  ({rr_cut/counts['mss_found']*100:.0f}%)")


if __name__ == "__main__":
    asyncio.run(run_diagnostics())
