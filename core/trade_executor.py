"""
MT5 Auto-Trade Executor — V5.4.2 [NATIVE ONLY]
Direct, high-speed execution via local MetaTrader 5 terminal.
All cloud-bridge (MetaAPI) dependencies have been purged.
"""

import json
import sqlite3
import asyncio
from datetime import datetime, timedelta
from typing import Optional, Dict, List

from config.manager import config_manager
from core.db_utils import connect_sqlite
from core.direct_mt5_engine import DirectMT5Engine

# Symbol mapping: yfinance → MT5 broker symbol
SYMBOL_MAP = {
    "EURUSD=X": "EURUSD",
    "GBPUSD=X": "GBPUSD",
    "NZDUSD=X": "NZDUSD",
    "USDJPY=X": "USDJPY",
    "AUDUSD=X": "AUDUSD",
    "GBPJPY=X": "GBPJPY",
    "GC=F":     "XAUUSD",
    "CL=F":     "USOIL",
    "BTC-USD":  "BTCUSD",
}


class TradeExecutor:
    """
    Executes trades directly on the local MT5 terminal.
    Bypasses all cloud bridges for institutional speed and reliability.
    """

    def __init__(self):
        settings = config_manager.snapshot()
        self.paper_mode = settings.mt5_paper_mode
        self.auto_trade = settings.mt5_auto_trade
        
        # Native Engine for Direct Execution
        self._direct_engine = DirectMT5Engine(
            login=settings.mt5_login,
            password=settings.mt5_password,
            server=settings.mt5_server,
            paper_mode=settings.mt5_paper_mode
        )

    def _load_runtime_config(self):
        settings = config_manager.refresh()
        self.paper_mode = settings.mt5_paper_mode
        self.auto_trade = settings.mt5_auto_trade

    def _map_symbol(self, yf_symbol: str) -> str:
        base_sym = SYMBOL_MAP.get(yf_symbol, yf_symbol.replace("=X", "").replace("-", ""))
        return f"{base_sym}{config_manager.get('mt5_symbol_suffix')}"

    def _log_paper_trade(self, action: str, signal_data: dict, result: dict):
        """Write paper trade to DB for tracking."""
        try:
            conn = connect_sqlite(config_manager.get("db_signals"))
            conn.execute("""
                UPDATE signals SET
                    status = ?,
                    execution_status = ?,
                    fill_price = ?,
                    filled_lot_size = ?,
                    score_details = json_patch(COALESCE(score_details,'{}'), ?)
                WHERE (id = ? OR signal_uid = ? OR (symbol = ? AND timestamp = ?))
            """, (
                "PAPER_EXECUTED",
                "PAPER_EXECUTED",
                signal_data.get("entry_price"),
                result.get("lot_size"),
                json.dumps({"mt5_action": action, "paper_result": result}),
                signal_data.get("id"),
                signal_data.get("signal_uid"),
                signal_data.get("symbol"),
                signal_data.get("timestamp")
            ))
            conn.commit()
            conn.close()
        except Exception as e:
            print(f"⚠️  Paper log failed: {e}")

    async def execute_trade(self, signal_data: dict) -> dict:
        """
        Main execution entry point. Dispatches to Native Engine.
        """
        self._load_runtime_config()
        if not self.auto_trade:
            return {"status": "skipped", "reason": "MT5_AUTO_TRADE=false"}

        symbol = signal_data.get("symbol")
        
        # 1. Check for live readiness
        if not self.paper_mode:
            errors = await self._live_readiness_errors(symbol)
            if errors:
                res = {"status": "blocked", "reason": "; ".join(errors)}
                self._persist_execution_state(signal_data, res)
                return res

        # 2. Prevent execution if core data is missing
        if not signal_data.get("entry_price"):
            res = {"status": "error", "reason": "missing entry_price"}
            self._persist_execution_state(signal_data, res)
            return res

        # Always use the native engine - Purged MetaAPI checks
        print("🚀 [DIRECT MT5] Dispatching to Native Engine...")
        return self._direct_engine.execute_trade(signal_data)

    async def get_open_positions(self) -> List[Dict]:
        """Fetch all open positions from MT5."""
        self._load_runtime_config()
        
        # Native fetch logic only
        import MetaTrader5 as mt5_lib
        if not self._direct_engine.initialized and not self._direct_engine.connect():
            return []
        
        positions = mt5_lib.positions_get()
        if positions is None:
            return []
        
        return [
            {
                "id": p.ticket,
                "symbol": p.symbol,
                "direction": "BUY" if p.type == 0 else "SELL",
                "lot_size": float(p.volume),
                "open_price": float(p.price_open),
                "current_price": float(p.price_current),
                "profit": float(p.profit),
                "sl": float(p.sl),
                "tp": float(p.tp),
                "open_time": p.time
            } for p in positions
        ]

    async def close_trade(self, position_id: str) -> dict:
        """Close an open position."""
        self._load_runtime_config()
        
        # Native close logic only
        import MetaTrader5 as mt5_lib
        if not self._direct_engine.initialized and not self._direct_engine.connect():
            return {"status": "error", "reason": "MT5 Not Initialized"}
        
        pos = mt5_lib.positions_get(ticket=int(position_id))
        if not pos: return {"status": "error", "reason": "Position not found"}
        p = pos[0]
        
        order_type = mt5_lib.ORDER_TYPE_SELL if p.type == 0 else mt5_lib.ORDER_TYPE_BUY
        price = mt5_lib.symbol_info_tick(p.symbol).bid if p.type == 0 else mt5_lib.symbol_info_tick(p.symbol).ask
        
        request = {
            "action": mt5_lib.TRADE_ACTION_DEAL,
            "symbol": p.symbol,
            "volume": p.volume,
            "type": order_type,
            "position": p.ticket,
            "price": price,
            "deviation": 20,
            "magic": 20260605,
            "comment": "Native close",
            "type_time": mt5_lib.ORDER_TIME_GTC,
            "type_filling": mt5_lib.ORDER_FILLING_IOC,
        }
        result = mt5_lib.order_send(request)
        if result.retcode != mt5_lib.TRADE_RETCODE_DONE:
            return {"status": "error", "reason": result.comment}
        return {"status": "closed", "position_id": position_id}

    async def get_historical_data(self, symbol: str, timeframe: str, limit: int = 100) -> Optional[List[Dict]]:
        """ Fetch candles directly from MT5. """
        mt5_sym = self._map_symbol(symbol)
        candles = self._direct_engine.get_candles(mt5_sym, timeframe, limit)
        if not candles:
            return None
        return [
            {
                "timestamp": datetime.fromisoformat(c['time']).timestamp(),
                "open": c['open'],
                "high": c['high'],
                "low": c['low'],
                "close": c['close'],
                "volume": c.get('tick_volume', 0)
            } for c in candles
        ]

    async def get_latest_tick(self, symbol: str) -> Optional[Dict]:
        """ Get real-time bid/ask from MT5. """
        import MetaTrader5 as mt5_lib
        if not self._direct_engine.initialized and not self._direct_engine.connect():
            return None
            
        mt5_sym = self._map_symbol(symbol)
        tick = mt5_lib.symbol_info_tick(mt5_sym)
        if tick is None:
            return None
            
        return {
            "bid": tick.bid,
            "ask": tick.ask,
            "time": tick.time
        }

    def _persist_execution_state(self, signal_data: dict, state: dict):
        try:
            patch = state.pop("score_details_patch", None)
            set_parts = []
            values = []
            for col, value in state.items():
                if col == "score_details_patch":
                    continue
                set_parts.append(f"{col} = ?")
                values.append(value)
            if patch is not None:
                set_parts.append("score_details = json_patch(COALESCE(score_details,'{}'), ?)")
                values.append(json.dumps(patch, default=str))
            if not set_parts:
                return
            values.extend([
                signal_data.get("id"),
                signal_data.get("signal_uid"),
                signal_data.get("symbol"),
                signal_data.get("timestamp"),
            ])
            with connect_sqlite(config_manager.get("db_signals")) as conn:
                self._ensure_execution_events(conn)
                conn.execute(f"""
                    UPDATE signals SET {", ".join(set_parts)}
                    WHERE id = ? OR signal_uid = ? OR (symbol = ? AND timestamp = ?)
                """, values)
                conn.execute("""
                    INSERT INTO execution_events (
                        signal_id, signal_uid, symbol, event_type, state_json, created_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (
                    signal_data.get("id"),
                    signal_data.get("signal_uid"),
                    signal_data.get("symbol"),
                    state.get("execution_status") or state.get("status") or "STATE_UPDATE",
                    json.dumps(state, default=str),
                    datetime.utcnow().isoformat(),
                ))
                conn.commit()
        except Exception as e:
            print(f"⚠️  Execution state persist failed: {e}")

    def _ensure_execution_events(self, conn):
        from core.db_utils import ensure_base_tables
        ensure_base_tables(conn)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS execution_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                signal_id INTEGER,
                signal_uid TEXT,
                symbol TEXT,
                event_type TEXT,
                state_json TEXT,
                created_at TEXT
            )
        """)

    async def _live_readiness_errors(self, symbol: str) -> List[str]:
        settings = config_manager.refresh()
        errors = []
        if not settings.live_trading_approved:
            errors.append("live_trading_approved=false")
        if not symbol:
            errors.append("symbol missing")
        return errors

# Global singleton
_executor = None

def get_executor():
    global _executor
    if _executor is None:
        _executor = TradeExecutor()
    return _executor
