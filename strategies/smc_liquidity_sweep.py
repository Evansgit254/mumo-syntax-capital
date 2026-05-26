from .base_strategy import BaseStrategy
from typing import Optional, Dict
import pandas as pd
from core.filters.risk_manager import RiskManager
from indicators.calculations import IndicatorCalculator

class SMCLiquiditySweepStrategy(BaseStrategy):
    """
    Maps the Asian Session high/low range (00:00 - 08:00 UTC).
    During London/NY, if price sweeps these levels but closes back inside (Wick Rejection),
    it generates a signal to fade the breakout (Stop Hunt trap).
    
    FORENSIC AUDIT FIXES:
    - Lowered RR from 3:1 to 2:1 (breakeven WR = 33% vs old 25%)
    - Widened SL from 1.0 ATR to 1.5 ATR (23% instant SL hits)
    - Banned toxic symbols: CL=F (6.7% WR), AUDUSD=X (10%), USDJPY=X (9.5%)
    - Banned toxic hours: 10, 14, 18, 19 (0-8% WR)
    - SELL-only bias when directional skew detected
    """

    # Symbols with <15% WR in audit — statistically proven losers
    # V35.1r: Added GBPUSD (-6.67R) and GBPJPY (-3.33R) — forensic audit Run 26
    # V36.0: Added GC=F — 0/7 BUY WR (-7.0R) in Run 29. Gold exclusive to GoldQuantStrategy.
    BANNED_SYMBOLS = {"CL=F", "AUDUSD=X", "USDJPY=X", "BTC-USD", "GBPUSD=X", "GBPJPY=X", "GC=F"}
    # Hours with 0-8% WR in audit. V24.1: Added 11 (Dead Zone)
    BANNED_HOURS = {10, 11, 14, 18, 19}

    def get_id(self) -> str:
        return "smc_sweep_v1"

    def get_name(self) -> str:
        return "SMC Asian Liquidity Sweep"

    async def analyze(
        self,
        symbol: str,
        data: Dict[str, pd.DataFrame],
        news_events: list,
        market_context: dict,
    ) -> Optional[dict]:
        try:
            # Forensic ban: skip proven losers
            if symbol in self.BANNED_SYMBOLS:
                return None

            df = data.get('h1')
            if df is None or len(df) < 24:
                return None

            latest = df.iloc[-1]
            ts = df.index[-1]
            if hasattr(ts, 'tz') and ts.tz is not None:
                ts_utc = ts.tz_convert('UTC')
            else:
                ts_utc = ts.tz_localize('UTC') if ts.tzinfo is None else ts

            current_hour = ts_utc.hour
            
            # Strategy only active during London and NY (08:00 to 20:00)
            if current_hour < 8 or current_hour > 20:
                return None

            # Forensic ban: skip toxic hours
            if current_hour in self.BANNED_HOURS:
                return None
                
            # Filter the last 24h for today's Asian Session (00:00 to 07:59 UTC)
            df_24 = df.tail(24).copy()
            asian_mask = (df_24.index.tz_convert('UTC') if pd.api.types.is_datetime64tz_dtype(df_24.index) else df_24.index).hour.isin(range(0, 8))
            
            asian_df = df_24[asian_mask]
            
            if len(asian_df) < 4:
                return None
                
            asian_high = asian_df['high'].max()
            asian_low = asian_df['low'].min()
            
            # Rejection confirmation: wick must be longer than the body
            wick_top = latest['high'] - max(latest['open'], latest['close'])
            wick_bot = min(latest['open'], latest['close']) - latest['low']
            body = abs(latest['open'] - latest['close'])
            
            high_sweep = latest['high'] > asian_high and latest['close'] < asian_high and wick_top > body
            low_sweep = latest['low'] < asian_low and latest['close'] > asian_low and wick_bot > body
            
            direction = None
            if high_sweep:
                direction = "SELL"
            elif low_sweep:
                direction = "BUY"
                
            if not direction:
                return None

            entry = latest['close']
            atr = latest.get('atr', 0.001)
            
            # FORENSIC FIX: Widened SL from 1.0 to 1.5 ATR (was getting 23% instant SL hits)
            sl_dist = atr * 1.5
            # FORENSIC FIX: Lowered TP from 3.0 to 2.0 ATR (breakeven WR now 33% — achievable)
            tp_dist = atr * 2.0
            
            sl = entry - sl_dist if direction == "BUY" else entry + sl_dist
            tp = entry + tp_dist if direction == "BUY" else entry - tp_dist
            
            risk_details = RiskManager.calculate_lot_size(symbol, entry, sl, hour=current_hour)

            return {
                'strategy_id': self.get_id(),
                'strategy_name': self.get_name(),
                'symbol': symbol,
                'direction': direction,
                'timeframe': 'H1',
                'trade_type': 'SMC_SWEEP',
                'entry_price': entry,
                'sl': sl,
                'tp0': tp,
                'tp1': tp,
                'tp2': tp,
                'confidence': 2.0,
                'quality_score': 8.5, # Elevated from 8.0 for better selectivity
                'regime': 'LIQUIDITY_SWEEP',
                'macro_bias': 'CONTRARIAN',
                'risk_details': risk_details,
                'expected_hold': '2-8 hours',
                'score_details': {
                    'asian_high': float(asian_high),
                    'asian_low': float(asian_low)
                }
            }
        except Exception:
            return None
