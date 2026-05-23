from .base_strategy import BaseStrategy
from typing import Optional, Dict
import pandas as pd
from datetime import datetime
from core.filters.risk_manager import RiskManager
from core.filters.macro_filter import MacroFilter
from core.filters.news_filter import NewsFilter
from indicators.calculations import IndicatorCalculator
from config.config import MIN_QUALITY_SCORE
from core.alpha_factors import AlphaFactors
from core.alpha_combiner import AlphaCombiner


class CRTStrategy(BaseStrategy):
    """
    Candle Range Theory (CRT) Strategy — V5.0 (High-Frequency Institutional release)
    ================================================================================
    Optimized for high-conviction institutional trades and daily signal accumulation.
    """

    def get_id(self) -> str:
        return "crt_h1"

    def get_name(self) -> str:
        return "Candle Range Theory (H1)"

    async def analyze(
        self,
        symbol: str,
        data: Dict[str, pd.DataFrame],
        news_events: list,
        market_context: dict,
    ) -> Optional[dict]:
        try:
            df_h1  = data.get("h1")
            df_d1  = data.get("d1")
            df_m5  = data.get("m5")
            df_m15 = data.get("m15")

            if df_h1 is None or len(df_h1) < 20:
                return None

            # Determine entry timeframe and scan depth
            if df_m5 is not None and not df_m5.empty:
                df_entry = df_m5
                scan_count = 48  # 4 hours
            elif df_m15 is not None and not df_m15.empty:
                df_entry = df_m15
                scan_count = 16
            else:
                return None

            # Forensic Event Logger
            forensic_events = []
            def log_event(type: str, message: str, bar_offset: int = 0, price: float = None):
                forensic_events.append({
                    "type": type, "message": message, "bar_offset": bar_offset,
                    "price": price, "time": datetime.now().isoformat()
                })

            # ─── 1. Daily Bias ──────────────────────────────────────────────────
            daily_bias = None 
            if df_d1 is not None and len(df_d1) >= 6:
                d1_last = df_d1.iloc[-1]
                d1_close = d1_last.get("close", 0)
                d1_open  = d1_last.get("open", 0)
                d1_ema   = d1_last.get("ema_trend") or d1_last.get("ema_200")
                if d1_close and d1_ema:
                    if d1_close > d1_ema and d1_close > d1_open:
                        daily_bias = "BUY"
                    elif d1_close < d1_ema and d1_close < d1_open:
                        daily_bias = "SELL"
            
            log_event("DAILY_BIAS", f"D1 Order Flow: {daily_bias or 'NEUTRAL'}")

            # ─── 2. Institutional Reference (Previous H1) ───────────────────────
            ref_h1     = df_h1.iloc[-2]
            ref_high   = ref_h1["high"]
            ref_low    = ref_h1["low"]
            ref_eq     = (ref_high + ref_low) / 2.0
            range_size = ref_high - ref_low
            
            # ─── 3. ICT Killzone Filter ─────────────────────────────────────────
            timestamp = df_h1.index[-1]
            if hasattr(timestamp, "hour"):
                hour = timestamp.hour
                if not (7 <= hour < 12 or 12 <= hour < 18):
                    return None
            else:
                return None

            # ─── 4. High-Frequency Scan Window ─────────────────────────────────
            scan_bars = df_entry.iloc[-scan_count:]
            if len(scan_bars) < 6:
                return None

            m5_highs  = scan_bars["high"].values
            m5_lows   = scan_bars["low"].values
            m5_closes = scan_bars["close"].values

            direction     = None
            entry_price   = None
            sweep_extreme = None

            for j in range(3, len(scan_bars)):
                c_high, c_low, c_close = m5_highs[j], m5_lows[j], m5_closes[j]
                
                prev_highs = m5_highs[:j]
                prev_lows  = m5_lows[:j]
                
                # BULLISH MSS: Sweep low + close back inside
                swept_lows = [l for l in prev_lows if l < ref_low]
                if swept_lows and c_close > ref_low:
                    direction, entry_price, sweep_extreme = "BUY", c_close, min(swept_lows)
                    break

                # BEARISH MSS: Sweep high + close back inside
                swept_highs = [h for h in prev_highs if h > ref_high]
                if swept_highs and c_close < ref_high:
                    direction, entry_price, sweep_extreme = "SELL", c_close, max(swept_highs)
                    break

            if not direction or entry_price is None or sweep_extreme is None:
                return None

            # ─── 5. SL Placement (Institutional Extreme) ────────────────────────
            if direction == "BUY":
                sl = sweep_extreme - (range_size * 0.05)
                tp0, tp1, tp2 = ref_eq, ref_high, ref_high + (ref_high - ref_eq)
                if not (entry_price < tp1): return None
            else:
                sl = sweep_extreme + (range_size * 0.05)
                tp0, tp1, tp2 = ref_eq, ref_low, ref_low - (ref_eq - ref_low)
                if not (entry_price > tp1): return None

            risk = abs(entry_price - sl)
            if risk <= 0: return None

            # ─── 6. EMA200 Trend Filter (Production Grade) ─────────────────────
            latest_h1 = df_h1.iloc[-1]
            ema_200 = latest_h1.get("ema_200") or latest_h1.get("ema_trend")
            trend_aligned = True
            if ema_200 and ema_200 > 0:
                if direction == "BUY" and entry_price < ema_200 * 0.995: trend_aligned = False
                if direction == "SELL" and entry_price > ema_200 * 1.005: trend_aligned = False
            
            # V33.2: Re-enable EMA filter but allow tight sweeps near EMA
            if not trend_aligned:
                log_event("FILTER_BLOCKED", "Counter-trend entry too far from EMA200")
                return None

            # ─── 7. Alpha Combiner & Scoring ────────────────────────────────────
            detected_regime = AlphaCombiner.detect_regime(df_h1)
            factors = {
                "velocity": AlphaFactors.velocity_alpha(df_h1),
                "zscore": AlphaFactors.mean_reversion_zscore(df_h1),
                "momentum": AlphaFactors.momentum_alpha(df_h1),
                "volatility": AlphaFactors.volatility_regime_alpha(df_h1)
            }
            signal_value = AlphaCombiner.combine(factors, forensic_events=forensic_events, regime=detected_regime, symbol=symbol)
            
            # Calculate Base Boost from ICT confluence
            # Boost if sweep was deep (> 0.5 * H1 range) or if displacement was strong
            base_boost = 3.5  # Starting base for a valid CRT setup
            if abs(entry_price - sweep_extreme) > (range_size * 0.5):
                base_boost += 1.5
                log_event("CONFLUENCE", "Deep swept detected (+1.5 boost)")

            quality_score = AlphaCombiner.calculate_quality_score(factors, signal_value, base_boost=base_boost)

            if quality_score < MIN_QUALITY_SCORE:
                log_event("FILTER_BLOCKED", f"Quality Score {quality_score} < {MIN_QUALITY_SCORE}")
                return None

            # ─── 8. Risk & Results ──────────────────────────────────────────────
            risk_details = RiskManager.calculate_lot_size(symbol, entry_price, sl)

            return {
                "strategy_id": self.get_id(), "strategy_name": self.get_name(),
                "symbol": symbol, "direction": direction, "trade_type": "CRT",
                "entry_price": round(entry_price, 5), "sl": round(sl, 5),
                "tp0": round(tp0, 5), "tp1": round(tp1, 5), "tp2": round(tp2, 5),
                "quality_score": quality_score, "regime": detected_regime,
                "risk_details": risk_details, "forensic_events": forensic_events
            }

        except Exception as e:
            print(f"CRT Error: {e}")
            return None
