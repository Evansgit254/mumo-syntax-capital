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
            self.logger.error("MetaTrader5 package not installed. Run 'pip install MetaTrader5' on Windows.")
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
        if self.paper_mode:
            self.logger.info(f"[PAPER] Simulating direct trade for {signal.get('symbol')}")
            return {"status": "PAPER_EXECUTED", "order_id": int(time.time())}

        if not self.initialized and not self.connect():
            return {"status": "FAILED", "reason": "CONNECTION_ERROR"}

        symbol = signal.get('symbol')
        # Handle XM/HFM suffixes (e.g. EURUSD# or EURUSD.m)
        from config.config import MT5_SYMBOL_SUFFIX
        if MT5_SYMBOL_SUFFIX and MT5_SYMBOL_SUFFIX not in symbol:
            symbol = symbol.replace("=X", "").replace("-USD", "") + MT5_SYMBOL_SUFFIX

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

    def close_connection(self):
        if self.initialized:
            mt5.shutdown()
            self.initialized = False
