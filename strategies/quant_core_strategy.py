from .base_strategy import BaseStrategy
from typing import Optional, Dict
import pandas as pd
from core.alpha_factors import AlphaFactors
from core.alpha_combiner import AlphaCombiner
from core.filters.risk_manager import RiskManager
from config.config import ATR_MULTIPLIER

class QuantCoreStrategy(BaseStrategy):
    def get_id(self) -> str:
        return "alpha_core_v1"

    def get_name(self) -> str:
        return "Alpha Core (Pure Quant)"

    async def analyze(self, symbol: str, data: Dict[str, pd.DataFrame], news_events: list, market_context: dict) -> Optional[dict]:
        try:
            df = data['m5']
            if len(df) < 100: return None
            
            # Benchmark for relative strength (defaults to DXY if not available)
            # In a production environment, this would be a proper sector benchmark.
            benchmark_df = data.get('d1') # Using D1 as a rough macro anchor for this iteration
            
            # 1. Calculate Mathematical Factors
            factors = {
                'velocity': AlphaFactors.velocity_alpha(df),
                'zscore': AlphaFactors.mean_reversion_zscore(df),
                'relative': 0.0 # Placeholder for sector analysis
            }
            
            # 2. Mathematical Aggregation
            alpha_signal = AlphaCombiner.combine(factors)
            
            # 3. Deterministic Decision Thresholds
            # |Signal| > 1.1 is considered a strong quant signal (Optimized v20.1)
            direction = None
            if alpha_signal > 1.1:
                direction = "BUY"
            elif alpha_signal < -1.1:
                direction = "SELL"
                
            if not direction:
                return None
                
            latest = df.iloc[-1]
            atr = latest['atr']
            
            # 4. Math-driven Execution Levels
            sl = latest['close'] - (atr * ATR_MULTIPLIER) if direction == "BUY" else latest['close'] + (atr * ATR_MULTIPLIER)
            risk_details = RiskManager.calculate_lot_size(symbol, latest['close'], sl)
            
            # V10.0 Hard-Skip Safety (Block if risk is dangerous for $50 account)
            if risk_details.get('skip_trade'):
                return None
            
            return {
                'strategy_id': self.get_id(),
                'strategy_name': self.get_name(),
                'symbol': symbol,
                'direction': direction,
                'setup_quality': "QUANT",
                'entry_price': latest['close'],
                'sl': sl,
                'tp0': latest['close'] + (atr * 1.5) if direction == "BUY" else latest['close'] - (atr * 1.5),
                'tp1': latest['close'] + (atr * 3.0) if direction == "BUY" else latest['close'] - (atr * 3.0),
                'tp2': latest['close'] + (atr * 5.0) if direction == "BUY" else latest['close'] - (atr * 5.0),
                'confidence': abs(alpha_signal),
                'quality_score': abs(alpha_signal) * 5.0, # Scale to 0-10
                'risk_details': risk_details,
                'session': "Quant Engine Live",
                'score_details': {
                    'velocity': factors['velocity'],
                    'zscore': factors['zscore'],
                    'signal': alpha_signal,
                    'direction': direction
                }
            }
        except Exception as e:
            return None
