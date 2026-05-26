"""
Session Clock Strategy (V1.0)
==============================
Based on empirical daily pattern analysis (365 days × 8 symbols).

Statistically proven patterns (p < 0.05):
  - OIL  BUY  at 21:00 UTC  (64.6% win rate)
  - OIL  SELL at 07:00 UTC  (60.5% bear rate)
  - BTC  BUY  at 21:00 UTC  (53.8% win rate)
  - BTC  BUY  at 22:00 UTC  (54.4% win rate)
  - GOLD BUY  at 16:00 UTC  (57.3% win rate — London Close)
  - GOLD BUY  at 11:00 UTC  (55.6% win rate)
  - EURUSD BUY  at 08:00 UTC (51.9% — London Open)
  - EURUSD SELL at 16:00 UTC (57.4% bear rate — London Close)
  - AUDUSD BUY  at 22:00 UTC (54.3% win rate)
  - GBPJPY SELL at 21:00 UTC (65.5% bear rate)
  - USDJPY SELL at 21:00 UTC (65.2% bear rate)
  - USDJPY BUY  at 18:00 UTC (56.9% win rate)
  - GBPJPY BUY  at 18:00 UTC (57.6% win rate)
  - GBPJPY BUY  at 23:00 UTC (57.6% win rate)

Day-of-week filter: No trades on Friday (markets tend to reverse/close positions).
"""
from .base_strategy import BaseStrategy
from typing import Optional, Dict
import pandas as pd
import pytz
from core.filters.risk_manager import RiskManager
from indicators.calculations import IndicatorCalculator
from core.filters.macro_filter import MacroFilter
from data.news_fetcher import NewsFetcher

# ── Signal Map ────────────────────────────────────────────────────────────────
# Format: { symbol: [ (utc_hour, direction, rr_multiplier), ... ] }
# rr_multiplier: 1.0 = standard 1.5R, 1.5 = 2.25R, 2.0 = 3R
CLOCK_SIGNALS = {
    "CL=F": [        # OIL
        # (21, "BUY",  1.5),   # NY Close rally — FAILURE in current regime
        (7,  "SELL", 1.0),   # Pre-London bear (60.5% bear rate) — 16/16 WR in Run 29
    ],
    "BTC-USD": [
        # (21, "BUY",  1.0),   # DISABLED: Inconsistent edge
        # (22, "BUY",  1.0),   # DISABLED: Inconsistent edge
    ],
    # V36.0 FORENSIC: GC=F BUY REMOVED — 0/31 WR (-31.0R) in Run 29. Gold handled by GoldQuantStrategy.
    # "GC=F": [
    #     (16, "BUY",  1.5),   # KILLED: 0% WR in 31 trades
    #     (11, "BUY",  1.0),   # KILLED: 0% WR in 31 trades
    # ],
    "EURUSD=X": [
        (8,  "BUY",  1.0),   # London Open EURUSD (51.9% WR)
        (16, "SELL", 1.0),   # London Close EURUSD selloff (57.4% bear)
    ],
    "AUDUSD=X": [
        # (22, "BUY",  1.0),   # DISABLED: Inconsistent edge
    ],
    "GBPJPY=X": [
        # (21, "SELL", 1.5),   # DISABLED: Over-filtered
        (18, "BUY",  1.0),   # Pre-NY close GBPJPY (57.6% WR)
        (23, "BUY",  1.0),   # Asian open GBPJPY (57.6% WR)
    ],
    # V36.0 FORENSIC: USDJPY BUY REMOVED — 0/16 WR (-16.0R) in Run 29.
    # USDJPY SELL remains available via Advanced Patterns (4/4 WR, +6.0R).
    # "USDJPY=X": [
    #     (18, "BUY",  1.0),   # KILLED: 0% WR in 16 trades
    # ],
}

# ATR multipliers for SL/TP
# V26.2: Tightened to 1.5 ATR. Best empirical performance across 30-day backtest.
# The wider 2.5 ATR (V27.0) actually lowered total profit (27.8R vs 35.0R).
SL_ATR = 1.5
BASE_RR = 1.0  # 1:1 visual TP (trade managed by time exit, not TP hit)


