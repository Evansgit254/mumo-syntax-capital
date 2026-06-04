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
    Executes trades on MT5 via MetaAPI REST bridge.
    Falls back to paper logging when MT5_PAPER_MODE=true or MetaAPI is not configured.
    """

    def __init__(self):
        settings = config_manager.snapshot()
        self.paper_mode = settings.mt5_paper_mode
        self.auto_trade = settings.mt5_auto_trade
        self._api = None
        self._account = None
        self._token_hash = None
        self._connect_lock = asyncio.Lock()
        
        # Native Engine for Direct Windows Execution (V5.3.3)
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

    def _get_credentials(self):
        settings = config_manager.snapshot()
        return settings.metaapi_token, settings.metaapi_account_id

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
        Place a market order based on a signal dict.
        Returns a result dict with order_id, fill_price, status.

        Paper mode: logs to console + DB but places no real order.
        """
        self._load_runtime_config()
        if not self.auto_trade:
            return {"status": "skipped", "reason": "MT5_AUTO_TRADE=false"}

        settings = config_manager.snapshot()
        if settings.mt5_use_direct:
            print("🚀 [DIRECT MT5] Dispatching to Native Engine...")
            return self._direct_engine.execute_trade(signal_data)

        symbol = str(signal_data.get("symbol") or "").strip()
        direction = str(signal_data.get("direction") or "").upper()
        lot_size = signal_data.get("lot_size")
        if lot_size is None and isinstance(signal_data.get("risk_details"), dict):
            lot_size = signal_data["risk_details"].get("lots")
        sl = signal_data.get("sl")
        tp = signal_data.get("tp1")  # Use TP1 as conservative target
        requested_price = signal_data.get("entry_price")

        validation_errors = []
        if not symbol:
            validation_errors.append("symbol missing")
        if direction not in {"BUY", "SELL"}:
            validation_errors.append("direction must be BUY or SELL")
        try:
            lot_size = float(lot_size)
        except (TypeError, ValueError):
            lot_size = None
        if lot_size is None or lot_size <= 0.0:
            validation_errors.append("lot_size missing or invalid")
        try:
            sl = float(sl)
        except (TypeError, ValueError):
            sl = None
        if sl is None or sl <= 0.0:
            validation_errors.append("sl missing or invalid")
        try:
            tp = float(tp)
        except (TypeError, ValueError):
            tp = None
        if tp is None or tp <= 0.0:
            validation_errors.append("tp1 missing or invalid")
        try:
            requested_price = float(requested_price)
        except (TypeError, ValueError):
            requested_price = None
        if requested_price is None or requested_price <= 0.0:
            validation_errors.append("entry_price missing or invalid")

        if validation_errors:
            reason = "; ".join(validation_errors)
            self._persist_execution_state(signal_data, {
                "status": "ERROR",
                "result": "ERROR",
                "execution_status": "ERROR",
                "execution_error": reason,
            })
            return {"status": "error", "reason": reason}

        mt5_sym = self._map_symbol(symbol)
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
        readiness_errors = await self._live_readiness_errors(symbol)
        if readiness_errors:
            reason = "; ".join(readiness_errors)
            self._persist_execution_state(signal_data, {
                "status": "BLOCKED",
                "result": "BLOCKED",
                "execution_status": "LIVE_READINESS_BLOCKED",
                "execution_error": reason,
            })
            return {"status": "blocked", "reason": reason}

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

            spread_check = await self._pretrade_spread_check(connection, mt5_sym, symbol)
            if spread_check is not None:
                self._persist_execution_state(signal_data, {
                    "status": "BLOCKED",
                    "result": "BLOCKED",
                    "execution_status": "SPREAD_BLOCKED",
                    "execution_error": spread_check,
                })
                return {"status": "blocked", "reason": spread_check}

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
        """Fetch all open positions from MT5."""
        self._load_runtime_config()
        
        settings = config_manager.snapshot()
        if settings.mt5_use_direct:
            info = self._direct_engine.get_account_info()
            # Note: Direct engine needs a get_positions method which I will add next
            # Or I can use mt5.positions_get() if I modify direct_mt5_engine.py
            # For now, I'll assume we add a proxy or call directly if we import mt5 here
            import MetaTrader5 as mt5_lib
            if mt5_lib.initialize():
                positions = mt5_lib.positions_get()
                return [
                    {
                        "id": p.ticket,
                        "symbol": p.symbol,
                        "direction": "BUY" if p.type == 0 else "SELL",
                        "lot_size": p.volume,
                        "open_price": p.price_open,
                        "current_price": p.price_current,
                        "profit": p.profit,
                        "sl": p.sl,
                        "tp": p.tp,
                        "open_time": p.time
                    } for p in (positions or [])
                ]
            return []

        if self.paper_mode or not self._has_live_credentials():
            # Return paper trades from DB
            try:
                conn = connect_sqlite(config_manager.get("db_signals"))
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
        """Close an open position."""
        self._load_runtime_config()
        
        settings = config_manager.snapshot()
        if settings.mt5_use_direct:
            import MetaTrader5 as mt5_lib
            if mt5_lib.initialize():
                # We need the position info to close it
                pos = mt5_lib.positions_get(ticket=int(position_id))
                if not pos: return {"status": "error", "reason": "Position not found"}
                p = pos[0]
                request = {
                    "action": mt5_lib.TRADE_ACTION_DEAL,
                    "symbol": p.symbol,
                    "volume": p.volume,
                    "type": mt5_lib.ORDER_TYPE_SELL if p.type == 0 else mt5_lib.ORDER_TYPE_BUY,
                    "position": p.ticket,
                    "price": mt5_lib.symbol_info_tick(p.symbol).bid if p.type == 0 else mt5_lib.symbol_info_tick(p.symbol).ask,
                    "deviation": 20,
                    "magic": 20260605,
                    "comment": "Direct close",
                    "type_time": mt5_lib.ORDER_TIME_GTC,
                    "type_filling": mt5_lib.ORDER_FILLING_IOC,
                }
                result = mt5_lib.order_send(request)
                return {"status": "closed" if result.retcode == mt5_lib.TRADE_RETCODE_DONE else "error", "position_id": position_id}

        if self.paper_mode or not self._has_live_credentials():
            try:
                conn = connect_sqlite(config_manager.get("db_signals"))
                row = conn.execute("SELECT symbol, signal_uid FROM signals WHERE id=?", (position_id,)).fetchone()
                conn.execute("UPDATE signals SET status='PAPER_CLOSED', execution_status='PAPER_CLOSED', result='CLOSED', closed_at=? WHERE id=?", (datetime.utcnow().isoformat(), position_id))
                conn.commit()
                conn.close()
                if row:
                    from core.execution_gate import ExecutionGate
                    ExecutionGate.release_reservation(row[0], config_manager.get("db_signals"), row[1], status="CLOSED")
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

        run_id = None
        started_at = datetime.utcnow().isoformat()
        with connect_sqlite(config_manager.get("db_signals")) as conn:
            self._ensure_execution_events(conn)
            cur = conn.execute("""
                INSERT INTO reconciliation_runs (status, started_at)
                VALUES ('RUNNING', ?)
            """, (started_at,))
            run_id = cur.lastrowid
            conn.commit()

        try:
            connected = await asyncio.wait_for(self._connect(), timeout=10)
        except asyncio.TimeoutError:
            print("⚠️  Reconciliation skipped: MetaAPI connection timed out")
            self._finish_reconciliation_run(run_id, "ERROR", 0, 0, "MetaAPI connection timed out")
            return
        if not connected:
            self._finish_reconciliation_run(run_id, "ERROR", 0, 0, "MetaAPI not connected")
            return

        try:
            connection = self._account.get_rpc_connection()
            await connection.connect()
            await connection.wait_synchronized()

            # 1. Sync Deals (Fills)
            # Fetch deals from last 24 hours to capture commissions/swaps/slippage
            start_time = datetime.utcnow() - timedelta(days=1)
            deals = await connection.get_deals_by_id(start_time, datetime.utcnow())
            deals = deals or []

            with connect_sqlite(config_manager.get("db_signals")) as conn:
                self._ensure_execution_events(conn)
                for deal in deals:
                    order_id = str(deal.get('orderId') or deal.get('order_id') or deal.get('id') or "")
                    if not order_id:
                        continue
                    # Sync комиссии and swap to our fills table
                    cur = conn.execute("""
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
                        order_id
                    ))
                    if cur.rowcount == 0:
                        symbol = deal.get("symbol") or "UNKNOWN"
                        direction = self._direction_from_deal(deal)
                        conn.execute("""
                            INSERT OR IGNORE INTO orders (
                                order_id, symbol, direction, requested_lots, requested_price,
                                status, raw_request, created_at
                            ) VALUES (?, ?, ?, ?, ?, 'BROKER_RECONCILED', ?, ?)
                        """, (
                            order_id,
                            symbol,
                            direction,
                            float(deal.get("volume") or deal.get("filledVolume") or 0),
                            deal.get("price"),
                            json.dumps({"reconciled_deal": deal}, default=str),
                            datetime.utcnow().isoformat(),
                        ))
                        conn.execute("""
                            INSERT INTO fills (
                                order_id, symbol, direction, filled_lots, filled_price,
                                commission, swap, broker_time, raw_response, created_at
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """, (
                            order_id,
                            symbol,
                            direction,
                            float(deal.get("volume") or deal.get("filledVolume") or 0),
                            float(deal.get("price") or 0),
                            deal.get("commission", 0),
                            deal.get("swap", 0),
                            deal.get("time"),
                            json.dumps(deal, default=str),
                            datetime.utcnow().isoformat(),
                        ))
                    conn.execute("""
                        INSERT INTO broker_reconciliation_events (
                            broker_order_id, broker_position_id, symbol, event_type, payload_json, created_at
                        ) VALUES (?, ?, ?, 'DEAL_SYNCED', ?, ?)
                    """, (
                        order_id,
                        deal.get("positionId") or deal.get("position_id"),
                        deal.get("symbol"),
                        json.dumps(deal, default=str),
                        datetime.utcnow().isoformat(),
                    ))
                conn.commit()

            # 2. Sync Positions (Open Signals)
            broker_positions = await connection.get_positions()
            broker_positions = broker_positions or []
            broker_pos_ids = [p['id'] for p in broker_positions]

            with connect_sqlite(config_manager.get("db_signals")) as conn:
                self._ensure_execution_events(conn)
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
                        ExecutionGate.release_reservation(row['symbol'], config_manager.get("db_signals"), row['signal_uid'], status="CLOSED")
                        conn.execute("""
                            INSERT INTO broker_reconciliation_events (
                                broker_order_id, broker_position_id, symbol, event_type, payload_json, created_at
                            ) VALUES (?, ?, ?, 'POSITION_CLOSED', ?, ?)
                        """, (
                            row['broker_order_id'],
                            row['broker_position_id'],
                            row['symbol'],
                            json.dumps({"signal_id": row["id"]}, default=str),
                            datetime.utcnow().isoformat(),
                        ))
                conn.commit()

            self._finish_reconciliation_run(run_id, "OK", len(deals), len(broker_positions), None)
            print(f"✅ Full Reconciliation Complete: Audited {len(deals)} deals and {len(broker_positions)} positions.")

        except Exception as e:
            print(f"❌ Reconciliation failed: {e}")
            self._finish_reconciliation_run(run_id, "ERROR", 0, 0, str(e))

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
        if settings.require_broker_data_for_live and settings.data_provider != "mt5":
            errors.append("data_provider must be mt5 for live execution")
        if not settings.metaapi_token or not settings.metaapi_account_id:
            errors.append("MetaAPI credentials missing")
        if not symbol:
            errors.append("symbol missing")
        return errors

    async def _pretrade_spread_check(self, connection, mt5_sym: str, original_symbol: str) -> Optional[str]:
        max_spread = float(config_manager.get("max_pretrade_spread_pips", 3.0, refresh=True) or 0)
        if max_spread <= 0:
            return None
        try:
            tick = await connection.get_tick(mt5_sym)
            bid = float(tick["bid"])
            ask = float(tick["ask"])
            spread_pips = abs(ask - bid) / self._pip_size(original_symbol)
            if spread_pips > max_spread:
                return f"Spread too wide: {spread_pips:.2f} pips > {max_spread:.2f}"
        except Exception as e:
            return f"Broker tick validation failed: {e}"
        return None

    def _pip_size(self, symbol: str) -> float:
        raw = (symbol or "").upper()
        if "JPY" in raw:
            return 0.01
        if "BTC" in raw:
            return 1.0
        if "XAU" in raw or "GC=F" in raw or "GOLD" in raw:
            return 0.1
        if "OIL" in raw or "CL=F" in raw:
            return 0.01
        return 0.0001

    def _direction_from_deal(self, deal: dict) -> str:
        raw = str(deal.get("type") or deal.get("entryType") or deal.get("direction") or "").upper()
        if "SELL" in raw:
            return "SELL"
        return "BUY"

    def _finish_reconciliation_run(self, run_id: Optional[int], status: str,
                                   deals_count: int, positions_count: int,
                                   error: Optional[str]) -> None:
        if run_id is None:
            return
        try:
            with connect_sqlite(config_manager.get("db_signals")) as conn:
                self._ensure_execution_events(conn)
                conn.execute("""
                    UPDATE reconciliation_runs
                    SET status = ?, deals_count = ?, positions_count = ?, error = ?, completed_at = ?
                    WHERE id = ?
                """, (
                    status,
                    deals_count,
                    positions_count,
                    error,
                    datetime.utcnow().isoformat(),
                    run_id,
                ))
                conn.commit()
        except Exception as e:
            print(f"⚠️  Reconciliation run update failed: {e}")

    def _write_order(self, signal_data: dict, order_data: dict):
        try:
            with connect_sqlite(config_manager.get("db_signals")) as conn:
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
            with connect_sqlite(config_manager.get("db_signals")) as conn:
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
