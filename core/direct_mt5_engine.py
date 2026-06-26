import os
import time
import logging
from typing import Dict, Optional, List
from datetime import datetime, timedelta

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
        self.last_connect_failure_at: Optional[datetime] = None
        self.last_connect_error: Optional[str] = None
        self.failure_backoff_seconds = int(os.getenv("MT5_CONNECT_FAILURE_BACKOFF_SECONDS", "60"))
        
        logging.basicConfig(level=logging.INFO)
        self.logger = logging.getLogger("DirectMT5")

    def connect(self) -> bool:
        """
        Initializes connection to the local MT5 terminal.
        Uses retry logic with cleanup between attempts to handle
        stale IPC handles common on Windows VPS/RDP environments.
        """
        if not MT5_AVAILABLE:
            self.logger.debug("MetaTrader5 package not installed. Run 'pip install MetaTrader5' on Windows.")
            return False

        if self.last_connect_failure_at:
            retry_at = self.last_connect_failure_at + timedelta(seconds=self.failure_backoff_seconds)
            if datetime.utcnow() < retry_at:
                self.logger.warning(
                    "MT5 connection skipped; previous failure is cooling down until %s",
                    retry_at.isoformat(timespec="seconds"),
                )
                return False

        # Detect Windows Admin privileges to diagnose UAC/IPC mismatches
        is_admin = False
        try:
            import ctypes
            is_admin = ctypes.windll.shell32.IsUserAnAdmin() != 0
        except Exception:
            pass
        self.logger.info(f"Python Process Administrator Status: {is_admin}")

        mt5_path = os.getenv("MT5_PATH")
        if mt5_path:
            mt5_path = mt5_path.strip().strip('"').strip("'")
            if not os.path.exists(mt5_path):
                self.logger.warning(f"MT5_PATH set but file not found: {mt5_path}")
                mt5_path = None

        max_retries = int(os.getenv("MT5_CONNECT_MAX_RETRIES", "3"))
        retry_delay = int(os.getenv("MT5_CONNECT_RETRY_DELAY_SECONDS", "5"))
        timeout_ms = int(os.getenv("MT5_CONNECT_TIMEOUT_MS", "60000"))

        for attempt in range(1, max_retries + 1):
            self.logger.info(f"MT5 connection attempt {attempt}/{max_retries}...")

            # Always shutdown first to clear any stale IPC handles
            try:
                mt5.shutdown()
            except Exception:
                pass
            
            if attempt > 1:
                self.logger.info(f"Waiting {retry_delay}s before retry...")
                time.sleep(retry_delay)

            # Strategy A: Default discovery (connect to already running terminal)
            try:
                self.logger.info("  → Strategy A: Trying default terminal discovery...")
                if mt5.initialize(timeout=timeout_ms):
                    self.initialized = True
                    acct = mt5.account_info()
                    if acct:
                        self.logger.info(f"✅ Connected via Strategy A to {acct.server} (Account: {acct.login}, Balance: {acct.balance})")
                    else:
                        self.logger.info(f"✅ Connected via Strategy A to MT5 terminal (no account info yet)")
                    return True
                else:
                    self.last_connect_error = str(mt5.last_error())
                    self.logger.warning(f"  → Strategy A failed: {self.last_connect_error}")
            except Exception as e:
                self.last_connect_error = str(e)
                self.logger.warning(f"  → Strategy A exception: {e}")

            # Strategy B: Open terminal via path (no credentials)
            if mt5_path:
                try:
                    mt5.shutdown()
                except Exception:
                    pass
                
                try:
                    self.logger.info(f"  → Strategy B: Trying path discovery ({mt5_path})...")
                    if mt5.initialize(path=mt5_path, timeout=timeout_ms):
                        self.initialized = True
                        acct = mt5.account_info()
                        if acct:
                            self.logger.info(f"✅ Connected via Strategy B to {acct.server} (Account: {acct.login}, Balance: {acct.balance})")
                        else:
                            self.logger.info(f"✅ Connected via Strategy B to MT5 terminal (no account info yet)")
                        return True
                    else:
                        self.last_connect_error = str(mt5.last_error())
                        self.logger.warning(f"  → Strategy B failed: {self.last_connect_error}")
                except Exception as e:
                    self.last_connect_error = str(e)
                    self.logger.warning(f"  → Strategy B exception: {e}")

            # Strategy C: Try to connect/login with explicit credentials
            try:
                mt5.shutdown()
            except Exception:
                pass

            try:
                self.logger.info(f"  → Strategy C: Trying with credentials (login={self.login}, server={self.server})...")
                init_args = {
                    "login": self.login,
                    "password": self.password,
                    "server": self.server,
                    "timeout": timeout_ms,
                }
                if mt5_path:
                    init_args["path"] = mt5_path

                if mt5.initialize(**init_args):
                    self.initialized = True
                    acct = mt5.account_info()
                    if acct:
                        self.logger.info(f"✅ Connected via Strategy C to {acct.server} (Account: {acct.login}, Balance: {acct.balance})")
                    else:
                        self.logger.info(f"✅ Connected via Strategy C to MT5 terminal (no account info yet)")
                    return True
                else:
                    self.last_connect_error = str(mt5.last_error())
                    self.logger.warning(f"  → Strategy C failed: {self.last_connect_error}")
            except Exception as e:
                self.last_connect_error = str(e)
                self.logger.warning(f"  → Strategy C exception: {e}")

        self.last_connect_failure_at = datetime.utcnow()
        self.logger.error(f"❌ MT5 connection failed after {max_retries} attempts. "
                         f"Checklist: (1) Is MT5 open and logged in? "
                         f"(2) Are both MT5 and this script running as the same user (both Admin or both normal)? "
                         f"(3) Kill all terminal64.exe in Task Manager and restart MT5 fresh.")
        return False


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
                "direction": signal.get('direction'),
                "volume": self._extract_volume(signal),
                "price": signal.get("entry_price"),
            }

        if not self.initialized and not self.connect():
            return {"status": "FAILED", "reason": "CONNECTION_ERROR"}

        symbol = mapped_symbol

        direction = signal.get('direction', '').upper()
        if direction not in {"BUY", "SELL"}:
            return {"status": "FAILED", "reason": "INVALID_DIRECTION"}
        try:
            volume = self._extract_volume(signal)
        except ValueError as exc:
            return {"status": "FAILED", "reason": str(exc)}
        
        # Prepare Order Request
        order_type = mt5.ORDER_TYPE_BUY if direction == 'BUY' else mt5.ORDER_TYPE_SELL
        tick = mt5.symbol_info_tick(symbol)
        if tick is None:
            return {"status": "FAILED", "reason": f"TICK_UNAVAILABLE: {symbol}"}
        price = tick.ask if direction == 'BUY' else tick.bid
        
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
        if check is None:
            return {"status": "FAILED", "reason": "CHECK_FAILED: no broker response"}
        if check.retcode != mt5.TRADE_RETCODE_DONE:
            return {"status": "FAILED", "reason": f"CHECK_FAILED: {check.comment}"}

        # 2. Send the order
        result = mt5.order_send(request)
        if result is None:
            return {"status": "FAILED", "reason": "ORDER_SEND_FAILED: no broker response"}
        if result.retcode != mt5.TRADE_RETCODE_DONE:
            self.logger.error(f"Trade Execution Failed: {result.comment}")
            return {"status": "FAILED", "reason": result.comment}

        self.logger.info(f"Direct Trade Executed: Order #{result.order} for {symbol}")
        return {
            "status": "LIVE_EXECUTED",
            "order_id": result.order,
            "price": result.price,
            "volume": volume,
            "timestamp": datetime.now().isoformat()
        }

    def _extract_volume(self, signal: Dict) -> float:
        raw_volume = (
            signal.get("volume")
            or signal.get("lot_size")
            or signal.get("requested_lot_size")
            or (signal.get("risk_details") or {}).get("lots")
            or (signal.get("risk_details") or {}).get("lot_size")
        )
        if raw_volume is None:
            raise ValueError("MISSING_LOT_SIZE")
        volume = float(raw_volume)
        if volume <= 0:
            raise ValueError("INVALID_LOT_SIZE")
        return round(volume, 2)

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
