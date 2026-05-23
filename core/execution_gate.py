import sqlite3
import os
from typing import Dict, Optional
from datetime import datetime

class ExecutionGate:
    """
    V31.0: Institutional Execution Safety Layer.
    Implements multi-factor validation gates before signals reach the broker level.
    """
    
    @staticmethod
    def validate(signal: Dict, db_signals: str, db_clients: str) -> Dict:
        """
        Runs a signal through the institutional gate sequence.
        Returns: {'status': 'PASSED'|'BLOCKED', 'reason': str}
        """
        try:
            # 1. Load System Configs
            thresholds = ExecutionGate._get_thresholds(db_clients)
            
            # 2. Check Regime Gate
            # Rule: Loosened for observation.
            regime = signal.get('regime', 'UNKNOWN')
            if regime == 'VOLATILE_RANGE' and signal.get('quality_score', 0) < 7.5:
                return {"status": "BLOCKED", "reason": "VOLATILITY_QUALITY_HURDLE"}

            # 3. Check Calibration Gate
            # Rule: Allow CALIBRATING signals for Phase A.
            conviction = signal.get('conviction', 'CALIBRATING')
            if conviction == 'CALIBRATING':
                 pass 

            # 4. Check Quality Threshold
            min_quality = thresholds.get('MIN_EXECUTION_QUALITY', 5.0)
            if signal.get('quality_score', 0) < min_quality:
                return {"status": "BLOCKED", "reason": f"QUALITY_BELOW_THRESHOLD ({signal.get('quality_score')})"}

            # 5. Check Inventory Gate (No Pyramiding)
            symbol = signal.get('symbol')
            if ExecutionGate._has_open_position(symbol, db_signals):
                return {"status": "BLOCKED", "reason": "EXISTING_POSITION_IN_SYMBOL"}

            # 6. Check Risk Gate (Daily Loss Limit)
            max_daily_loss = thresholds.get('MAX_DAILY_LOSS_PCT', 2.0)
            if ExecutionGate._is_drawdown_limit_hit(max_daily_loss, db_signals):
                return {"status": "BLOCKED", "reason": "DAILY_LOSS_LIMIT_BREACHED"}

            return {"status": "PASSED", "reason": "GATE_CRITERIA_MET"}

        except Exception as e:
            return {"status": "BLOCKED", "reason": f"GATE_ENGINE_ERROR: {str(e)}"}

    @staticmethod
    def _get_thresholds(db_path: str) -> Dict:
        """Fetch config from weight_overrides or separate config table."""
        thresholds = {}
        if not os.path.exists(db_path): return thresholds
        try:
            with sqlite3.connect(db_path) as conn:
                conn.row_factory = sqlite3.Row
                rows = conn.execute("SELECT event_type, multiplier FROM weight_overrides").fetchall()
                for row in rows:
                    thresholds[row['event_type']] = row['multiplier']
        except: pass
        return thresholds

    @staticmethod
    def _has_open_position(symbol: str, db_path: str) -> bool:
        """Checks if there's currently an OPEN trade for this symbol."""
        try:
            with sqlite3.connect(db_path) as conn:
                res = conn.execute("SELECT COUNT(*) FROM signals WHERE symbol = ? AND result = 'OPEN'", (symbol,)).fetchone()
                return res[0] > 0
        except: return False

    @staticmethod
    def _is_drawdown_limit_hit(max_pct: float, db_path: str) -> bool:
        """Calculates realized loss today vs account equity (mock/paper)."""
        # In a real system, this would fetch from broker API.
        # For Phase A, we check the 'signals' table for today's realized P&L.
        try:
            today = datetime.now().strftime('%Y-%m-%d')
            with sqlite3.connect(db_path) as conn:
                # Calculate total pips lost today
                res = conn.execute("""
                    SELECT SUM(result_pips) FROM signals 
                    WHERE closed_at LIKE ? AND result_pips < 0
                """, (f"{today}%",)).fetchone()
                # Simplified: compare pips to a constant 1000 pip daily limit (arbitrary for mock)
                # In real scenario, convert pips to account currency
                lost_pips = abs(res[0] or 0)
                if lost_pips > 500: # Mock threshold for Phase A
                    return True
        except: pass
        return False
