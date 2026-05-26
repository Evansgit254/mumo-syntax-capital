from config.config import ACCOUNT_BALANCE, RISK_PER_TRADE_PERCENT, MIN_LOT_SIZE, USE_KELLY_SIZING
import pandas as pd
import sqlite3
import os
import numpy as np

class RiskManager:
    # Approximate pip values for 0.01 lot (1,000 units)
    # Most majors are $0.10 per pip for 0.01 lot
    # Fixed pip values per 0.01 lot (V9.0 Forensic Fix)
    PIP_VALUE_001 = {
        # Forex - Standard
        "EURUSD": 0.10,
        "GBPUSD": 0.10,
        "AUDUSD": 0.10,
        "USDCAD": 0.075,
        "NZDUSD": 0.10,
        "USDJPY": 0.065,
        "GBPJPY": 0.065,
        
        # Commodities - Per Contract
        "GC": 0.10,       # Gold Futures: $10 per 0.1 oz on 0.01 lot
        "XAUUSD": 0.10,   # Spot Gold: $1 per $1.00 move on 0.01 lot (Standard Retail)
        "CL": 0.001,      # Oil: $0.10 per $0.1 barrel on 0.01 lot (FIXED)
        
        # Crypto - Per Contract
        "BTC-USD": 0.0001,  # BTC: $0.01 per $1 move on 0.01 lot (FIXED)
        
        # Indices
        "GSPC": 0.05,
        "IXIC": 0.05
    }

    @staticmethod
    def calculate_lot_size(symbol: str, entry: float, sl: float, 
                           balance: float = None, 
                           risk_pct_override: float = None,
                           hour: int = None,
                           db_path="database/signals.db") -> dict:
        """
        Calculates the recommended lot size with dynamic scaling.
        Supports account balance and risk overrides for multi-client delivery.
        """
        import sqlite3
        import os
        
        # Use provided balance or fallback to global config
        current_balance = balance if balance is not None else ACCOUNT_BALANCE
        base_risk_pct = risk_pct_override if risk_pct_override is not None else RISK_PER_TRADE_PERCENT
        
        # V24.5 Forensic Alpha Scaling (Power Hours)
        # Audit (Run 24) showed 07:00 and 15:00 as massive outliers (>20R total)
        power_multiplier = 1.0
        if hour in [7, 15]:
            power_multiplier = 1.25 # Accelerate risk in proven high-alpha windows
            
        multiplier = 1.0 * power_multiplier
        
        # V7.0 Performance-Based Scaling
        if os.path.exists(db_path):
            try:
                conn = sqlite3.connect(db_path)
                # Get last 5 resolved trades
                query = "SELECT status FROM signals WHERE status IN ('WIN', 'LOSS', 'BREAKEVEN') ORDER BY timestamp DESC LIMIT 5"
                recent_trades = pd.read_sql_query(query, conn)['status'].tolist()
                conn.close()
                
                if recent_trades:
                    # Streak Logic
                    win_streak = 0
                    loss_streak = 0
                    for status in recent_trades:
                        if status == 'WIN': win_streak += 1
                        elif status == 'LOSS': loss_streak += 1
                        else: break # Break on breakeven
                    
                    if win_streak >= 3: 
                        multiplier = 1.25 # Reward 3+ wins
                    elif loss_streak >= 3:
                        multiplier = 0.50 # V12.0 Circuit Breaker: 50% Reduction after 3 losses
                    elif loss_streak >= 2: 
                        multiplier = 0.75 # Protect after 2 losses
            except:
                pass

        # V8.0: Kelly Criterion or Fixed Risk
        if USE_KELLY_SIZING and os.path.exists(db_path):
            kelly_fraction = RiskManager._calculate_kelly_fraction(db_path)
            if kelly_fraction > 0:
                # Use Kelly but cap at 2x base risk for safety
                risk_pct = min(base_risk_pct * kelly_fraction, base_risk_pct * 2.0)
            else:
                risk_pct = base_risk_pct
        else:
            risk_pct = base_risk_pct
        
        risk_amount = current_balance * (risk_pct / 100) * multiplier
        
        # Calculate SL distance in "pips" (V9.0 Forensic Fix)
        sl_distance = abs(entry - sl)
        
        # Normalization for different asset types
        if "JPY" in symbol:
            pips = sl_distance * 100  # 100 pips per 1.00 move
        elif "BTC" in symbol:
            pips = sl_distance  # $1 SL = 1 pip for BTC (FIXED)
        elif "CL" in symbol:
            pips = sl_distance * 10  # $1 SL = 10 pips for Oil (FIXED)
        elif "GC" in symbol or "XAU" in symbol or "GSPC" in symbol or "IXIC" in symbol:
            pips = sl_distance * 10  # $1 SL = 10 pips for Gold/Indices
        else:
            pips = sl_distance * 10000  # 10000 pips per 1.0000 move (FX)

        # Find pip value for this symbol
        key = symbol.replace("=X", "").replace("^", "")
        pip_val = RiskManager.PIP_VALUE_001.get(key, 0.10)
        
        if pips == 0: return {"lots": MIN_LOT_SIZE, "risk_cash": 0}

        # Calculation: (Risk Amount / (Pip Value 0.01 * Pips)) * 0.01
        recommended_lots = (risk_amount / (pip_val * pips)) * 0.01
        
        # Round to 2 decimal places and ensure minimum
        final_lots = max(round(recommended_lots, 2), MIN_LOT_SIZE)
        
        actual_risk = (final_lots / 0.01) * pip_val * pips
        actual_risk_pct = (actual_risk / current_balance) * 100
        
        
        # V9.0: Hard cap at 2% maximum risk per trade (Forensic Safety)
        MAX_RISK_PERCENT = 2.0
        if actual_risk_pct > MAX_RISK_PERCENT:
            # Recalculate lot size to meet cap: lots = (target_risk / (pip_val * pips)) * 0.01
            max_risk_amount = current_balance * (MAX_RISK_PERCENT / 100)
            final_lots = (max_risk_amount / (pip_val * pips)) * 0.01
            final_lots = max(round(final_lots, 2), MIN_LOT_SIZE)
            # Recalculate actual risk with capped lots
            actual_risk = (final_lots / 0.01) * pip_val * pips
            actual_risk_pct = (actual_risk / current_balance) * 100
        
        # V11.0 Guidance-Based Risk (Instead of Hard-Skip)
        GUIDE_THRESHOLD = 5.0
        # Calculate balance needed to keep risk at exactly 5% with minimum 0.01 lot
        min_balance_req = (pip_val * pips) / (GUIDE_THRESHOLD / 100)
        is_high_risk = actual_risk_pct > GUIDE_THRESHOLD

        return {
            'lots': final_lots,
            'risk_cash': round(actual_risk, 2),
            'risk_percent': round(actual_risk_pct, 1),
            'pips': round(pips, 1),
            'min_balance_req': round(min_balance_req, 2),
            'is_high_risk': is_high_risk
        }

    @staticmethod
    def calculate_layers(total_lots: float, entry: float, sl: float, direction: str, quality: str = "B") -> list:
        """
        Splits total lot size into strategic layers based on setup quality.
        """
        if quality == "A+":
            # A+ setups use aggressive "Load the Boat" layering
            # 50% Market, 30% Retest, 20% Extreme Retest
            l1_lots = max(MIN_LOT_SIZE, round(total_lots * 0.5, 2))
            l2_lots = max(MIN_LOT_SIZE, round(total_lots * 0.3, 2))
            l3_lots = max(MIN_LOT_SIZE, round(total_lots * 0.2, 2))
        else:
            # Standard setups use balanced layering
            # 40% (Market), 40% (Retest), 20% (Defensive)
            l1_lots = max(MIN_LOT_SIZE, round(total_lots * 0.4, 2))
            l2_lots = max(MIN_LOT_SIZE, round(total_lots * 0.4, 2))
            l3_lots = max(MIN_LOT_SIZE, round(total_lots * 0.2, 2))
        
        # Calculate Price Levels for Layers
        dist = abs(entry - sl)
        if direction == "BUY":
            l1_price = entry
            l2_price = entry - (dist * 0.3) # 30% pullback
            l3_price = entry - (dist * 0.6) # 60% deep retest
        else:
            l1_price = entry
            l2_price = entry + (dist * 0.3)
            l3_price = entry + (dist * 0.6)
            
        return [
            {'label': f'Aggressive Layer ({"50%" if quality=="A+" else "40%"})', 'price': l1_price, 'lots': l1_lots},
            {'label': f'Optimal Retest ({"30%" if quality=="A+" else "40%"})', 'price': l2_price, 'lots': l2_lots},
            {'label': 'Safety Layer (20%)', 'price': l3_price, 'lots': l3_lots}
        ]
    
    @staticmethod
    def _calculate_kelly_fraction(db_path: str, lookback: int = 50) -> float:
        """
        Calculates Kelly Criterion fraction based on historical win rate and avg win/loss.
        Returns fraction of capital to risk (0-1).
        """
        try:
            conn = sqlite3.connect(db_path)
            query = f"""
                SELECT status, r_multiple 
                FROM signals 
                WHERE status IN ('WIN', 'LOSS') 
                ORDER BY timestamp DESC 
                LIMIT {lookback}
            """
            trades = pd.read_sql_query(query, conn)
            conn.close()
            
            if len(trades) < 10:  # Need minimum data
                return 0.0
            
            wins = trades[trades['status'] == 'WIN']
            losses = trades[trades['status'] == 'LOSS']
            
            if len(losses) == 0:
                return 0.0
            
            win_rate = len(wins) / len(trades)
            avg_win = wins['r_multiple'].mean() if len(wins) > 0 else 0
            avg_loss = abs(losses['r_multiple'].mean()) if len(losses) > 0 else 1
            
            if avg_loss == 0:
                return 0.0
            
            # Kelly Formula: f = (p * b - q) / b
            # where p = win rate, q = loss rate, b = avg_win/avg_loss
            b = avg_win / avg_loss
            q = 1 - win_rate
            kelly = (win_rate * b - q) / b
            
            # Conservative Kelly: use fractional Kelly (25% of full Kelly)
            return max(0.0, min(kelly * 0.25, 0.1))  # Cap at 10% of capital
            
        except Exception:
            return 0.0
    
    @staticmethod
    def calculate_optimal_rr(symbol: str, quality_score: float, regime: str, current_atr: float) -> dict:
        """
        Calculates optimal Risk:Reward ratio based on signal quality and market regime.
        V14.1 Friction-Hardened Update (SATP)
        """
        from config.config import SPREAD_PIPS, SLIPPAGE_PIPS
        
        base_rr = 1.5  # Base R:R for intraday
        
        # Quality adjustment: higher quality = better R:R potential
        quality_multiplier = 1.0 + (quality_score - 5.0) / 10.0  # 0.5x to 1.5x
        
        # Regime adjustment (V14.5: 4-Cluster Optimization)
        regime_multiplier = {
            "TRENDING_BULL": 1.5,   # High-conviction trend
            "TRENDING_BEAR": 1.5,
            "VOLATILE_RANGE": 1.2,
            "LOW_VOL_RANGE": 1.3    # Boosted to ensure >1.5R in range extremes
        }.get(regime, 1.0)
        
        optimal_rr = base_rr * quality_multiplier * regime_multiplier
        
        # --- SATP: Spread-Adjusted Terminal Profit (V14.1) ---
        # Convert pips to price distance (Simplified normalization)
        friction_pips = SPREAD_PIPS + SLIPPAGE_PIPS
        if "JPY" in symbol: friction_dist = friction_pips / 100.0
        elif "BTC" in symbol: friction_dist = friction_pips # $1 = 1 pip
        elif "CL" in symbol or "GC" in symbol: friction_dist = friction_pips / 10.0
        else: friction_dist = friction_pips / 10000.0
        
        # Vol-Floor: If friction consumes > 35% of ATR, it's a "low-margin" death trap (V15.0)
        is_friction_heavy = friction_dist > (current_atr * 0.35)
        
        if is_friction_heavy:
            # Force skip by returning zero RR
            return {'tp1_rr': 0, 'tp2_rr': 0, 'tp3_rr': 0, 'is_friction_heavy': True}
        
        return {
            'tp1_rr': round(optimal_rr, 2),
            'tp2_rr': round(optimal_rr * 2.0, 2),
            'tp3_rr': round(optimal_rr * 3.5, 2),
            'is_friction_heavy': False
        }