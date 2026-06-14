import os
import time
import logging
from typing import Dict, Optional, List
from datetime import datetime

# Attempt to import MT5 (will only work on Windows)
try:
    import MetaTrader5 as mt5
    MT5_AVAILABLE = True
except ImportError:
    MT5_AVAILABLE = False

class DirectMT5Engine:
    """
    Native MetaTrader 5 Execution Engine.
    Bypasses MetaAPI for direct, low-latency execution on Windows systems.
    """

    def __init__(self, login: int, password: str, server: str, paper_mode: bool = True):
        self.login = login
        self.password = password
        self.server = server
        self.paper_mode = paper_mode
        self.initialized = False
        
        logging.basicConfig(level=logging.INFO)
        self.logger = logging.getLogger("DirectMT5")

    def connect(self) -> bool:
        """Initializes connection to the local MT5 terminal."""
        if not MT5_AVAILABLE:
            self.logger.debug("MetaTrader5 package not installed. Run 'pip install MetaTrader5' on Windows.")
            return False

        if not mt5.initialize(login=self.login, password=self.password, server=self.server):
            self.logger.error(f"MT5 Initialize failed: {mt5.last_error()}")
            return False
        
        self.initialized = True
        self.logger.info(f"Successfully connected to {self.server} (Account: {self.login})")
        return True

    def get_account_info(self) -> Optional[Dict]:
        """Fetches real-time balance and equity."""
        if not self.initialized and not self.connect():
            return None
        
        account_info = mt5.account_info()
        if account_info is None:
            return None
            
        return account_info._asdict()

    def execute_trade(self, signal: Dict) -> Dict:
        """
        Executes a trade directly on the terminal.
        """
        symbol = signal.get('symbol', '')
        # Map original symbol to broker symbol (e.g. EURUSD=X -> EURUSD)
        from core.trade_executor import SYMBOL_MAP
        base_sym = SYMBOL_MAP.get(symbol, symbol.replace("=X", "").replace("-", ""))
        from config.manager import config_manager
        suffix = config_manager.get("mt5_symbol_suffix", "")
        mapped_symbol = f"{base_sym}{suffix}"

        if self.paper_mode:
            self.logger.info(f"[PAPER] Simulating direct trade for {mapped_symbol}")
            return {
                "status": "PAPER_EXECUTED", 
                "order_id": int(time.time()),
                "symbol": mapped_symbol,
                "direction": signal.get('direction')
            }

        if not self.initialized and not self.connect():
            return {"status": "FAILED", "reason": "CONNECTION_ERROR"}

        symbol = mapped_symbol

        direction = signal.get('direction', '').upper()
        volume = float(signal.get('volume', 0.01))
        
        # Prepare Order Request
        order_type = mt5.ORDER_TYPE_BUY if direction == 'BUY' else mt5.ORDER_TYPE_SELL
        price = mt5.symbol_info_tick(symbol).ask if direction == 'BUY' else mt5.symbol_info_tick(symbol).bid
        
        sl = float(signal.get('sl', 0.0))
        tp = float(signal.get('tp1', 0.0))

        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": symbol,
            "volume": volume,
            "type": order_type,
            "price": price,
            "sl": sl,
            "tp": tp,
            "deviation": 20,
            "magic": 20260605, # Institutional Magic Number
            "comment": "SMC Native v5.3.2",
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_IOC,
        }

        # 1. Check for errors
        check = mt5.order_check(request)
        if check.retcode != mt5.TRADE_RETCODE_DONE:
            return {"status": "FAILED", "reason": f"CHECK_FAILED: {check.comment}"}

        # 2. Send the order
        result = mt5.order_send(request)
        if result.retcode != mt5.TRADE_RETCODE_DONE:
            self.logger.error(f"Trade Execution Failed: {result.comment}")
            return {"status": "FAILED", "reason": result.comment}

        self.logger.info(f"Direct Trade Executed: Order #{result.order} for {symbol}")
        return {
            "status": "LIVE_EXECUTED",
            "order_id": result.order,
            "price": result.price,
            "timestamp": datetime.now().isoformat()
        }

    def get_candles(self, symbol: str, timeframe: str, count: int = 500) -> Optional[List[Dict]]:
        """
        Fetches historical candles directly from the MT5 terminal.
        Expects symbol to be already mapped (e.g. including broker suffix).
        """
        if not self.initialized and not self.connect():
            return None

        # Map string timeframes to MT5 constants
        mt5_tf = {
            "1m": mt5.TIMEFRAME_M1, "5m": mt5.TIMEFRAME_M5, "15m": mt5.TIMEFRAME_M15,
            "1h": mt5.TIMEFRAME_H1, "4h": mt5.TIMEFRAME_H4, "1d": mt5.TIMEFRAME_D1
        }.get(timeframe, mt5.TIMEFRAME_H1)

        rates = mt5.copy_rates_from_pos(symbol, mt5_tf, 0, count)
        if rates is None or len(rates) == 0:
            self.logger.warning(f"Failed to fetch {timeframe} candles for {symbol}")
            return None

        return [{
            "time": datetime.fromtimestamp(r['time']).isoformat(),
            "open": float(r['open']),
            "high": float(r['high']),
            "low": float(r['low']),
            "close": float(r['close']),
            "tick_volume": int(r['tick_volume'])
        } for r in rates]

    def get_account_summary(self) -> Dict:
        """Fetches live account metrics directly from the terminal."""
        if not self.initialized and not self.connect():
            return {"balance": 0.0, "equity": 0.0}
            
        info = mt5.account_info()
        if info is None:
            return {"balance": 0.0, "equity": 0.0}
            
        return {
            "balance": float(info.balance),
            "equity": float(info.equity),
            "currency": info.currency,
            "broker": info.company
        }

    def modify_position_sl(self, ticket: int, symbol: str, new_sl: float) -> Dict:
        """
        Modifies the stop-loss of an open position on the broker side.
        Used by the Signal Tracker to lock profits at breakeven or trail stops.
        V5.4.4: Broker-Side Profit Lock
        """
        if self.paper_mode:
            self.logger.info(f"[PAPER] SL modify: ticket={ticket} {symbol} → SL={new_sl:.5f}")
            return {"status": "PAPER_MODIFIED", "ticket": ticket, "new_sl": new_sl}

        if not MT5_AVAILABLE:
            return {"status": "SKIPPED", "reason": "MT5_NOT_AVAILABLE"}

        if not self.initialized and not self.connect():
            return {"status": "FAILED", "reason": "CONNECTION_ERROR"}

        # Get the current position to read its TP
        positions = mt5.positions_get(ticket=ticket)
        if positions is None or len(positions) == 0:
            return {"status": "FAILED", "reason": f"POSITION_NOT_FOUND: ticket={ticket}"}

        position = positions[0]
        current_tp = position.tp
        current_sl = position.sl

        # Don't modify if new SL is worse than current SL
        if position.type == mt5.ORDER_TYPE_BUY:
            if new_sl <= current_sl and current_sl > 0:
                return {"status": "SKIPPED", "reason": "NEW_SL_WORSE_THAN_CURRENT"}
        else:  # SELL
            if new_sl >= current_sl and current_sl > 0:
                return {"status": "SKIPPED", "reason": "NEW_SL_WORSE_THAN_CURRENT"}

        request = {
            "action": mt5.TRADE_ACTION_SLTP,
            "position": ticket,
            "symbol": symbol,
            "sl": new_sl,
            "tp": current_tp,  # Keep existing TP
        }

        result = mt5.order_send(request)
        if result is None or result.retcode != mt5.TRADE_RETCODE_DONE:
            comment = result.comment if result else "No response"
            self.logger.error(f"SL Modify Failed: ticket={ticket} → {comment}")
            return {"status": "FAILED", "reason": comment}

        self.logger.info(f"✅ SL Modified: ticket={ticket} {symbol} SL={current_sl:.5f}→{new_sl:.5f}")
        return {
            "status": "LIVE_MODIFIED",
            "ticket": ticket,
            "old_sl": current_sl,
            "new_sl": new_sl,
            "timestamp": datetime.now().isoformat()
        }

    def get_open_positions(self, magic: int = 20260605) -> list:
        """
        Fetches all open positions placed by this system (filtered by magic number).
        Used by Signal Tracker to map DB signals to broker tickets.
        """
        if not MT5_AVAILABLE:
            return []

        if not self.initialized and not self.connect():
            return []

        positions = mt5.positions_get()
        if positions is None:
            return []

        return [
            {
                "ticket": p.ticket,
                "symbol": p.symbol,
                "type": "BUY" if p.type == mt5.ORDER_TYPE_BUY else "SELL",
                "volume": p.volume,
                "price_open": p.price_open,
                "sl": p.sl,
                "tp": p.tp,
                "profit": p.profit,
                "magic": p.magic,
                "comment": p.comment,
            }
            for p in positions
            if p.magic == magic
        ]

    def close_connection(self):
        if self.initialized:
            mt5.shutdown()
            self.initialized = False
