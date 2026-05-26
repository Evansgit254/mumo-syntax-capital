"""
Market Regime Detector (V23.2)
==============================
Automatically classifies the market as TRENDING or RANGING
using ADX and ATR volatility across multiple symbols.

Based on backtested thresholds:
- ADX > 25 → TRENDING  → Quality threshold = 5.0 (normal)
- ADX 20-25 → MIXED    → Quality threshold = 6.5 (moderate filter)
- ADX < 20 → RANGING   → Quality threshold = 8.0 (strict filter)
"""

import numpy as np
import sqlite3
from datetime import datetime

# --- REGIME THRESHOLDS ---
ADX_TRENDING  = 25.0   # Strong trend
ADX_MIXED     = 20.0   # Transitioning
ADX_RANGING   = 20.0   # Choppy / sideways

# Quality scores per regime
QUALITY_TRENDING = 5.0
QUALITY_MIXED    = 6.5
QUALITY_RANGING  = 8.0


def _calc_adx(df, period=14) -> float:
    """Calculate Average Directional Index (ADX) from H1 OHLC data."""
    try:
        high  = df['high'].values if 'high' in df.columns else df['High'].values
        low   = df['low'].values  if 'low'  in df.columns else df['Low'].values
        close = df['close'].values if 'close' in df.columns else df['Close'].values

        n = len(close)
        if n < period + 5:
            return 20.0  # Neutral default

        # True Range
        tr_list = []
        for i in range(1, n):
            tr = max(high[i] - low[i],
                     abs(high[i] - close[i-1]),
                     abs(low[i]  - close[i-1]))
            tr_list.append(tr)

        # Directional Movement
        dm_plus  = [max(high[i] - high[i-1], 0) if (high[i] - high[i-1]) > (low[i-1] - low[i]) else 0 for i in range(1, n)]
        dm_minus = [max(low[i-1] - low[i], 0)   if (low[i-1] - low[i]) > (high[i] - high[i-1]) else 0 for i in range(1, n)]

        # Smooth over period (simple EMA-like)
        def smooth(arr, p):
            result = [sum(arr[:p]) / p]
            for v in arr[p:]:
                result.append(result[-1] * (p-1)/p + v / p)
            return result

        atr   = smooth(tr_list, period)
        pdm   = smooth(dm_plus, period)
        mdm   = smooth(dm_minus, period)

        min_len = min(len(atr), len(pdm), len(mdm))
        di_plus  = [100 * pdm[i] / atr[i] if atr[i] > 0 else 0 for i in range(min_len)]
        di_minus = [100 * mdm[i] / atr[i] if atr[i] > 0 else 0 for i in range(min_len)]
        dx       = [100 * abs(di_plus[i] - di_minus[i]) / (di_plus[i] + di_minus[i])
                    if (di_plus[i] + di_minus[i]) > 0 else 0 for i in range(min_len)]

        adx = smooth(dx, period)
        return round(adx[-1], 2) if adx else 20.0

    except Exception:
        return 20.0  # Neutral fallback


def detect_regime(data_source, period=50) -> dict:
    """
    Improved 4-Cluster Regime Detector (V35.0)
    
    Args:
        data_source: Either {symbol: h1_df} dict OR a single pd.DataFrame.
        period: Lookback for ATR/Trend averaging.

    Returns:
        {
            'regime': 'TRENDING_BULL' | 'TRENDING_BEAR' | 'VOLATILE_RANGE' | 'LOW_VOL_RANGE',
            'adx': float,
            'vol_ratio': float,
            'quality_threshold': float
        }
    """
    # 1. Normalize input to a single dataframe for local or first in map for global
    if isinstance(data_source, dict):
        # Global: Process first symbol as proxy or potentially average (Simplified for Phase A)
        symbol = list(data_source.keys())[0]
        df = data_source[symbol]
    else:
        df = data_source

    if df is None or len(df) < period:
        return {
            'regime': 'LOW_VOL_RANGE', 'adx': 20.0, 'vol_ratio': 1.0, 
            'quality_threshold': QUALITY_MIXED
        }

    last = df.iloc[-1]
    
    # 1. Trend Strength (ADX)
    adx = _calc_adx(df)
    
    # 2. Volatility (ATR Ratio)
    atr_now = last.get('atr', 0)
    atr_avg = df['atr'].tail(period).mean()
    vol_ratio = atr_now / atr_avg if (atr_avg and atr_avg != 0) else 1.0
    
    # 3. Directional Spread (Normalized EMA Distance)
    # Using EMA20 vs EMA200 for long-term trend orientation
    ema_short = last.get('ema_20', 0)
    ema_long = last.get('ema_200', 0) or last.get('ema_trend', 0)
    close = last.get('close', 1.0)
    spread = (ema_short - ema_long) / close if close != 0 else 0
    
    # --- Clustering Logic ---
    # Thresholds: ADX > 25 for trend, ATR_Ratio > 1.2 for volatile
    if adx > 25:
        if spread > 0.005: 
            regime = "TRENDING_BULL"
        elif spread < -0.005: 
            regime = "TRENDING_BEAR"
        else:
            regime = "VOLATILE_RANGE"  # Strong ADX but no clear EMA spread = Volatile
    elif vol_ratio > 1.2:
        regime = "VOLATILE_RANGE"
    else:
        regime = "LOW_VOL_RANGE"

    # Map thresholds to the new clusters
    thresholds = {
        "TRENDING_BULL": QUALITY_TRENDING,
        "TRENDING_BEAR": QUALITY_TRENDING,
        "VOLATILE_RANGE": QUALITY_MIXED,
        "LOW_VOL_RANGE": QUALITY_RANGING
    }
    
    threshold = thresholds.get(regime, QUALITY_MIXED)
    adx_str = f"ADX={adx:.1f}"
    vol_str = f"VolRatio={vol_ratio:.2f}"
    spread_str = f"Spread={spread:.4f}"
    detail = f"{adx_str} | {vol_str} | {spread_str} → Regime: {regime}"

    return {
        'regime': regime,
        'adx': adx,
        'vol_ratio': round(vol_ratio, 2),
        'quality_threshold': threshold,
        'detail': detail
    }


def apply_regime_filter(regime_result: dict, db_clients_path: str):
    """
    Write the detected quality threshold to the system_config DB
    so _load_dynamic_config() picks it up automatically next cycle.
    """
    threshold = regime_result['quality_threshold']
    try:
        conn = sqlite3.connect(db_clients_path)
        conn.execute(
            "UPDATE system_config SET value=? WHERE key='MIN_QUALITY_SCORE'",
            (str(threshold),)
        )
        conn.commit()
        conn.close()
        print(f"🧠 REGIME: {regime_result['regime']} → Quality threshold set to {threshold}")
        print(f"   └─ {regime_result['detail']}")
    except Exception as e:
        print(f"⚠️  Could not apply regime filter: {e}")
