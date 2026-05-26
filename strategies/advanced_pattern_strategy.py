"""
Advanced Pattern Strategy (V23)
==============================
Captures high-conviction "Super Signals" discovered in the latest research.
Combines DOW-specific hourly biases and Price Action "Stop Hunt" reversals.
"""
from .base_strategy import BaseStrategy
from typing import Optional, Dict, List
import pandas as pd
import numpy as np
import pytz
from core.filters.risk_manager import RiskManager

# ── DOW-Specific Hourly Signals ───────────────────────────────────────────
# Format: { (dow, hour, symbol): (direction, quality_score, expected_hold) }
# dow: 0=Mon, 2=Wed, 4=Fri
DOW_SIGNALS = {
    (2, 21, "USDJPY=X"): ("SELL", 9.5, "1 hour (DOW-WED-BEAR)"),  # 4/4 WR, +6.0R in Run 29
    (2, 21, "GBPJPY=X"): ("SELL", 9.5, "1 hour (DOW-WED-BEAR)"),
    # V35.1r: CL=F REMOVED — 15/17 losses (-14R) in Run 26 forensic audit
    # (4, 21, "CL=F"):     ("BUY",  9.0, "1 hour (DOW-FRI-OIL-BULL)"),
    # V36.0: GC=F BUY REMOVED — 0/4 WR (-4.0R) in Run 29. Gold exclusive to GoldQuantStrategy.
    # (1, 13, "GC=F"):     ("BUY",  8.8, "1 hour (DOW-TUE-GOLD-BID)"),
}

class AdvancedPatternStrategy(BaseStrategy):
    """
    Advanced strategy targeting specific Day-of-Week nuances and Pin-Bar stop hunts.
    V35.1r: Session dedup to prevent multiple fires per symbol per day.
    """
    _fired_today: dict = {}  # {(symbol, date_str): True}

    def get_id(self) -> str:
        return "advanced_patterns_v23"

    def get_name(self) -> str:
        return "Advanced Patterns (DOW + PA)"

    async def analyze(
        self,
        symbol: str,
        data: Dict[str, pd.DataFrame],
        news_events: list,
        market_context: dict,
    ) -> Optional[dict]:
        try:
            # Get data (prefer H1 for these patterns)
            h1 = data.get('h1')
            m5 = data.get('m5')
            df = h1 if h1 is not None else m5
            if df is None or len(df) < 20:
                return None

            latest = df.iloc[-1]
            ts = df.index[-1]

            # Convert to UTC
            if hasattr(ts, 'tz') and ts.tz is not None:
                ts_utc = ts.tz_convert('UTC')
            else:
                ts_utc = ts.tz_localize('UTC') if ts.tzinfo is None else ts

            hour = ts_utc.hour
            dow  = ts_utc.dayofweek
            date_str = ts_utc.strftime('%Y-%m-%d')
            
            # V35.1r: Session dedup — only fire once per symbol per calendar day
            dedup_key = (symbol, date_str)
            if dedup_key in AdvancedPatternStrategy._fired_today:
                return None
            
            # --- 1. DOW-Hourly Signal Check ---
            dow_sig = DOW_SIGNALS.get((dow, hour, symbol))
            if dow_sig:
                direction, q_score, hold = dow_sig
                AdvancedPatternStrategy._fired_today[dedup_key] = True
                return self._build_signal(symbol, df, direction, q_score, hold, "DOW_HOURLY_EDGE")

            # --- 2. Stop Hunt (Pin Bar Reversal) Check ---
            # Only check for specific symbols/hours with proven reversal edge
            # Oil at 14:00 UTC often has a Top Pin reversal
            if symbol == "CL=F" and hour == 14:
                return self._check_stop_hunt(symbol, df, "SELL")
            
            # BTC at 15:00 UTC often has a Top Pin reversal
            if symbol == "BTC-USD" and hour == 15:
                return self._check_stop_hunt(symbol, df, "SELL")

            return None

        except Exception as e:
            return None

    def _check_stop_hunt(self, symbol: str, df: pd.DataFrame, expected_dir: str) -> Optional[dict]:
        latest = df.iloc[-1]
        
        # Calculate Pin Bar characteristics
        body_size = abs(latest['close'] - latest['open'])
        high_wick = latest['high'] - max(latest['open'], latest['close'])
        low_wick  = min(latest['open'], latest['close']) - latest['low']
        
        # ATR estimate (we use last 20)
        atr = latest.get('atr', latest.get('ATR', df['high'].sub(df['low']).tail(20).mean()))
        
        if expected_dir == "SELL":
            # Potential Stop Hunt Top (Bearish Reversal)
            # Criteria: Wick > 2x Body AND Wick > ATR
            if high_wick > 2 * body_size and high_wick > atr:
                return self._build_signal(symbol, df, "SELL", 8.5, "1 hour (STOP_HUNT_REVERSAL)", "PA_REVERSAL")
        
        return None

    def _build_signal(self, symbol: str, df: pd.DataFrame, direction: str, q_score: float, hold: str, regime: str) -> dict:
        latest = df.iloc[-1]
        entry  = latest['open']
        atr    = latest.get('atr', latest.get('ATR', df['high'].sub(df['low']).tail(20).mean()))
        
        # Advanced patterns use tighter stops for 1-hour time-based expectancy
        # V36.0: Tightened from 2.5 ATR to 2.0 ATR — reduces loss magnitude per trade
        sl_dist = atr * 2.0
        # V35.1r: Changed from 1:1 to 1.5:1 — breakeven WR drops from 50% to 40%
        tp_dist = sl_dist * 1.5
        
        if direction == "BUY":
            sl = entry - sl_dist
            tp = entry + tp_dist
        else:
            sl = entry + sl_dist
            tp = entry - tp_dist
            
        risk_details = RiskManager.calculate_lot_size(symbol, entry, sl)
            
        return {
            'strategy_id':   self.get_id(),
            'strategy_name': self.get_name(),
            'symbol':        symbol,
            'direction':     direction,
            'timeframe':     'H1',
            'trade_type':    'ADVANCED_PATTERN',
            'entry_price':   entry,
            'sl':            sl,
            'tp0':           tp,
            'tp1':           tp,
            'tp2':           tp,
            'confidence':    1.5 if q_score > 9 else 1.0,
            'quality_score': q_score,
            'regime':        regime,
            'macro_bias':    'N/A',
            'risk_details':  risk_details,
            'expected_hold': hold,
        }
