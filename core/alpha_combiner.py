import sqlite3
import json
import os
import math
import pandas as pd
from typing import Dict, Optional, List
from .alpha_factors import AlphaFactors

class AlphaCombiner:
    @staticmethod
    def combine(factors: Dict[str, float], forensic_events: List[Dict] = None, regime: str = "NORMAL", symbol: Optional[str] = None) -> float:
        """
        Pure Mathematical Aggregator with Regime + Symbol Adaptation.
        V29.0: Incorporates Dynamic Forensic Multipliers.
        """
        from config.config import SYMBOL_ALPHA_WEIGHTS

        # 1. Base weights from regime/symbol
        sym_weights = SYMBOL_ALPHA_WEIGHTS.get(symbol, {}).get(regime) if symbol else None
        weights = sym_weights if sym_weights else AlphaCombiner._get_fallback_weights(regime)

        # 2. Calculate Base Signal
        total_signal = 0.0
        for name, value in factors.items():
            weight = weights.get(name, 0.0)
            clipped_value = max(min(value, 4.0), -4.0)
            total_signal += clipped_value * weight

        # 3. Apply Institutional Forensic Multiplier (Dynamic)
        if forensic_events:
            multiplier = AlphaCombiner.get_forensic_multiplier(forensic_events)
            total_signal *= multiplier

        return round(total_signal, 4)

    @staticmethod
    def _get_fallback_weights(regime: str) -> Dict[str, float]:
        if regime in ["TRENDING_BULL", "TRENDING_BEAR"]:
            return {'velocity': 0.7, 'zscore': 0.1, 'momentum': 0.2, 'volatility': 0.0}
        elif regime == "VOLATILE_RANGE":
            return {'velocity': 0.3, 'zscore': 0.5, 'momentum': 0.1, 'volatility': 0.1}
        else: # LOW_VOL_RANGE or fallback
            return {'velocity': 0.4, 'zscore': 0.5, 'momentum': 0.05, 'volatility': 0.05}

    @staticmethod
    def detect_regime(df: pd.DataFrame) -> str:
        """
        V35.0: Relays to Unified Core Registry.
        """
        from core.market_regime import detect_regime
        return detect_regime(df)['regime']

    @staticmethod
    def calculate_wilson_interval(p: float, n: int, confidence: float = 0.95) -> Dict[str, float]:
        """
        V29.1: Calculates the Wilson score interval (CI) for binomial proportion.
        More robust than normal approximation for small samples and extreme rates.
        """
        if n == 0: return {"lower": 0.0, "upper": 0.0}
        
        z = 1.96 # Approx for 95% confidence
        upscale = 1 + (z**2 / n)
        adj_p = p + (z**2 / (2 * n))
        spread = z * math.sqrt((p * (1 - p) / n) + (z**2 / (4 * n**2)))
        
        return {
            "lower": round(max(0.0, (adj_p - spread) / upscale) * 100, 1),
            "upper": round(min(1.0, (adj_p + spread) / upscale) * 100, 1)
        }

    @staticmethod
    def get_forensic_multiplier(events: List[Dict], regime: str = "NORMAL") -> float:
        """
        V30.0: Hardened dynamic multiplier with Regime-Aware filtering.
        """
        try:
            # 1. Build combination string
            event_types = sorted([e.get('type') for e in events if e.get('type')])
            combination = " + ".join(event_types)
            if not combination: return 1.0

            # 2. Fetch System Configuration (Thresholds)
            multiplier = 1.0
            from config.config import DB_CLIENTS, DB_SIGNALS
            conf_db = DB_CLIENTS
            db_path = DB_SIGNALS
            
            # Add regime context to the combination for audit lookup
            # This allows the combiner to scale weights based on (regime + combination)
            regime_combination = f"[{regime}] {combination}"
            
            threshold = 30 # Default hardening
            if os.path.exists(conf_db):
                with sqlite3.connect(conf_db) as conn:
                    val = conn.execute("SELECT multiplier FROM weight_overrides WHERE event_type = 'SYSTEM_THRESHOLD'").fetchone()
                    if val: threshold = int(val[0])

            # 3. Fetch Audit Data (Systematic Calibration)
            if os.path.exists(db_path):
                with sqlite3.connect(db_path) as conn:
                    conn.row_factory = sqlite3.Row
                    # Attempt look-up with regime context first
                    stats = conn.execute("""
                        SELECT 
                            COUNT(*) as count,
                            AVG(CASE WHEN result_pips > 0 THEN 1 ELSE 0 END) as win_rate
                        FROM signals 
                        WHERE regime = ? AND forensic_events LIKE ?
                    """, (regime, f"%{combination}%")).fetchone()

                    # Fallback to general combination if regime-specific sample size is too low
                    if not stats or stats['count'] < threshold:
                        stats = conn.execute("""
                            SELECT 
                                COUNT(*) as count,
                                AVG(CASE WHEN result_pips > 0 THEN 1 ELSE 0 END) as win_rate
                            FROM signals 
                            WHERE forensic_events LIKE ?
                        """, (f"%{combination}%",)).fetchone()

                    if stats and stats['count'] >= threshold:
                        wr = stats['win_rate'] * 100
                        if wr >= 60: multiplier = 1.5
                        elif wr < 45: multiplier = 0.6
                    else:
                        multiplier = 1.0

            # 4. Apply Manual Overrides (Control Panel)
            if os.path.exists(conf_db):
                with sqlite3.connect(conf_db) as conn:
                    conn.row_factory = sqlite3.Row
                    overrides = conn.execute("SELECT * FROM weight_overrides WHERE is_active = 1").fetchall()
                    for ov in overrides:
                        if ov['event_type'] in combination:
                            multiplier *= ov['multiplier']
                        # Regime specific overrides
                        if ov['event_type'] == f"REGIME_{regime}":
                            multiplier *= ov['multiplier']

            return round(multiplier, 2)
        except Exception as e:
            print(f"AlphaCombiner Multiplier Error: {e}")
            return 1.0

    
    @staticmethod
    def calculate_quality_score(factors: Dict[str, float], signal: float, base_boost: float = 0.0) -> float:
        """
        Calculates signal quality score (0-10) based on factor alignment and institutional context.
        Higher quality = better R:R potential.
        """
        # Factor alignment: all factors pointing same direction = higher quality
        # V33.1: Soften alignment penalty for institutional reversal setups
        factor_values = [v for v in factors.values() if v != 0]
        if not factor_values:
            return round(base_boost, 2)
        
        # Check alignment (all same sign = high quality)
        signs = [1 if v > 0 else -1 for v in factor_values]
        alignment = 1.0 if len(set(signs)) == 1 else 0.6  # Boosted from 0.5 to reduce reversal penalty
        
        # Signal strength component
        signal_strength = min(abs(signal) / 2.0, 1.0)  # Normalize to 0-1
        
        # Combined quality score (0-10)
        # base_boost allows strategies like CRT to inject institutional confidence
        quality = (alignment * 5.0 + signal_strength * 3.0 + (base_boost * 0.2))
        return round(min(quality, 10.0), 2)