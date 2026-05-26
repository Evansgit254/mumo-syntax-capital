import sqlite3
import math
from datetime import datetime
from typing import Dict, Optional

class ExecutionGate:
    """
    Standardizes signal validation and inventory management.
    Ensures data integrity across live and simulated trading environments.
    """
    
    @staticmethod
    def validate(signal: Dict, db_signals: str, db_clients: str, 
                 table_name: str = 'signals', current_ts: Optional[datetime] = None) -> Dict[str, str]:
        """
        Validates a signal against institutional risk and inventory rules.
        """
        try:
            # 1. Load Configuration
            symbol = signal.get('symbol')
            if not symbol:
                return {"status": "BLOCKED", "reason": "MISSING_SYMBOL"}

            # 2. Inventory Check (No Pyramiding)
            if ExecutionGate._has_open_position(symbol, db_signals, table_name):
                return {"status": "BLOCKED", "reason": f"EXISTING_POSITION_IN_{symbol}"}

            # 3. Quality Assurance
            quality = signal.get('quality_score', 0.0)
            if math.isnan(quality):
                return {"status": "BLOCKED", "reason": "CORRUPT_SIGNAL_QUALITY (NaN)"}

            # 4. Threshold Validation
            thresholds = ExecutionGate._get_thresholds(db_clients)
            min_quality = thresholds.get('MIN_EXECUTION_QUALITY', 5.0)
            if quality < min_quality:
                return {"status": "BLOCKED", "reason": f"INSUFFICIENT_QUALITY ({quality:.2f})"}

            return {"status": "PASSED", "reason": "VALIDATION_SUCCESS"}

        except Exception as e:
            return {"status": "BLOCKED", "reason": f"GATE_SYSTEM_ERROR: {str(e)}"}

    @staticmethod
    def _has_open_position(symbol: str, db_path: str, table_name: str) -> bool:
        """Queries the signal database for active trades on the given symbol."""
        try:
            with sqlite3.connect(db_path) as conn:
                res = conn.execute(
                    f"SELECT COUNT(*) FROM {table_name} WHERE symbol = ? AND result = 'OPEN'", 
                    (symbol,)
                ).fetchone()
                return res[0] > 0 if res else False
        except:
            return False

    @staticmethod
    def _get_thresholds(db_path: str) -> Dict[str, float]:
        """Loads operational thresholds from the client configuration database."""
        thresholds = {}
        try:
            with sqlite3.connect(db_path) as conn:
                conn.row_factory = sqlite3.Row
                rows = conn.execute("SELECT weight_id, weight_value FROM weight_overrides").fetchall()
                for row in rows:
                    thresholds[row['weight_id']] = float(row['weight_value'])
        except:
            pass
        return thresholds
