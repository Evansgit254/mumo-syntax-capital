"""
MT5 Auto-Trade Executor — V1.0
Uses MetaAPI (metaapi.cloud) REST bridge — Linux compatible.

Setup:
  1. pip install metaapi-cloud-sdk
  2. Set in .env:
       METAAPI_TOKEN=your_token_here
       METAAPI_ACCOUNT_ID=your_account_id_here
       MT5_AUTO_TRADE=true
       MT5_PAPER_MODE=true   ← set to false only after paper testing

Paper Mode (default=true): logs trades to console/DB without placing real orders.
"""

import json
import sqlite3
import asyncio
from datetime import datetime, timedelta
from typing import Optional, Dict, List

from config.config import (
    METAAPI_TOKEN, METAAPI_ACCOUNT_ID,
    MT5_AUTO_TRADE, MT5_PAPER_MODE, DB_SIGNALS
)
from core.secure_config import reveal_config_value
from core.db_utils import connect_sqlite

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
    Executes trades on MT5 via MetaAPI REST bridge.
    Falls back to paper logging when MT5_PAPER_MODE=true or MetaAPI is not configured.
    """

    def __init__(self):
        self.paper_mode = MT5_PAPER_MODE
        self.auto_trade = MT5_AUTO_TRADE
        self._api = None
        self._account = None
        self._account_id = None
        self._token_hash = None
        self._connect_lock = asyncio.Lock()

    def _get_db_config(self, key: str) -> Optional[str]:
        """Fetch config from system_config table."""
        from config.config import DB_CLIENTS
        try:
            conn = connect_sqlite(DB_CLIENTS)
            row = conn.execute("SELECT value FROM system_config WHERE key = ?", (key,)).fetchone()
            conn.close()
            return reveal_config_value(key, row[0]) if row else None
        except Exception:
            return None

    def _load_runtime_config(self):
        paper_conf = self._get_db_config("mt5_paper_mode")
        if paper_conf is not None:
            self.paper_mode = str(paper_conf).lower() == "true"
        auto_conf = self._get_db_config("mt5_auto_trade")
        if auto_conf is not None:
            self.auto_trade = str(auto_conf).lower() == "true"

    def _get_credentials(self):
        token = METAAPI_TOKEN or self._get_db_config("metaapi_token")
        account_id = METAAPI_ACCOUNT_ID or self._get_db_config("metaapi_account_id")
        return token, account_id

    def _has_live_credentials(self) -> bool:
        token, account_id = self._get_credentials()
        return bool(token and account_id)

    async def _connect(self):
        """Lazy-connect to MetaAPI. Only called when a trade is needed."""
        self._load_runtime_config()
        token, account_id = self._get_credentials()
        token_hash = str(hash(token)) if token else None

        if self._api is not None and self._account is not None and self._account_id == account_id and self._token_hash == token_hash:
            return True

        async with self._connect_lock:
            if self._api is not None and self._account is not None and self._account_id == account_id and self._token_hash == token_hash:
                return True

            if not token or not account_id:
                print("⚠️  TradeExecutor: MetaAPI credentials not found in ENV or DB. Running in PAPER mode.")
                self.paper_mode = True
                return False

            try:
                from metaapi_cloud_sdk import MetaApi
                api = MetaApi(token)
                account = await api.metatrader_account_api.get_account(account_id)
                state = account.state
                if state not in ['DEPLOYING', 'DEPLOYED']:
                    await account.deploy()
                await account.wait_connected()
                self._api = api
                self._account = account
                self._account_id = account_id
                self._token_hash = token_hash
                print(f"✅ TradeExecutor: Connected to MetaAPI account {account_id}")
                return True
            except ImportError:
                print("⚠️  TradeExecutor: metaapi-cloud-sdk not installed. Run: pip install metaapi-cloud-sdk")
                self.paper_mode = True
                return False
            except Exception as e:
                self._api = None
                self._account = None
                print(f"❌ TradeExecutor: MetaAPI connection failed: {e}")
                return False

    def _map_symbol(self, yf_symbol: str) -> str:
        from config.config import MT5_SYMBOL_SUFFIX
        base_sym = SYMBOL_MAP.get(yf_symbol, yf_symbol.replace("=X", "").replace("-", ""))
        return f"{base_sym}{MT5_SYMBOL_SUFFIX}"

    def _log_paper_trade(self, action: str, signal_data: dict, result: dict):
        """Write paper trade to DB for tracking."""
        try:
            conn = connect_sqlite(DB_SIGNALS)
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
        Place a market order based on a signal dict.
        Returns a result dict with order_id, fill_price, status.

        Paper mode: logs to console + DB but places no real order.
        """
        self._load_runtime_config()
        if not self.auto_trade:
            return {"status": "skipped", "reason": "MT5_AUTO_TRADE=false"}

        symbol    = signal_data.get("symbol", "")
        direction = signal_data.get("direction", "BUY").upper()
        lot_size  = signal_data.get("lot_size", 0.01)
        sl        = signal_data.get("sl")
        tp        = signal_data.get("tp1")  # Use TP1 as conservative target
        mt5_sym   = self._map_symbol(symbol)
        order_type = "ORDER_TYPE_BUY" if direction == "BUY" else "ORDER_TYPE_SELL"
        requested_price = signal_data.get("entry_price")
        try:
            requested_price = float(requested_price)
        except (TypeError, ValueError):
            requested_price = None
        if requested_price is None or requested_price <= 0.0:
            self._persist_execution_state(signal_data, {
                "status": "ERROR",
                "result": "ERROR",
                "execution_status": "ERROR",
                "execution_error": "Missing executable entry_price",
            })
            return {"status": "error", "reason": "Missing executable entry_price"}
        self._persist_execution_state(signal_data, {
            "execution_status": "PENDING_EXECUTION",
            "requested_price": requested_price,
            "requested_lot_size": lot_size,
        })

        if self.paper_mode:
            result = {
                "status": "paper",
                "symbol": mt5_sym,
                "direction": direction,
                "lot_size": lot_size,
                "sl": sl,
                "tp": tp,
                "timestamp": datetime.utcnow().isoformat()
            }
            print(f"📝 [PAPER TRADE] {direction} {lot_size} {mt5_sym} | SL={sl} | TP={tp}")

            paper_order_id = f"PAPER_{int(datetime.utcnow().timestamp())}"
            self._write_order(signal_data, {
                "order_id": paper_order_id,
                "symbol": mt5_sym,
                "direction": direction,
                "requested_lots": lot_size,
                "requested_price": requested_price,
                "sl": sl,
                "tp": tp,
                "status": "PAPER_EXECUTED"
            })
            self._write_fill(paper_order_id, {
                "symbol": mt5_sym,
                "direction": direction,
                "filled_lots": lot_size,
                "filled_price": requested_price or 0,
                "raw_response": json.dumps({"paper": True})
            })

            self._log_paper_trade("OPEN", signal_data, result)
            return result

        # Live execution
        connected = await self._connect()
        if not connected:
            self._persist_execution_state(signal_data, {
                "status": "ERROR",
                "result": "ERROR",
                "execution_status": "ERROR",
                "execution_error": "MetaAPI not connected",
            })
            return {"status": "error", "reason": "MetaAPI not connected"}

        try:
            connection = self._account.get_rpc_connection()
            await connection.connect()
            await connection.wait_synchronized()

            order_result = await connection.create_market_buy_order(
                mt5_sym, lot_size, sl, tp,
                {"comment": "CRT-AutoBot"}
            ) if direction == "BUY" else await connection.create_market_sell_order(
                mt5_sym, lot_size, sl, tp,
                {"comment": "CRT-AutoBot"}
            )

            result = {
                "status": "executed",
                "order_id": order_result.get("orderId"),
                "position_id": order_result.get("positionId"),
                "symbol": mt5_sym,
                "direction": direction,
                "lot_size": lot_size,
                "fill_price": order_result.get("openPrice"),
                "timestamp": datetime.utcnow().isoformat()
            }

            # Record Order Intent
            self._write_order(signal_data, {
                "order_id": order_result.get("orderId"),
                "symbol": mt5_sym,
                "direction": direction,
                "requested_lots": lot_size,
                "requested_price": requested_price,
                "sl": sl,
                "tp": tp,
                "status": "LIVE_EXECUTED",
                "raw_request": json.dumps({"direction": direction, "volume": lot_size, "sl": sl, "tp": tp})
            })

            # Record Fill Reality
            self._write_fill(order_result.get("orderId"), {
                "symbol": mt5_sym,
                "direction": direction,
                "filled_lots": float(order_result.get("volume") or order_result.get("filledVolume") or lot_size),
                "filled_price": float(order_result.get("openPrice") or order_result.get("price") or 0),
                "broker_time": order_result.get("time"),
                "raw_response": json.dumps(order_result, default=str)
            })
            filled_volume = order_result.get("volume") or order_result.get("filledVolume") or lot_size
            fill_price = order_result.get("openPrice") or order_result.get("price")
            execution_status = "PARTIAL" if filled_volume and float(filled_volume) < float(lot_size) else "LIVE_EXECUTED"
            self._persist_execution_state(signal_data, {
                "status": execution_status,
                "execution_status": execution_status,
                "broker_order_id": order_result.get("orderId"),
                "broker_position_id": order_result.get("positionId"),
                "fill_price": fill_price,
                "filled_lot_size": filled_volume,
                "slippage_pips": self._slippage_pips(symbol, requested_price, fill_price),
                "execution_error": None,
                "score_details_patch": {"mt5_action": "OPEN", "live_result": order_result},
            })
            print(f"✅ [LIVE TRADE] {direction} {lot_size} {mt5_sym} → OrderID: {result['order_id']}")
            return result

        except Exception as e:
            print(f"❌ Trade execution failed for {mt5_sym}: {e}")
            self._persist_execution_state(signal_data, {
                "status": "ERROR",
                "result": "ERROR",
                "execution_status": "ERROR",
                "execution_error": str(e),
            })
            return {"status": "error", "reason": str(e)}

    async def get_open_positions(self) -> List[Dict]:
        """Fetch all open positions from MT5 via MetaAPI."""
        self._load_runtime_config()
        if self.paper_mode or not self._has_live_credentials():
            # Return paper trades from DB
            try:
                conn = connect_sqlite(DB_SIGNALS)
                rows = conn.execute("""
                    SELECT id, signal_uid, symbol, direction, entry_price, sl, tp1, trade_type, timestamp,
                           execution_status, fill_price, filled_lot_size
                    FROM signals
                    WHERE status IN ('PAPER_EXECUTED', 'PARTIAL', 'LIVE_EXECUTED')
                    ORDER BY timestamp DESC LIMIT 20
                """).fetchall()
                conn.close()
                return [dict(r) for r in rows]
            except Exception:
                return []

        connected = await self._connect()
        if not connected:
            return []

        try:
            connection = self._account.get_rpc_connection()
            await connection.connect()
            await connection.wait_synchronized()
            positions = await connection.get_positions()
            return [
                {
                    "id": p.get("id"),
                    "symbol": p.get("symbol"),
                    "direction": "BUY" if p.get("type") == "POSITION_TYPE_BUY" else "SELL",
                    "lot_size": p.get("volume"),
                    "open_price": p.get("openPrice"),
                    "current_price": p.get("currentPrice"),
                    "profit": p.get("profit"),
                    "sl": p.get("stopLoss"),
                    "tp": p.get("takeProfit"),
                    "open_time": p.get("time")
                }
                for p in (positions or [])
            ]
        except Exception as e:
            print(f"❌ get_open_positions failed: {e}")
            return []

    async def close_trade(self, position_id: str) -> dict:
        """Close an open position by ID."""
        self._load_runtime_config()
        if self.paper_mode or not self._has_live_credentials():
            try:
                conn = connect_sqlite(DB_SIGNALS)
                row = conn.execute("SELECT symbol, signal_uid FROM signals WHERE id=?", (position_id,)).fetchone()
                conn.execute("UPDATE signals SET status='PAPER_CLOSED', execution_status='PAPER_CLOSED', result='CLOSED', closed_at=? WHERE id=?", (datetime.utcnow().isoformat(), position_id))
                conn.commit()
                conn.close()
                if row:
                    from core.execution_gate import ExecutionGate
                    ExecutionGate.release_reservation(row[0], DB_SIGNALS, row[1], status="CLOSED")
            except Exception:
                pass
            return {"status": "paper_closed", "position_id": position_id}

        connected = await self._connect()
        if not connected:
            return {"status": "error", "reason": "MetaAPI not connected"}

        try:
            connection = self._account.get_rpc_connection()
            await connection.connect()
            await connection.wait_synchronized()
            result = await connection.close_position(position_id, {"comment": "CRT-AutoBot close"})
            return {"status": "closed", "position_id": position_id, "result": result}
        except Exception as e:
            print(f"❌ close_trade failed: {e}")
            return {"status": "error", "reason": str(e)}

    async def reconcile_with_broker(self):
        """ Institutional Reconciliation: syncs local ledger with actual broker deals/positions. """
        self._load_runtime_config()
        if self.paper_mode or not self._has_live_credentials():
            return

        connected = await self._connect()
        if not connected: return

        try:
            connection = self._account.get_rpc_connection()
            await connection.connect()
            await connection.wait_synchronized()

            # 1. Sync Deals (Fills)
            # Fetch deals from last 24 hours to capture commissions/swaps/slippage
            start_time = datetime.utcnow() - timedelta(days=1)
            deals = await connection.get_deals_by_id(start_time, datetime.utcnow())

            with connect_sqlite(DB_SIGNALS) as conn:
                for deal in deals:
                    # Sync комиссии and swap to our fills table
                    conn.execute("""
                        UPDATE fills SET
                            commission = ?,
                            swap = ?,
                            filled_price = ?,
                            broker_time = ?
                        WHERE order_id = ?
                    """, (
                        deal.get('commission', 0),
                        deal.get('swap', 0),
                        deal.get('price'),
                        deal.get('time'),
                        deal.get('orderId')
                    ))
                conn.commit()

            # 2. Sync Positions (Open Signals)
            broker_positions = await connection.get_positions()
            broker_pos_ids = [p['id'] for p in broker_positions]

            with connect_sqlite(DB_SIGNALS) as conn:
                # Find local signals marked as LIVE_EXECUTED that are NOT in broker positions
                local_active = conn.execute("""
                    SELECT id, symbol, signal_uid, broker_order_id, broker_position_id
                    FROM signals
                    WHERE status IN ('LIVE_EXECUTED', 'PARTIAL')
                      AND broker_position_id IS NOT NULL
                """).fetchall()

                for row in local_active:
                    if row['broker_position_id'] not in broker_pos_ids:
                        print(f"🔄 Reconciling closure for {row['symbol']} (PosID: {row['broker_position_id']})")
                        conn.execute("""
                            UPDATE signals SET
                                status = 'CLOSED',
                                execution_status = 'RECONCILED_CLOSED',
                                closed_at = ?
                            WHERE id = ?
                        """, (datetime.utcnow().isoformat(), row['id']))

                        # Release risk reservation
                        from core.execution_gate import ExecutionGate
                        ExecutionGate.release_reservation(row['symbol'], DB_SIGNALS, row['signal_uid'], status="CLOSED")
                conn.commit()

            print(f"✅ Full Reconciliation Complete: Audited {len(deals)} deals and {len(broker_positions)} positions.")

        except Exception as e:
            print(f"❌ Reconciliation failed: {e}")

    async def get_historical_data(self, symbol: str, timeframe: str, limit: int = 100) -> Optional[List[Dict]]:
        """ Fetch candles directly from the broker bridge. """
        connected = await self._connect()
        if not connected: return None

        try:
            mt5_sym = self._map_symbol(symbol)
            # Map common timeframes to MetaAPI naming if necessary
            # MetaAPI usually uses '1m', '5m', '1h' etc.
            tf_map = {"15m": "15m", "1h": "1h", "4h": "4h", "1d": "1d"}
            mapped_tf = tf_map.get(timeframe, timeframe)

            # MetaAPI fetch works backwards from a given start_time.
            # We use UTC now to get the most recent N candles.
            candles = await self._account.get_historical_candles(
                symbol=mt5_sym,
                timeframe=mapped_tf,
                start_time=datetime.utcnow(),
                limit=limit
            )
            
            # Reformat to match our internal data structure
            return [
                {
                    "timestamp": c['time'],
                    "open": c['open'],
                    "high": c['high'],
                    "low": c['low'],
                    "close": c['close'],
                    "volume": c.get('tickVolume', 0)
                } for c in candles
            ]
        except Exception as e:
            print(f"⚠️ Broker data fetch failed for {symbol}: {e}")
            return None

    async def get_latest_tick(self, symbol: str) -> Optional[Dict]:
        """ Get real-time bid/ask from the broker. """
        connected = await self._connect()
        if not connected: return None

        try:
            connection = self._account.get_rpc_connection()
            await connection.connect()
            await connection.wait_synchronized()

            mt5_sym = self._map_symbol(symbol)
            tick = await connection.get_tick(mt5_sym)
            return {
                "bid": tick['bid'],
                "ask": tick['ask'],
                "time": tick['time']
            }
        except Exception as e:
            print(f"⚠️ Broker tick fetch failed for {symbol}: {e}")
            return None

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
            with connect_sqlite(DB_SIGNALS) as conn:
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

    def _write_order(self, signal_data: dict, order_data: dict):
        try:
            with connect_sqlite(DB_SIGNALS) as conn:
                self._ensure_execution_events(conn)
                conn.execute("""
                    INSERT OR REPLACE INTO orders (
                        order_id, symbol, direction, requested_lots, requested_price, sl, tp, status, raw_request, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    order_data["order_id"],
                    order_data["symbol"],
                    order_data["direction"],
                    order_data["requested_lots"],
                    order_data.get("requested_price"),
                    order_data.get("sl"),
                    order_data.get("tp"),
                    order_data["status"],
                    order_data.get("raw_request"),
                    datetime.utcnow().isoformat()
                ))
                conn.commit()
        except Exception as e:
            print(f"⚠️  _write_order failed: {e}")

    def _write_fill(self, order_id: str, fill_data: dict):
        try:
            with connect_sqlite(DB_SIGNALS) as conn:
                self._ensure_execution_events(conn)
                conn.execute("""
                    INSERT INTO fills (
                        order_id, symbol, direction, filled_lots, filled_price, broker_time, raw_response, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    order_id,
                    fill_data["symbol"],
                    fill_data["direction"],
                    fill_data["filled_lots"],
                    fill_data["filled_price"],
                    fill_data.get("broker_time"),
                    fill_data.get("raw_response"),
                    datetime.utcnow().isoformat()
                ))
                conn.commit()
        except Exception as e:
            print(f"⚠️  _write_fill failed: {e}")

    def _slippage_pips(self, symbol: str, requested_price, fill_price) -> Optional[float]:
        try:
            if requested_price is None or fill_price is None:
                return None
            dist = abs(float(fill_price) - float(requested_price))
            if "JPY" in symbol:
                return round(dist * 100, 3)
            if "BTC" in symbol:
                return round(dist, 3)
            if "CL" in symbol or "GC" in symbol or "XAU" in symbol:
                return round(dist * 10, 3)
            return round(dist * 10000, 3)
        except Exception:
            return None


# Singleton instance
_executor = None

def get_executor() -> TradeExecutor:
    global _executor
    if _executor is None:
        _executor = TradeExecutor()
    return _executor