class SessionClockStrategy(BaseStrategy):
    """
    Time-based strategy that enters at statistically proven hours.
    No indicators required — pure time + price action confirmation.
    """

    def get_id(self) -> str:
        return "session_clock_v1"

    def get_name(self) -> str:
        return "Session Clock (Time-Based Edge)"

    async def analyze(
        self,
        symbol: str,
        data: Dict[str, pd.DataFrame],
        news_events: list,
        market_context: dict,
    ) -> Optional[dict]:
        try:
            # Get H1 data (this strategy operates on hourly candles)
            h1 = data.get('h1')
            m5 = data.get('m5')
            df = h1 if h1 is not None else m5
            if df is None or len(df) < 1:
                return None

            # Check if this symbol has clock signals
            signals_for_symbol = CLOCK_SIGNALS.get(symbol)
            if not signals_for_symbol:
                return None

            latest = df.iloc[-1]
            ts = df.index[-1]

            # Convert to UTC
            if hasattr(ts, 'tz') and ts.tz is not None:
                ts_utc = ts.tz_convert('UTC')
            else:
                ts_utc = ts.tz_localize('UTC') if ts.tzinfo is None else ts

            current_hour = ts_utc.hour
            current_minute = ts_utc.minute
            current_dow  = ts_utc.dayofweek  # 0=Mon, 4=Fri

            # Day-of-week filter: skip Friday
            if current_dow == 4:
                return None
                
            # Prevent multiple signals: Only trigger in the first 15 minutes of the hour
            if current_minute >= 15:
                return None

            # Find matching signal for this hour
            matched = None
            for (sig_hour, direction, rr_mult) in signals_for_symbol:
                if current_hour == sig_hour:
                    matched = (direction, rr_mult)
                    break

            if matched is None:
                return None

            # V27.0 RELAXED FILTER: Allow patterns with rr_mult >= 1.0 (All defined patterns)
            # This ensures EURUSD, AUDUSD, BTC, and OIL all fire correctly.
            direction, rr_mult = matched
            if rr_mult < 1.0:
                return None

            # V26.2: NEWS FILTER — Block signals within ±30 min of High-impact events
            # Prevents SESSION_CLOCK from firing into NFP, CPI, FOMC, BoE decisions etc.
            if NewsFetcher.is_high_impact_imminent(current_hour, news_events, symbol):
                return None

            # V25.0 FORENSIC HEDGE: Apply Regime & Macro filters to Session Clock
            regime = IndicatorCalculator.get_market_regime(df)
            if regime in ["CHOPPY", "UNKNOWN"]:
                return None
            
            # V36.0: Block in LOW_VOL_RANGE — momentum plays fail in compression
            if regime == "LOW_VOL_RANGE":
                return None
                
            macro_bias = MacroFilter.get_macro_bias(market_context)
            if not MacroFilter.is_macro_safe(symbol, direction, macro_bias):
                return None

            # V26.3: Z-SCORE CONTRADICTION FILTER
            # If the asset's z-score strongly opposes our direction, the time
            # pattern is firing against a strong macro trend — skip it.
            # e.g., GBPJPY SELL at 21:00 but z-score is deeply negative
            # (already sold off hard) — asymmetric risk, reward is already taken.
            zscore = latest.get('zscore_20', 0.0) or 0.0
            if direction == "BUY"  and zscore < -1.8:
                return None  # Market deeply oversold — reversal risk, no room to run
            if direction == "SELL" and zscore > +1.8:
                return None  # Market deeply overbought — squeeze risk, no room to fall

            # ATR for SL/TP
            atr = latest.get('atr', latest.get('ATR', None))
            if atr is None or atr == 0:
                return None

            entry = latest.get('open', latest.get('Open'))
            sl_dist = atr * SL_ATR
            
            # Time-based targets (will be closed by the bot after 1h)
            # V26.2: TP set at 1.5:1 to incentivize moves past 1.0 ATR
            tp_dist = sl_dist * 1.5

            if direction == "BUY":
                sl = entry - sl_dist
                tp = entry + tp_dist
            else:
                sl = entry + sl_dist
                tp = entry - tp_dist

            risk_details = RiskManager.calculate_lot_size(symbol, entry, sl, hour=current_hour)

            return {
                'strategy_id':   self.get_id(),
                'strategy_name': self.get_name(),
                'symbol':        symbol,
                'direction':     direction,
                'timeframe':     'H1',
                'trade_type':    'SESSION_CLOCK',
                'entry_price':   entry,
                'sl':            sl,
                'tp0':           tp,
                'tp1':           tp,
                'tp2':           tp,
                'confidence':    rr_mult,
                'quality_score': 8.5,  # High confidence — statistically validated
                'regime':        'TIME_BASED_EXPECTANCY',
                'macro_bias':    'N/A',
                'risk_details':  risk_details,
                'expected_hold': '1 hour (TIME-BASED EXIT)',
                'score_details': {
                    'hour':      current_hour,
                    'dow':       current_dow,
                    'rr_mult':   rr_mult,
                    'signal':    1.0 if direction == "BUY" else -1.0,
                }
            }

        except Exception:
            return None
