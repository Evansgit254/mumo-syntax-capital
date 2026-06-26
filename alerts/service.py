"""
Telegram Service for sending trading signals.
"""
from datetime import datetime
from typing import Optional
from telegram import Bot
from telegram.error import TelegramError
from config.manager import config_manager
from core.signal_formatter import SignalFormatter
from core.db_utils import connect_sqlite


class TelegramService:
    """
    Service for sending trading signals via Telegram.
    """
    
    def __init__(self):
        settings = config_manager.refresh()
        self.bot_token = settings.telegram_bot_token
        self.chat_id = settings.telegram_chat_id
        # All destinations: primary + any extras from TELEGRAM_EXTRA_CHAT_IDS env var
        self.all_chat_ids = [self.chat_id] + settings.telegram_extra_chat_ids if self.chat_id else settings.telegram_extra_chat_ids
        self.bot = None
        
        if self.bot_token and self.all_chat_ids:
            try:
                self.bot = Bot(token=self.bot_token)
            except Exception as e:
                print(f"⚠️  Warning: Could not initialize Telegram bot: {e}")
    
    def format_signal(self, signal_data: dict) -> str:
        """
        Formats signal data into a Telegram message.
        Handles both simple signals and complex mock signals.
        """
        # If it's a simple signal (from generate_signals.py), use SignalFormatter
        if 'trade_type' in signal_data or 'timeframe' in signal_data:
            return SignalFormatter.format_signal(signal_data)
        
        # Otherwise, format as complex signal (from mock/test data)
        symbol = signal_data.get('symbol', 'UNKNOWN')
        direction = signal_data.get('direction', 'N/A')
        entry_tf = signal_data.get('entry_tf', signal_data.get('timeframe', 'N/A'))
        setup_quality = signal_data.get('setup_quality', 'STANDARD')
        session = signal_data.get('session', 'N/A')
        
        entry = signal_data.get('entry_price', signal_data.get('entry', 0))
        sl = signal_data.get('sl', signal_data.get('stop_loss', 0))
        tp0 = signal_data.get('tp0', 0)
        tp1 = signal_data.get('tp1', 0)
        tp2 = signal_data.get('tp2', 0)
        confidence = signal_data.get('confidence', 0)
        
        risk_details = signal_data.get('risk_details', {})
        layers = signal_data.get('layers', [])
        
        # Calculate pips
        pip_divisor = 10000.0
        if "JPY" in symbol:
            pip_divisor = 100.0
        elif "GC" in symbol or "BTC" in symbol or "CL" in symbol:
            pip_divisor = 10.0
        
        sl_pips = abs(entry - sl) * pip_divisor if entry and sl else 0
        tp0_pips = abs(tp0 - entry) * pip_divisor if tp0 and entry else 0
        tp1_pips = abs(tp1 - entry) * pip_divisor if tp1 and entry else 0
        tp2_pips = abs(tp2 - entry) * pip_divisor if tp2 and entry else 0
        
        # Build message
        message = f"""
{'='*60}
📊 TRADE SIGNAL - {setup_quality}
{'='*60}
Symbol:           {symbol}
Direction:        {direction}
Timeframe:        {entry_tf}
Session:          {session}
Entry Price:      {entry:.5f}
Stop Loss:        {sl:.5f} ({'-' if direction == 'BUY' else '+'}{sl_pips:.1f} pips)
──────────────────────────────────────────────────────────
TP0 (50% Exit):   {tp0:.5f} ({'+' if direction == 'BUY' else '-'}{tp0_pips:.1f} pips)
TP1 (30% Exit):   {tp1:.5f} ({'+' if direction == 'BUY' else '-'}{tp1_pips:.1f} pips)
TP2 (20% Exit):   {tp2:.5f} ({'+' if direction == 'BUY' else '-'}{tp2_pips:.1f} pips)
──────────────────────────────────────────────────────────
"""
        
        # Add layers if present
        if layers:
            message += "Entry Layers:\n"
            for layer in layers:
                message += f"  • {layer.get('label', 'Layer')}: {layer.get('lots', 0):.2f} lots @ {layer.get('price', 0):.5f}\n"
            message += "──────────────────────────────────────────────────────────\n"
        
        # Add risk details
        if risk_details:
            message += f"Position Size:    {risk_details.get('lots', risk_details.get('lot_size', 0))}\n"
            message += f"Risk Amount:      ${risk_details.get('risk_cash', risk_details.get('risk_amount', 0))}\n"
            message += f"Risk Percent:     {risk_details.get('risk_percent', 0)}%\n"
            if risk_details.get('warning'):
                message += f"⚠️  {risk_details.get('warning')}\n"
        
        # Add additional info
        if signal_data.get('liquidity_event'):
            message += f"\n💧 Liquidity: {signal_data.get('liquidity_event')}\n"
        if signal_data.get('ai_logic'):
            message += f"🧠 Logic: {signal_data.get('ai_logic')}\n"
        if signal_data.get('entry_zone'):
            message += f"📍 Entry Zone: {signal_data.get('entry_zone')}\n"
        
        message += f"Alpha Score:      {confidence:.2f} {'(STRONG)' if confidence > 1.5 else '(MODERATE)' if confidence > 1.0 else '(WEAK)'}\n"
        message += f"{'='*60}\n"
        
        return message
    
    async def send_signal(self, message: str) -> bool:
        """
        Sends a formatted signal message to all configured Telegram chat IDs.
        Returns True if at least one send succeeded.
        """
        if not self.bot or not self.all_chat_ids:
            print("⚠️  Telegram not configured. Skipping send.")
            return False
        
        any_success = False
        for chat_id in self.all_chat_ids:
            try:
                await self.bot.send_message(
                    chat_id=chat_id,
                    text=message,
                    parse_mode='HTML'
                )
                any_success = True
            except TelegramError as e:
                print(f"❌ Telegram error sending to {chat_id}: {e}")
            except Exception as e:
                print(f"❌ Error sending Telegram message to {chat_id}: {e}")
        return any_success
    
    async def send_text(self, text: str, chat_id: str = None) -> bool:
        """
        Sends plain text message to Telegram.
        """
        target_id = chat_id if chat_id else self.chat_id
        if not self.bot or not target_id:
            return False
        
        try:
            await self.bot.send_message(
                chat_id=target_id, 
                text=text,
                parse_mode='HTML'
            )
            return True
        except Exception as e:
            print(f"❌ Error sending Telegram message: {e}")
            return False

    def _ensure_entitlement_table(self, db_path: str):
        conn = None
        try:
            conn = connect_sqlite(db_path)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS client_signal_entitlements (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    telegram_chat_id TEXT NOT NULL,
                    signal_id INTEGER NOT NULL,
                    signal_uid TEXT,
                    delivery_status TEXT DEFAULT 'ENTITLED',
                    delivery_channel TEXT DEFAULT 'telegram',
                    tier_at_delivery TEXT,
                    created_at TEXT NOT NULL,
                    delivered_at TEXT,
                    UNIQUE(telegram_chat_id, signal_id)
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_client_signal_entitlements_client
                ON client_signal_entitlements(telegram_chat_id, signal_id)
            """)
            conn.commit()
        finally:
            if conn:
                conn.close()

    def _record_signal_entitlement(
        self,
        db_path: str,
        client: dict,
        signal_data: dict,
        delivery_status: str,
        delivered_at: str = None,
    ):
        signal_id = signal_data.get("id")
        if not signal_id:
            return
        self._ensure_entitlement_table(db_path)
        conn = None
        try:
            now = datetime.utcnow().isoformat()
            conn = connect_sqlite(db_path)
            conn.execute("""
                INSERT INTO client_signal_entitlements (
                    telegram_chat_id, signal_id, signal_uid, delivery_status,
                    delivery_channel, tier_at_delivery, created_at, delivered_at
                )
                VALUES (?, ?, ?, ?, 'telegram', ?, ?, ?)
                ON CONFLICT(telegram_chat_id, signal_id) DO UPDATE SET
                    signal_uid = excluded.signal_uid,
                    delivery_status = excluded.delivery_status,
                    tier_at_delivery = excluded.tier_at_delivery,
                    delivered_at = COALESCE(excluded.delivered_at, client_signal_entitlements.delivered_at)
            """, (
                str(client["telegram_chat_id"]),
                int(signal_id),
                signal_data.get("signal_uid"),
                delivery_status,
                client.get("subscription_tier"),
                now,
                delivered_at,
            ))
            conn.commit()
        except Exception as e:
            print(f"⚠️ Failed to record client signal entitlement for {client.get('telegram_chat_id')}: {e}")
        finally:
            if conn:
                conn.close()

    async def broadcast_personalized_signal(self, signal_data: dict):
        """
        Broadcasts personalized signals to all active clients.
        """
        from core.client_manager import ClientManager
        settings = config_manager.refresh()
        
        if not settings.multi_client_mode:
            # Fallback to single user
            message = self.format_signal(signal_data)
            await self.send_signal(message)
            return
            
        manager = ClientManager(settings.db_clients)
        clients = manager.get_all_active_clients()
        
        # V11.2 Auto-Register Primary Chat if Database is Empty
        if not clients and self.chat_id:
            print(f"⚙️ Auto-registering primary chat {self.chat_id} with ${settings.account_balance} balance...")
            manager.register_client(
                telegram_chat_id=self.chat_id,
                account_balance=settings.account_balance,
                risk_percent=2.0
            )
            clients = manager.get_all_active_clients()
            print(f"✅ Primary client registered successfully.")
        
        if not clients:
            print("⚠️ No active clients found. Signal not sent.")
            return
        
        success_count = 0
        skipped_count = 0
        entitled_count = 0
        
        for client in clients:
            # V17.1 Monetization Check
            chat_id = client['telegram_chat_id']
            is_admin = str(chat_id) == str(self.chat_id)
            
            if not is_admin and not manager.is_subscription_active(chat_id):
                skipped_count += 1
                continue
                
            try:
                self._record_signal_entitlement(
                    settings.db_clients,
                    client,
                    signal_data,
                    delivery_status="PENDING",
                )
                entitled_count += 1
                formatted = SignalFormatter.format_personalized_signal(signal_data, client)
                if await self.send_text(formatted, chat_id=client['telegram_chat_id']):
                    success_count += 1
                    self._record_signal_entitlement(
                        settings.db_clients,
                        client,
                        signal_data,
                        delivery_status="SENT",
                        delivered_at=datetime.utcnow().isoformat(),
                    )
                else:
                    self._record_signal_entitlement(
                        settings.db_clients,
                        client,
                        signal_data,
                        delivery_status="FAILED",
                    )
            except Exception as e:
                self._record_signal_entitlement(
                    settings.db_clients,
                    client,
                    signal_data,
                    delivery_status="FAILED",
                )
                print(f"⚠️ Failed to send signal to {client['telegram_chat_id']}: {e}")
        
        print(f"📢 Broadcast complete. {success_count} sent, {entitled_count} entitled, {skipped_count} expired/skipped. Total clients: {len(clients)}")
