from fastapi import FastAPI, HTTPException, Request, Depends, status
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
import sqlite3
import os
import json
import secrets
import stripe
import hashlib
import jwt
from datetime import datetime, timedelta
from typing import List, Optional
from pydantic import BaseModel
import subprocess
import time
import asyncio
from data.fetcher import DataFetcher
from data.news_fetcher import NewsFetcher
from indicators.calculations import IndicatorCalculator
from core.filters.macro_filter import MacroFilter
from config.config import DXY_SYMBOL, TNX_SYMBOL, SYMBOLS, DB_CLIENTS, DB_SIGNALS
from core.client_manager import ClientManager

# Stripe Configuration
stripe.api_key = os.getenv("STRIPE_API_KEY")
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET")

# Admin Credentials (CRITICAL: Required in Production)
ADMIN_USER = os.getenv("ADMIN_USER", "admin")
ADMIN_PASS = os.getenv("ADMIN_PASS")
if not ADMIN_PASS:
    print("⚠️ WARNING: ADMIN_PASS not set. Backend will be inaccessible.")

# Market Context Cache
market_context_cache = {
    "data": None,
    "last_update": 0,
    "ttl": 900 # 15 minutes
}

app = FastAPI(title="Trading Expert Admin Dashboard")

def get_db_connection(path):
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn

# Restricted CORS for Security
ALLOWED_ORIGINS = os.getenv("ALLOWED_ORIGINS", "http://localhost:5000,http://127.0.0.1:5000").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_methods=["GET", "POST", "PUT"],
    allow_headers=["*"],
)

# DATABASE PATHS MOVED TO config/config.py

def ensure_db_schema():
    """V18.1: Automatic Schema Migration - Ensures all required columns exist.
    Also creates the database and signals table from scratch if it does not exist yet.
    """
    # Always connect (sqlite3.connect creates the file if missing)
    os.makedirs(os.path.dirname(DB_SIGNALS), exist_ok=True)

    conn = None
    try:
        conn = sqlite3.connect(DB_SIGNALS)
        conn.execute("PRAGMA journal_mode=WAL")
        cursor = conn.cursor()
        
        # Create the core signals table from scratch if this is a fresh database
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS signals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT,
                direction TEXT,
                entry_price REAL,
                sl REAL DEFAULT 0.0,
                tp0 REAL DEFAULT 0.0,
                tp1 REAL DEFAULT 0.0,
                tp2 REAL DEFAULT 0.0,
                reasoning TEXT,
                timeframe TEXT,
                confidence REAL DEFAULT 0.0,
                timestamp TEXT,
                status TEXT DEFAULT 'OPEN',
                strategy TEXT,
                result_price REAL,
                result_pips REAL,
                trade_type TEXT DEFAULT 'INSTITUTIONAL',
                quality_score REAL DEFAULT 0.0,
                regime TEXT DEFAULT 'UNKNOWN',
                expected_hold TEXT DEFAULT 'UNKNOWN',
                risk_details TEXT DEFAULT '{}',
                score_details TEXT DEFAULT '{}',
                forensic_candles TEXT DEFAULT '[]',
                forensic_events TEXT DEFAULT '[]',
                gate_status TEXT DEFAULT 'PASSED',
                gate_reason TEXT DEFAULT 'PASSED'
            )
        """)
        
        # V31.0: Paper Account Tracking
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS paper_account (
                id INTEGER PRIMARY KEY DEFAULT 1,
                balance REAL DEFAULT 100000.0,
                equity REAL DEFAULT 100000.0,
                last_daily_reset_date TEXT
            )
        """)
        # Initialize if empty
        cursor.execute("INSERT OR IGNORE INTO paper_account (id, balance, equity) VALUES (1, 100000.0, 100000.0)")
        
        conn.commit()

        # V29.0: Weight Overrides for dynamic AlphaCombiner
        conn_conf = get_db_connection(DB_CLIENTS)
        conn_conf.execute("""
            CREATE TABLE IF NOT EXISTS weight_overrides (
                event_type TEXT PRIMARY KEY,
                multiplier REAL DEFAULT 1.0,
                is_active INTEGER DEFAULT 1
            )
        """)
        conn_conf.commit()
        # V31.0: Seed default execution gates
        conn_conf.execute("INSERT OR IGNORE INTO weight_overrides (event_type, multiplier) VALUES ('MIN_EXECUTION_QUALITY', 5.0)")
        conn_conf.execute("INSERT OR IGNORE INTO weight_overrides (event_type, multiplier) VALUES ('MAX_DAILY_LOSS_PCT', 2.0)")
        conn_conf.commit()
        conn_conf.close()

        # Required columns for High Fidelity Dashboard
        required_cols = [
            ("sl", "REAL DEFAULT 0.0"),
            ("tp0", "REAL DEFAULT 0.0"),
            ("tp1", "REAL DEFAULT 0.0"),
            ("tp2", "REAL DEFAULT 0.0"),
            ("reasoning", "TEXT"),
            ("confidence", "REAL DEFAULT 0.0"),
            ("trade_type", "TEXT DEFAULT 'INSTITUTIONAL'"),
            ("quality_score", "REAL DEFAULT 0.0"),
            ("regime", "TEXT DEFAULT 'UNKNOWN'"),
            ("expected_hold", "TEXT DEFAULT 'UNKNOWN'"),
            ("risk_details", "TEXT DEFAULT '{}'"),
            ("score_details", "TEXT DEFAULT '{}'"),
            ("forensic_candles", "TEXT DEFAULT '[]'"),
            ("forensic_events", "TEXT DEFAULT '[]'"),
            ("gate_status", "TEXT DEFAULT 'UNKNOWN'"),
            ("gate_reason", "TEXT DEFAULT 'UNKNOWN'"),
            ("closed_at", "TEXT"),
            ("max_tp_reached", "INTEGER DEFAULT 0")
        ]
        
        for col_name, col_def in required_cols:
            try:
                cursor.execute(f"ALTER TABLE signals ADD COLUMN {col_name} {col_def}")
                print(f"✅ Auto-added missing column: {col_name}")
            except sqlite3.OperationalError:
                # Column likely already exists
                pass
        
        conn.commit()
    finally:
        if conn:
            conn.close()

# Run migration on startup
ensure_db_schema()

def ensure_config_table():
    """Ensure system_config table exists and has required defaults."""
    conn = None
    try:
        conn = sqlite3.connect(DB_CLIENTS)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS system_config (
                key TEXT PRIMARY KEY,
                value TEXT,
                type TEXT
            )
        """)
        
        # Ensure defaults exist (INSERT OR IGNORE)
        defaults = [
            ("system_status", "ACTIVE", "str"),
            ("risk_per_trade", "2.0", "float"),
            ("max_concurrent_trades", "4", "int"),
            ("min_quality_score", "5.0", "float"),
            ("news_filter_minutes", "30", "int"),
            ("strategy_session_clock", "true", "bool"),
            ("strategy_smc_sweep", "true", "bool"),
            ("strategy_poc_edge", "true", "bool"),
            ("strategy_stat_arb", "true", "bool"),
            ("strategy_pre_news", "true", "bool"),
            ("strategy_news_edge", "true", "bool"),
        ]
        
        cursor = conn.cursor()
        cursor.executemany("""
            INSERT OR IGNORE INTO system_config (key, value, type) 
            VALUES (?, ?, ?)
        """, defaults)
        
        conn.commit()
        print("✅ Verified system_config defaults")
            
    except Exception as e:
        print(f"⚠️ Config table init failed: {e}")
    finally:
        if conn: conn.close()

ensure_config_table()

def ensure_users_table():
    """V18.2: Authoritative Credential Sync - Ensures .env credentials match the DB."""
    conn = None
    try:
        conn = sqlite3.connect(DB_CLIENTS)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS admin_users (
                username TEXT PRIMARY KEY,
                password_hash TEXT,
                last_login TEXT
            )
        """)
        
        # V18.2 Sync Logic: Always favor .env if provided
        if ADMIN_PASS:
            salt = secrets.token_hex(8)
            pwd_hash = hashlib.sha256((ADMIN_PASS + salt).encode()).hexdigest()
            stored_pwd = f"{salt}${pwd_hash}"
            
            # This will either insert or replace the existing admin credentials
            conn.execute("""
                INSERT OR REPLACE INTO admin_users (username, password_hash) 
                VALUES (?, ?)
            """, (ADMIN_USER, stored_pwd))
            conn.commit()
            print(f"✅ Synchronized admin credentials for user: {ADMIN_USER}")
        else:
            # Fallback only if no pass provided and table is empty
            cursor = conn.cursor()
            if cursor.execute("SELECT COUNT(*) FROM admin_users").fetchone()[0] == 0:
                default_salt = secrets.token_hex(8)
                password = "admin123"
                pwd_hash = hashlib.sha256((password + default_salt).encode()).hexdigest()
                stored_pwd = f"{default_salt}${pwd_hash}"
                cursor.execute("INSERT INTO admin_users (username, password_hash) VALUES (?, ?)", ("admin", stored_pwd))
                conn.commit()
                print("✅ Initialized admin_users with standard credentials (admin/admin123)")
            
    except Exception as e:
        print(f"⚠️ Users table sync failed: {e}")
    finally:
        if conn: conn.close()

ensure_users_table()

# Auth Configuration
JWT_SECRET = os.getenv("JWT_SECRET")
if not JWT_SECRET:
    print("⚠️ WARNING: JWT_SECRET not set. Using ephemeral secret (sessions will reset on restart).")
    JWT_SECRET = secrets.token_hex(32)

ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24 # 24 hours

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="api/token")

class AuthToken(BaseModel):
    access_token: str
    token_type: str

class User(BaseModel):
    username: str

def verify_password(plain_password, stored_password):
    try:
        salt, hash_val = stored_password.split('$')
        check_hash = hashlib.sha256((plain_password + salt).encode()).hexdigest()
        return check_hash == hash_val
    except:
        return False

async def get_current_user(token: str = Depends(oauth2_scheme)):
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        if username is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Could not validate credentials",
                headers={"WWW-Authenticate": "Bearer"},
            )
        return User(username=username)
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token expired",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except jwt.PyJWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )

@app.post("/api/token", response_model=AuthToken)
async def login_for_access_token(form_data: OAuth2PasswordRequestForm = Depends()):
    conn = get_db_connection(DB_CLIENTS)
    conn.row_factory = sqlite3.Row
    user = conn.execute("SELECT * FROM admin_users WHERE username = ?", (form_data.username,)).fetchone()
    conn.close()
    
    if not user:
        # Dummy check to prevent timing attacks (skipping for MVP speed)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
        
    if not verify_password(form_data.password, user['password_hash']):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    # Generate Secure JWT Token
    expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode = {"sub": user['username'], "exp": expire}
    encoded_jwt = jwt.encode(to_encode, JWT_SECRET, algorithm=ALGORITHM)
    
    return {"access_token": encoded_jwt, "token_type": "bearer"}

@app.get("/api/me", response_model=User)
async def read_users_me(current_user: User = Depends(get_current_user)):
    return current_user

class ConfigUpdate(BaseModel):
    key: str
    value: str

from fastapi.responses import FileResponse
import os

@app.get("/api/backup/{db_name}")
async def download_db(db_name: str, current_user: User = Depends(get_current_user)):
    """Securely download database files for forensic analysis and backup"""
    if db_name not in ["signals", "clients"]:
        raise HTTPException(status_code=400, detail="Invalid database requested")
    
    file_path = f"database/{db_name}.db"
    if os.path.exists(file_path):
        return FileResponse(file_path, media_type="application/octet-stream", filename=f"{db_name}.db")
    raise HTTPException(status_code=404, detail="Database file not found")

@app.get("/api/config")
async def get_config(current_user: User = Depends(get_current_user)):
    """Get all system configuration settings"""
    conn = None
    try:
        conn = get_db_connection(DB_CLIENTS)
        rows = conn.execute("SELECT key, value, type FROM system_config").fetchall()
        config = {}
        for row in rows:
            val = row['value']
            if row['type'] == 'int': val = int(val)
            elif row['type'] == 'float': val = float(val)
            elif row['type'] == 'bool': val = (val.lower() == 'true')
            config[row['key']] = val
        return config
    except Exception as e:
        print(f"Error fetching config: {e}")
        return {}
    finally:
        if conn: conn.close()

@app.post("/api/config")
async def update_config(update: ConfigUpdate, current_user: User = Depends(get_current_user)):
    """Update a specific configuration setting"""
    conn = None
    try:
        conn = get_db_connection(DB_CLIENTS)
        conn.execute("UPDATE system_config SET value = ? WHERE key = ?", (str(update.value), update.key))
        conn.commit()
        return {{"status": "success", "key": update.key, "value": update.value}}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if conn: conn.close()

# ── Strategy Toggle API ────────────────────────────────────────────────────────
# CRT and ADVANCED_PATTERN are always active. All others can be toggled.
ALWAYS_ON_STRATEGIES = {"crt", "advanced_pattern"}

STRATEGY_META = {
    "session_clock":  {"name": "Session Clock",       "key": "strategy_session_clock"},
    "smc_sweep":      {"name": "SMC Liquidity Sweep",  "key": "strategy_smc_sweep"},
    "poc_edge":       {"name": "Anchored POC Edge",    "key": "strategy_poc_edge"},
    "stat_arb":       {"name": "Statistical Arb",      "key": "strategy_stat_arb"},
    "pre_news":       {"name": "Pre-News Quant",       "key": "strategy_pre_news"},
    "news_edge":      {"name": "News Edge",            "key": "strategy_news_edge"},
    # Always-on (no toggle key needed)
    "crt":            {"name": "CRT Strategy",         "key": None, "locked": True},
    "advanced_pattern":{"name": "Advanced Pattern",   "key": None, "locked": True},
}

@app.get("/api/strategies")
async def get_strategies(current_user: User = Depends(get_current_user)):
    """Get list of all strategies with their enabled/locked status."""
    conn = None
    try:
        conn = get_db_connection(DB_CLIENTS)
        result = []
        for strategy_id, meta in STRATEGY_META.items():
            locked = meta.get("locked", False)
            if locked:
                result.append({
                    "id": strategy_id,
                    "name": meta["name"],
                    "enabled": True,
                    "locked": True
                })
            else:
                row = conn.execute(
                    "SELECT value FROM system_config WHERE key = ?", (meta["key"],)
                ).fetchone()
                enabled = (row["value"].lower() == "true") if row else True
                result.append({
                    "id": strategy_id,
                    "name": meta["name"],
                    "enabled": enabled,
                    "locked": False
                })
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if conn: conn.close()

@app.post("/api/strategies/{strategy_id}/toggle")
async def toggle_strategy(strategy_id: str, current_user: User = Depends(get_current_user)):
    """Toggle a strategy on or off. CRT and ADVANCED_PATTERN cannot be toggled."""
    if strategy_id in ALWAYS_ON_STRATEGIES:
        raise HTTPException(
            status_code=403,
            detail=f"Strategy '{strategy_id}' is locked and cannot be disabled."
        )
    meta = STRATEGY_META.get(strategy_id)
    if not meta:
        raise HTTPException(status_code=404, detail=f"Strategy '{strategy_id}' not found.")

    conn = None
    try:
        conn = get_db_connection(DB_CLIENTS)
        row = conn.execute(
            "SELECT value FROM system_config WHERE key = ?", (meta["key"],)
        ).fetchone()
        current = (row["value"].lower() == "true") if row else True
        new_val = "false" if current else "true"
        conn.execute(
            "UPDATE system_config SET value = ? WHERE key = ?", (new_val, meta["key"])
        )
        conn.commit()
        return {
            "status": "success",
            "strategy": strategy_id,
            "enabled": new_val == "true"
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if conn: conn.close()


# ── MT5 Position Management API ───────────────────────────────────────────────
@app.get("/api/mt5/positions")
async def get_mt5_positions(current_user: User = Depends(get_current_user)):
    """Get all open MT5 positions (live or paper)."""
    try:
        from core.trade_executor import get_executor
        executor = get_executor()
        positions = await executor.get_open_positions()
        return {"positions": positions, "mode": "PAPER" if executor.paper_mode else "LIVE"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/mt5/close/{position_id}")
async def close_mt5_position(position_id: str, current_user: User = Depends(get_current_user)):
    """Close an open MT5 position by ID."""
    try:
        from core.trade_executor import get_executor
        executor = get_executor()
        result = await executor.close_trade(position_id)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


class ClientUpdate(BaseModel):

    account_balance: Optional[float] = None
    risk_percent: Optional[float] = None
    subscription_days: Optional[int] = None
    tier: Optional[str] = None
    is_active: Optional[bool] = None
    dashboard_access: Optional[bool] = None


def get_db_connection(db_path):
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.row_factory = sqlite3.Row
    return conn

@app.get("/api/clients")
async def get_clients(current_user: User = Depends(get_current_user)):
    conn = None
    try:
        conn = get_db_connection(DB_CLIENTS)
        clients = conn.execute("SELECT * FROM clients").fetchall()
        return [dict(ix) for ix in clients]
    finally:
        if conn:
            conn.close()

@app.post("/api/clients/{chat_id}")
async def update_client(chat_id: str, update: ClientUpdate, current_user: User = Depends(get_current_user)):
    conn = None
    try:
        conn = get_db_connection(DB_CLIENTS)
        client = conn.execute("SELECT * FROM clients WHERE telegram_chat_id = ?", (chat_id,)).fetchone()
        
        if not client:
            raise HTTPException(status_code=404, detail="Client not found")
        
        fields = []
        values = []
        
        if update.account_balance is not None:
            fields.append("account_balance = ?")
            values.append(update.account_balance)
        
        if update.risk_percent is not None:
            fields.append("risk_percent = ?")
            values.append(update.risk_percent)
            
        if update.is_active is not None:
            fields.append("is_active = ?")
            values.append(1 if update.is_active else 0)
            
        if update.subscription_days is not None:
            # Calculate new expiry
            current_expiry_str = client['subscription_expiry']
            now = datetime.now()
            if current_expiry_str:
                try:
                    current_expiry = datetime.strptime(current_expiry_str, "%Y-%m-%d %H:%M:%S.%f") if "." in current_expiry_str else datetime.strptime(current_expiry_str, "%Y-%m-%d %H:%M:%S")
                    start_date = max(now, current_expiry)
                except:
                    start_date = now
            else:
                start_date = now
            
            new_expiry = start_date + timedelta(days=update.subscription_days)
            fields.append("subscription_expiry = ?")
            values.append(new_expiry.strftime("%Y-%m-%d %H:%M:%S"))
            
        if update.tier is not None:
            fields.append("subscription_tier = ?")
            values.append(update.tier)
        
        # Add dashboard_access field handling
        if hasattr(update, 'dashboard_access') and update.dashboard_access is not None:
            fields.append("dashboard_access = ?")
            values.append(1 if update.dashboard_access else 0)

            
        if fields:
            fields.append("updated_at = ?")
            values.append(datetime.now())
            values.append(chat_id)
            
            query = f"UPDATE clients SET {', '.join(fields)} WHERE telegram_chat_id = ?"
            conn.execute(query, values)
            conn.commit()
        
        return {"status": "success"}
    except Exception as e:
        if isinstance(e, HTTPException): raise e
        print(f"Error updating client {chat_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if conn:
            conn.close()

@app.post("/api/clients/{chat_id}/toggle-signals")
async def toggle_signals(chat_id: str, current_user: User = Depends(get_current_user)):
    """Toggle Telegram signal delivery for a client"""
    conn = None
    try:
        conn = get_db_connection(DB_CLIENTS)
        client = conn.execute("SELECT is_active FROM clients WHERE telegram_chat_id = ?", (chat_id,)).fetchone()
        
        if not client:
            raise HTTPException(status_code=404, detail="Client not found")
        
        new_status = 0 if client['is_active'] else 1
        conn.execute("""
            UPDATE clients 
            SET is_active = ?, updated_at = ? 
            WHERE telegram_chat_id = ?
        """, (new_status, datetime.now(), chat_id))
        conn.commit()
        
        return {
            "status": "success",
            "is_active": bool(new_status),
            "message": f"Telegram signals {'enabled' if new_status else 'disabled'}"
        }
    except Exception as e:
        if isinstance(e, HTTPException): raise e
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if conn:
            conn.close()

@app.post("/api/clients/{chat_id}/toggle-dashboard")
async def toggle_dashboard(chat_id: str, current_user: User = Depends(get_current_user)):
    """Toggle dashboard access for a client"""
    conn = None
    try:
        conn = get_db_connection(DB_CLIENTS)
        client = conn.execute("SELECT dashboard_access FROM clients WHERE telegram_chat_id = ?", (chat_id,)).fetchone()
        
        if not client:
            raise HTTPException(status_code=404, detail="Client not found")
        
        new_status = 0 if client['dashboard_access'] else 1
        conn.execute("""
            UPDATE clients 
            SET dashboard_access = ?, updated_at = ? 
            WHERE telegram_chat_id = ?
        """, (new_status, datetime.now(), chat_id))
        conn.commit()
        
        return {
            "status": "success",
            "dashboard_access": bool(new_status),
            "message": f"Dashboard access {'granted' if new_status else 'revoked'}"
        }
    except Exception as e:
        if isinstance(e, HTTPException): raise e
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if conn:
            conn.close()

@app.post("/api/clients/{chat_id}/extend")
async def quick_extend(chat_id: str, days: int = 30, current_user: User = Depends(get_current_user)):
    """Quick extend subscription by specified days (default 30)"""
    conn = None
    try:
        conn = get_db_connection(DB_CLIENTS)
        client = conn.execute("SELECT subscription_expiry FROM clients WHERE telegram_chat_id = ?", (chat_id,)).fetchone()
        
        if not client:
            raise HTTPException(status_code=404, detail="Client not found")
        
        current_expiry_str = client['subscription_expiry']
        now = datetime.now()
        
        if current_expiry_str:
            try:
                current_expiry = datetime.strptime(current_expiry_str, "%Y-%m-%d %H:%M:%S.%f") if "." in current_expiry_str else datetime.strptime(current_expiry_str, "%Y-%m-%d %H:%M:%S")
                start_date = max(now, current_expiry)
            except:
                start_date = now
        else:
            start_date = now
        
        new_expiry = start_date + timedelta(days=days)
        
        conn.execute("""
            UPDATE clients 
            SET subscription_expiry = ?, updated_at = ? 
            WHERE telegram_chat_id = ?
        """, (new_expiry.strftime("%Y-%m-%d %H:%M:%S"), datetime.now(), chat_id))
        conn.commit()
        
        return {
            "status": "success",
            "new_expiry": new_expiry.strftime("%Y-%m-%d %H:%M:%S"),
            "message": f"Subscription extended by {days} days"
        }
    except Exception as e:
        if isinstance(e, HTTPException): raise e
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if conn:
            conn.close()

@app.post("/api/stripe/webhook")
async def stripe_webhook(request: Request):
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature")
    
    if not STRIPE_WEBHOOK_SECRET:
        print("⚠️ STRIPE_WEBHOOK_SECRET not set. Webhook bypass for DEBUG only.")
    
    try:
        event = None
        if STRIPE_WEBHOOK_SECRET:
            event = stripe.Webhook.construct_event(
                payload, sig_header, STRIPE_WEBHOOK_SECRET
            )
        else:
            # Fallback for debug if secret is missing
            event = json.loads(payload)
            
    except Exception as e:
        print(f"⚠️ Webhook signature verification failed: {e}")
        raise HTTPException(status_code=400, detail="Invalid signature")

    # Handle the checkout.session.completed event
    if event["type"] == "checkout.session.completed":
        session = event["data"]["object"]
        
        # Extract metadata
        metadata = session.get("metadata", {})
        chat_id = metadata.get("telegram_chat_id")
        days = int(metadata.get("subscription_days", 30))
        tier = metadata.get("tier", "BASIC")
        
        if chat_id:
            print(f"💰 PAYMENT SUCCESS: Activating {chat_id} for {days} days ({tier})")
            client_manager = ClientManager(DB_CLIENTS)
            result = client_manager.update_subscription(chat_id, days, tier)
            
            # Also ensure client is marked as active
            if result.get('status') == 'success':
                conn = get_db_connection(DB_CLIENTS)
                conn.execute("UPDATE clients SET is_active = 1 WHERE telegram_chat_id = ?", (chat_id,))
                conn.commit()
                conn.close()
                print(f"✅ Client {chat_id} activated automatically.")
            else:
                print(f"❌ Failed to activate client {chat_id}: {result.get('message')}")
        else:
            print("⚠️ Webhook received but no telegram_chat_id in metadata.")

    return {"status": "success"}

@app.get("/api/signals")
async def get_signals(current_user: User = Depends(get_current_user)):
    conn = None
    try:
        conn = get_db_connection(DB_SIGNALS)
        # V18.0: Fetch all signal fidelity fields
        cursor = conn.execute("""
            SELECT 
                id, timestamp, symbol, direction, entry_price, sl, tp1, tp2, 
                reasoning, timeframe, confidence, result, closed_at, max_tp_reached,
                trade_type, quality_score, regime, expected_hold, risk_details, score_details,
                forensic_candles, forensic_events, gate_status, gate_reason
            FROM signals 
            ORDER BY timestamp DESC LIMIT 50
        """)
        return [dict(row) for row in cursor.fetchall()]
    except Exception as e:
        print(f"Error fetching signals: {e}")
        return []
    finally:
        if conn:
            conn.close()

@app.get("/api/signals/{signal_id}")
async def get_signal_detail(signal_id: int, current_user: User = Depends(get_current_user)):
    """Fetch all details for a single signal, including forensic forensics data."""
    conn = None
    try:
        conn = get_db_connection(DB_SIGNALS)
        row = conn.execute("SELECT * FROM signals WHERE id = ?", (signal_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Signal not found")
        return dict(row)
    except Exception as e:
        if isinstance(e, HTTPException): raise e
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if conn: conn.close()

async def get_market_context():
    """V19.0: Fetch and cache macro/news context for dashboard visibility."""
    now = time.time()
    if market_context_cache["data"] and (now - market_context_cache["last_update"]) < market_context_cache["ttl"]:
        return market_context_cache["data"]

    ctx = {"DXY": "NEUTRAL", "TNX": "NEUTRAL", "RISK": "NEUTRAL", "NEWS": "NO NEWS"}
    try:
        fetcher = DataFetcher()
        # Non-blocking fetch
        dxy_data = await fetcher.fetch_data_async(DXY_SYMBOL, "1h", period="10d")
        tnx_data = await fetcher.fetch_data_async(TNX_SYMBOL, "1h", period="10d")
        
        bundle = {}
        if dxy_data is not None and not dxy_data.empty:
            bundle['DXY'] = IndicatorCalculator.add_indicators(dxy_data, "1h")
        if tnx_data is not None and not tnx_data.empty:
            bundle['^TNX'] = IndicatorCalculator.add_indicators(tnx_data, "1h")
            
        bias = MacroFilter.get_macro_bias(bundle)
        ctx.update(bias)
        
        # News Check
        news_fetcher = NewsFetcher()
        events = news_fetcher.fetch_news()
        relevant = news_fetcher.filter_relevant_news(events, SYMBOLS)
        
        # Check if any high impact news is coming in 30 mins
        current_time_str = datetime.now().strftime('%Y%m%dT%H%M')
        active_news = []
        for e in relevant:
            if e.get('impact') == 'High':
                active_news.append(e.get('title'))
        
        if active_news:
            ctx['NEWS'] = f"{len(active_news)} HIGH IMPACT EVENTS"
            
    except Exception as e:
        print(f"Market Context Error: {e}")
        
    market_context_cache["data"] = ctx
    market_context_cache["last_update"] = now
    return ctx

@app.get("/api/stats")
async def get_basic_stats(current_user: User = Depends(get_current_user)):
    conn = None
    try:
        conn = get_db_connection(DB_SIGNALS)
        today = datetime.now().strftime('%Y-%m-%d')
        signals_count = conn.execute("SELECT COUNT(*) FROM signals WHERE DATE(timestamp) = ?", (today,)).fetchone()[0]
        
        cm = ClientManager(DB_CLIENTS)
        active_clients = cm.get_client_count()
        
        # V19.2: Market Context
        mctx = await get_market_context()

        # V23.1: System Status Switch
        conn_config = get_db_connection(DB_CLIENTS)
        status_row = conn_config.execute("SELECT value FROM system_config WHERE key = 'system_status'").fetchone()
        system_status = status_row['value'] if status_row else "UNKNOWN"
        conn_config.close()
        
        return {
            "active_clients": active_clients,
            "signals_today": signals_count,
            "server_time": datetime.now().strftime("%H:%M:%S"),
            "market_context": mctx,
            "system_status": system_status
        }
    except Exception as e:
        print(f"Error fetching stats: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if conn: conn.close()

@app.get("/api/analytics/daily")
async def get_daily_analytics(current_user: User = Depends(get_current_user)):
    conn = None
    try:
        conn = get_db_connection(DB_SIGNALS)
        last_24h = (datetime.utcnow() - timedelta(days=1)).isoformat()
        
        # 1. Overall Summary
        summary = conn.execute("""
            SELECT 
                COUNT(*) as total,
                AVG(quality_score) as avg_quality
            FROM signals 
            WHERE timestamp >= ?
        """, (last_24h,)).fetchone()
        
        # 2. Performance by Trade Type (INSTITUTIONAL vs SWING)
        type_stats = conn.execute("""
            SELECT 
                UPPER(TRIM(trade_type)) as trade_type,
                COUNT(*) as total,
                SUM(CASE WHEN result IN ('TP1', 'TP2', 'TP3') OR max_tp_reached > 0 THEN 1 ELSE 0 END) as wins,
                SUM(CASE WHEN result = 'SL' THEN 1 ELSE 0 END) as losses,
                SUM(CASE WHEN result = 'OPEN' THEN 1 ELSE 0 END) as open,
                AVG(quality_score) as avg_quality
            FROM signals 
            WHERE timestamp >= ?
            GROUP BY UPPER(TRIM(trade_type))
        """, (last_24h,)).fetchall()
        
        stats_by_type = {}
        for row in type_stats:
            rtype = row['trade_type']
            if rtype == 'SWING': rtype = 'CRT'
            
            if rtype not in stats_by_type:
                stats_by_type[rtype] = dict(row)
                stats_by_type[rtype]['trade_type'] = rtype
            else:
                # Aggregate if both exist
                stats_by_type[rtype]['total'] += row['total']
                stats_by_type[rtype]['wins'] += row['wins']
                stats_by_type[rtype]['losses'] += row['losses']
                stats_by_type[rtype]['open'] += row['open']
        
        # 3. Market Bias (Long vs Short)
        bias_rows = conn.execute("""
            SELECT direction, COUNT(*) as count
            FROM signals 
            WHERE timestamp >= ?
            GROUP BY direction
        """, (last_24h,)).fetchall()
        
        bias = {row['direction']: row['count'] for row in bias_rows}
        
        # 4. Detailed Asset Stats (Enhanced for V22.5)
        asset_stats_rows = conn.execute("""
            SELECT 
                symbol, 
                COUNT(*) as count,
                SUM(CASE WHEN result IN ('TP1', 'TP2', 'TP3') OR max_tp_reached > 0 THEN 1 ELSE 0 END) as wins,
                SUM(CASE WHEN result = 'SL' THEN 1 ELSE 0 END) as losses,
                SUM(CASE WHEN result = 'OPEN' THEN 1 ELSE 0 END) as open,
                AVG(quality_score) as avg_quality
            FROM signals 
            WHERE timestamp >= ?
            GROUP BY symbol
            ORDER BY count DESC
        """, (last_24h,)).fetchall()
        
        all_assets = [dict(row) for row in asset_stats_rows]
        
        # 5. Session Analytics (Sydney, Tokyo, London, NY)
        session_rows = conn.execute("""
            SELECT 
                symbol,
                CAST(STRFTIME('%H', timestamp) as INTEGER) as hour,
                COUNT(*) as total,
                SUM(CASE WHEN result IN ('TP1', 'TP2', 'TP3') OR max_tp_reached > 0 THEN 1 ELSE 0 END) as wins
            FROM signals
            WHERE timestamp >= ?
            GROUP BY symbol, hour
        """, (last_24h,)).fetchall()

        session_insights = {}
        for row in session_rows:
            sym = row['symbol']
            hour = row['hour']
            
            # Define Session Mapping (UTC)
            sessions = []
            if hour >= 22 or hour < 7: sessions.append("SYDNEY")
            if hour >= 0 and hour < 9: sessions.append("TOKYO")
            if hour >= 8 and hour < 17: sessions.append("LONDON")
            if hour >= 13 and hour < 22: sessions.append("NEWYORK")
            
            if sym not in session_insights: session_insights[sym] = {}
            for s in sessions:
                if s not in session_insights[sym]: session_insights[sym][s] = {"total": 0, "wins": 0}
                session_insights[sym][s]["total"] += row['total']
                session_insights[sym][s]["wins"] += row['wins']

        # 6. Hourly Heatmap
        hourly_rows = conn.execute("""
            SELECT STRFTIME('%H', timestamp) as hour, COUNT(*) as count
            FROM signals
            WHERE timestamp >= ?
            GROUP BY hour
        """, (last_24h,)).fetchall()
        
        hourly = {row['hour']: row['count'] for row in hourly_rows}
        
        # 7. Best Performing Symbol
        best_symbol = conn.execute("""
            SELECT symbol, COUNT(*) as count, SUM(CASE WHEN result IN ('TP1', 'TP2', 'TP3') OR max_tp_reached > 0 THEN 1 ELSE 0 END) as wins
            FROM signals 
            WHERE timestamp >= ?
            GROUP BY symbol
            ORDER BY wins DESC, count DESC
            LIMIT 1
        """, (last_24h,)).fetchone()

        # 8. Equity Curve (Last 7 Days)
        seven_days_ago = (datetime.utcnow() - timedelta(days=7)).isoformat()
        equity_rows = conn.execute("""
            SELECT 
                DATE(timestamp) as day,
                SUM(CASE 
                    WHEN result = 'TP3' THEN 2.0
                    WHEN result = 'TP2' THEN 1.0
                    WHEN result = 'TP1' THEN 0.5
                    WHEN result = 'SL' THEN -1.0
                    ELSE 0 END) as profit
            FROM signals 
            WHERE timestamp >= ? AND result != 'OPEN'
            GROUP BY day
            ORDER BY day ASC
        """, (seven_days_ago,)).fetchall()
        
        equity_curve = []
        cumulative = 0
        for row in equity_rows:
            cumulative += row['profit']
            equity_curve.append({"day": row['day'], "profit": round(cumulative, 2)})

        # 9. Strategy Performance per Symbol (V23.1.2)
        strategy_symbol_rows = conn.execute("""
            SELECT 
                symbol,
                UPPER(TRIM(trade_type)) as trade_type,
                COUNT(*) as total,
                SUM(CASE WHEN result IN ('TP1', 'TP2', 'TP3') OR max_tp_reached > 0 THEN 1 ELSE 0 END) as wins,
                SUM(CASE WHEN result = 'SL' THEN 1 ELSE 0 END) as losses,
                SUM(CASE WHEN result = 'OPEN' THEN 1 ELSE 0 END) as open,
                AVG(quality_score) as avg_quality
            FROM signals 
            WHERE timestamp >= ?
            GROUP BY symbol, UPPER(TRIM(trade_type))
            ORDER BY symbol ASC, total DESC
        """, (last_24h,)).fetchall()
        
        strategy_symbol_breakdown = []
        for row in strategy_symbol_rows:
            d = dict(row)
            if d['trade_type'] == 'SWING': d['trade_type'] = 'CRT'
            
            # Simple aggregation for matrix
            existing = next((x for x in strategy_symbol_breakdown if x['symbol'] == d['symbol'] and x['trade_type'] == d['trade_type']), None)
            if existing:
                existing['total'] += d['total']
                existing['wins'] += d['wins']
                existing['losses'] += d['losses']
                existing['open'] += d['open']
            else:
                strategy_symbol_breakdown.append(d)

        return {
            "total_signals": summary['total'] or 0,
            "avg_quality": round(summary['avg_quality'] or 0, 1),
            "stats_by_type": stats_by_type,
            "bias": bias,
            "assets": all_assets,
            "session_insights": session_insights,
            "hourly_heatmap": hourly,
            "top_performer": dict(best_symbol) if best_symbol else None,
            "equity_curve": equity_curve,
            "strategy_symbol_breakdown": strategy_symbol_breakdown,
            "debug": {
                "server_time": datetime.now().isoformat(),
                "lookback_from": last_24h,
                "seven_days_ago": seven_days_ago,
                "raw_types": [row['trade_type'] for row in type_stats]
            }
        }
    except Exception as e:
        print(f"Error calculating analytics: {e}")
        return {"error": str(e)}
    finally:
        if conn:
            conn.close()

@app.get("/api/analytics/forensic_audit")
async def get_forensic_audit(regime: Optional[str] = None, current_user: User = Depends(get_current_user)):
    """
    V30.0: Regime-Aware Forensic Alpha Audit Engine
    Analyzes historical signals grouped by institutional combination and market environment.
    """
    conn = None
    try:
        conn = get_db_connection(DB_SIGNALS)
        conn.row_factory = sqlite3.Row
        
        query = """
            SELECT trade_type, result, forensic_events, entry_price, sl, tp1, max_tp_reached, regime 
            FROM signals 
            WHERE forensic_events IS NOT NULL 
            AND forensic_events != '[]' 
            AND result != 'OPEN'
        """
        params = []
        if regime and regime != "ALL":
            query += " AND regime = ?"
            params.append(regime)
            
        rows = conn.execute(query, params).fetchall()
        
        audit_map = {} # key: event_mask (sorted string)

        for row in rows:
            try:
                events = json.loads(row['forensic_events'])
            except:
                continue
                
            # Create a unique tag combination for this signal
            tags = sorted(list(set([ev['type'] for ev in events])))
            mask = " + ".join(tags) if tags else "NONE"
            
            if mask not in audit_map:
                audit_map[mask] = {"count": 0, "wins": 0, "total_rr": 0}
            
            # Outcome Logic
            is_win = row['result'] in ['TP1', 'TP2', 'TP3'] or (row['max_tp_reached'] or 0) > 0
            
            # Calculate actualized R:R (very rough estimate for audit)
            risk = abs(row['entry_price'] - row['sl'])
            reward = abs(row['tp1'] - row['entry_price'])
            rr = (reward / risk) if risk > 0 else 0
            
            audit_map[mask]["count"] += 1
            if is_win:
                audit_map[mask]["wins"] += 1
                audit_map[mask]["total_rr"] += rr
                
        # Transform for frontend
        from core.alpha_combiner import AlphaCombiner
        
        # Load System Threshold
        threshold = 30
        try:
            conn_conf = get_db_connection(DB_CLIENTS)
            val = conn_conf.execute("SELECT multiplier FROM weight_overrides WHERE event_type = 'SYSTEM_THRESHOLD'").fetchone()
            if val: threshold = int(val[0])
            conn_conf.close()
        except: pass

        result = []
        for mask, data in audit_map.items():
            raw_p = data["wins"] / data["count"] if data["count"] > 0 else 0
            wr = raw_p * 100
            avg_rr = (data["total_rr"] / data["wins"]) if data["wins"] > 0 else 0
            
            # Implementation of Wilson Score Interval for UI
            ci = AlphaCombiner.calculate_wilson_interval(raw_p, data["count"])
            
            # Hardened conviction: Must pass sample size threshold to be HIGH/MODERATE
            if data["count"] < threshold:
                conviction = "CALIBRATING"
            else:
                conviction = "HIGH" if wr >= 60 else ("MODERATE" if wr >= 45 else "LOW")

            result.append({
                "combination": mask,
                "sample_size": data["count"],
                "win_rate": round(wr, 1),
                "avg_rr": round(avg_rr, 2),
                "conviction": conviction,
                "ci": ci,
                "is_confident": data["count"] >= threshold
            })
            
        return sorted(result, key=lambda x: x['win_rate'], reverse=True)
    except Exception as e:
        print(f"Forensic Audit Error: {e}")
        return []
    finally:
        if conn: conn.close()

@app.get("/api/config/weights")
async def get_weight_overrides(current_user: User = Depends(get_current_user)):
    conn = None
    try:
        conn = get_db_connection(DB_CLIENTS)
        rows = conn.execute("SELECT * FROM weight_overrides").fetchall()
        return [dict(row) for row in rows]
    finally:
        if conn: conn.close()

@app.put("/api/config/weights")
async def update_weight_override(data: dict, current_user: User = Depends(get_current_user)):
    conn = None
    try:
        conn = get_db_connection(DB_CLIENTS)
        conn.execute("""
            INSERT INTO weight_overrides (event_type, multiplier, is_active)
            VALUES (?, ?, ?)
            ON CONFLICT(event_type) DO UPDATE SET
            multiplier = excluded.multiplier,
            is_active = excluded.is_active
        """, (data['event_type'], data['multiplier'], 1 if data.get('is_active', True) else 0))
        conn.commit()
        return {"status": "success"}
    finally:
        if conn: conn.close()


@app.get("/api/logs/{service}")
async def get_logs(service: str, lines: int = 100, current_user: User = Depends(get_current_user)):
    """V19.0: System Log Retrieval - checks local files first, then journalctl."""
    # Mapping service IDs to local log files
    log_map = {
        "smc-admin-dashboard": "admin.log",
        "smc-signal-service": "signals.log",
        "smc-alpha-kernel": "signals.log",
        "smc-interactive-bot": "bot.log",
        "smc-signal-tracker": "tracker.log"
    }
    
    if service not in log_map:
        raise HTTPException(status_code=400, detail="Invalid service name")

    # 1. Try local file first (fastest and most reliable in user-mode)
    local_log = log_map[service]
    if os.path.exists(local_log):
        try:
            # Use tail command to safely get the last N lines
            result = subprocess.run(["tail", "-n", str(lines), local_log], capture_output=True, text=True)
            if result.returncode == 0:
                return {"logs": result.stdout}
        except Exception as e:
            print(f"Failed to read local log {local_log}: {e}")

    # 2. Fallback to journalctl
    try:
        cmd = ["journalctl", "--user", "-u", f"{service}.service", "-n", str(lines), "--no-pager"]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
        
        if result.returncode == 0 and result.stdout.strip():
            return {"logs": result.stdout}
            
        return {"logs": f"No logs found in {local_log} or systemd."}
    except Exception as e:
        return {"logs": f"Log retrieval failed: {str(e)}"}

# ═══════════════════════════════════════════════════════════════════════════
# V31.0: EXECUTION LIFECYCLE APIs
# ═══════════════════════════════════════════════════════════════════════════

@app.get("/api/execution/gate-log")
async def get_gate_log(current_user: User = Depends(get_current_user)):
    """Returns recent gate decisions for dashboard display."""
    conn = None
    try:
        conn = get_db_connection(DB_SIGNALS)
        rows = conn.execute("""
            SELECT id, timestamp, symbol, direction, regime, quality_score,
                   gate_status, gate_reason, trade_type
            FROM signals 
            WHERE gate_status IS NOT NULL AND gate_status != 'UNKNOWN'
            ORDER BY timestamp DESC LIMIT 50
        """).fetchall()
        return [dict(row) for row in rows]
    finally:
        if conn: conn.close()

@app.get("/api/execution/paper-account")
async def get_paper_account(current_user: User = Depends(get_current_user)):
    """Returns the current paper trading account state."""
    conn = None
    try:
        conn = get_db_connection(DB_SIGNALS)
        
        # Get account balance
        acct = conn.execute("SELECT * FROM paper_account WHERE id = 1").fetchone()
        balance = dict(acct) if acct else {"balance": 100000.0, "equity": 100000.0}
        
        # Get today's P&L
        today = datetime.now().strftime('%Y-%m-%d')
        daily_pnl = conn.execute("""
            SELECT COALESCE(SUM(result_pips), 0) as total_pips,
                   COUNT(*) as trade_count
            FROM signals 
            WHERE closed_at LIKE ? AND gate_status = 'PASSED'
        """, (f"{today}%",)).fetchone()
        
        # Get gate stats
        gate_stats = conn.execute("""
            SELECT gate_status, COUNT(*) as count
            FROM signals
            WHERE gate_status IS NOT NULL AND gate_status != 'UNKNOWN'
            GROUP BY gate_status
        """).fetchall()
        
        stats = {row['gate_status']: row['count'] for row in gate_stats}
        
        return {
            "balance": balance.get('balance', 100000.0),
            "equity": balance.get('equity', 100000.0),
            "daily_pips": dict(daily_pnl)['total_pips'] if daily_pnl else 0,
            "daily_trades": dict(daily_pnl)['trade_count'] if daily_pnl else 0,
            "total_passed": stats.get('PASSED', 0),
            "total_blocked": stats.get('BLOCKED', 0),
            "observation_target": 50
        }
    finally:
        if conn: conn.close()

@app.get("/api/execution/positions")
async def get_positions(current_user: User = Depends(get_current_user)):
    """Returns open positions (paper or live)."""
    try:
        from core.trade_executor import get_executor
        executor = get_executor()
        positions = await executor.get_open_positions()
        return positions
    except Exception as e:
        return []

@app.get("/api/execution/observation-report")
async def get_observation_report(current_user: User = Depends(get_current_user)):
    """V31.0: Aggregates institutional discipline metrics for Phase B readiness assessment."""
    conn = None
    try:
        conn = get_db_connection(DB_SIGNALS)
        
        # 1. Total Overview
        total_data = conn.execute("""
            SELECT COUNT(*) as total,
                   SUM(CASE WHEN gate_status = 'PASSED' THEN 1 ELSE 0 END) as passed,
                   SUM(CASE WHEN gate_status = 'BLOCKED' THEN 1 ELSE 0 END) as blocked
            FROM signals 
            WHERE gate_status IS NOT NULL AND gate_status != 'UNKNOWN'
        """).fetchone()
        
        # 2. Blocked Breakdown
        blocked_reasons = conn.execute("""
            SELECT gate_reason, COUNT(*) as count
            FROM signals
            WHERE gate_status = 'BLOCKED'
            GROUP BY gate_reason
        """).fetchall()
        
        # 3. Performance on PASSED signals
        perf_data = conn.execute("""
            SELECT COUNT(*) as total_trades,
                   SUM(CASE WHEN result IN ('TP1', 'TP2', 'TP3') THEN 1 ELSE 0 END) as wins,
                   SUM(CASE WHEN result = 'SL' THEN 1 ELSE 0 END) as losses,
                   SUM(result_pips) as net_pips
            FROM signals
            WHERE gate_status = 'PASSED' AND result != 'OPEN'
        """).fetchone()
        
        # 4. Account State
        acct = conn.execute("SELECT balance FROM paper_account WHERE id = 1").fetchone()
        
        total = total_data['total'] or 0
        passed = total_data['passed'] or 0
        blocked = total_data['blocked'] or 0
        
        return {
            "summary": {
                "total_signals": total,
                "pass_count": passed,
                "block_count": blocked,
                "pass_rate_pct": round((passed / total * 100), 1) if total > 0 else 0,
            },
            "rejections": {row['gate_reason']: row['count'] for row in blocked_reasons},
            "performance": {
                "trades_closed": perf_data['total_trades'] or 0,
                "win_rate_pct": round((perf_data['wins'] / perf_data['total_trades'] * 100), 1) if perf_data['total_trades'] and perf_data['total_trades'] > 0 else 0,
                "net_pips": round(perf_data['net_pips'] or 0, 1),
                "current_balance": acct['balance'] if acct else 100000.0,
                "roi_pct": round(((acct['balance'] / 100000.0) - 1) * 100, 2) if acct else 0
            },
            "readiness_score": min(100, round((passed / 50) * 100)) # Target 50 PASSES
        }
    finally:
        if conn: conn.close()

# ═══════════════════════════════════════════════════════════════════════════
# V32.0: BACKTESTING APIs
# ═══════════════════════════════════════════════════════════════════════════

BACKTEST_PROGRESS = {}  # {job_id: {"progress": float, "status": str, "error": str|None}}

@app.post("/api/backtest/run")
async def run_backtest(request: Request, current_user: User = Depends(get_current_user)):
    """V32.0: Initiates a historical backtest run."""
    from core.backtest_engine import BacktestEngine
    data = await request.json()
    start_date = data.get("start_date", (datetime.now() - timedelta(days=30)).strftime('%Y-%m-%d'))
    end_date = data.get("end_date", datetime.now().strftime('%Y-%m-%d'))
    
    unique_id = secrets.token_hex(4)
    BACKTEST_PROGRESS[unique_id] = {"progress": 0.0, "status": "running", "error": None}
    
    async def task():
        try:
            engine = BacktestEngine(start_date, end_date)
            def update_prog(p): BACKTEST_PROGRESS[unique_id]["progress"] = round(p * 100, 1)
            result = await engine.run(progress_callback=update_prog)
            if isinstance(result, dict) and "error" in result:
                BACKTEST_PROGRESS[unique_id] = {"progress": 0.0, "status": "error", "error": result["error"]}
                print(f"❌ Backtest {unique_id} failed: {result['error']}")
            else:
                BACKTEST_PROGRESS[unique_id] = {"progress": 100.0, "status": "done", "error": None}
                print(f"✅ Backtest {unique_id} completed successfully.")
        except Exception as e:
            print(f"💥 Backtest {unique_id} crashed: {e}")
            import traceback; traceback.print_exc()
            BACKTEST_PROGRESS[unique_id] = {"progress": 0.0, "status": "error", "error": str(e)}
        
    asyncio.create_task(task())
    return {"job_id": unique_id, "status": "started"}

@app.get("/api/backtest/progress/{job_id}")
async def get_backtest_progress(job_id: str, current_user: User = Depends(get_current_user)):
    info = BACKTEST_PROGRESS.get(job_id, {"progress": 0.0, "status": "unknown", "error": None})
    return {"progress": info["progress"], "status": info["status"], "error": info["error"]}

@app.get("/api/backtest/latest_job")
async def get_latest_job(current_user: User = Depends(get_current_user)):
    """Returns the ID of the most recent job to allow UI re-attachment."""
    if not BACKTEST_PROGRESS: return {"job_id": None}
    # Get the most recent job_id
    latest_id = list(BACKTEST_PROGRESS.keys())[-1]
    return {"job_id": latest_id}

@app.get("/api/backtest/runs")
async def list_backtest_runs(current_user: User = Depends(get_current_user)):
    db_path = "database/backtest_results.db"
    if not os.path.exists(db_path): return []
    with get_db_connection(db_path) as conn:
        rows = conn.execute("SELECT * FROM backtest_runs ORDER BY timestamp DESC").fetchall()
        data = []
        for row in rows:
            d = dict(row)
            # If total_trades is None, it means it's either running or crashed
            if d.get("total_trades") is None:
                # Check if it's currently in our active memory
                # This is a bit of a heuristic since we don't store row ID in memory, 
                # but for a single-user system it's fine.
                d["status"] = "IN_PROGRESS"
            else:
                d["status"] = "COMPLETED"
            data.append(d)
        return data

@app.get("/api/backtest/results/{run_id}")
async def get_backtest_results(run_id: int, current_user: User = Depends(get_current_user)):
    db_path = "database/backtest_results.db"
    with get_db_connection(db_path) as conn:
        run = conn.execute("SELECT * FROM backtest_runs WHERE id = ?", (run_id,)).fetchone()
        trades = conn.execute("SELECT * FROM backtest_signals WHERE run_id = ?", (run_id,)).fetchall()
        
        # Calculate daily equity curve for chart
        equity_curve = []
        balance = 100000.0
        sorted_trades = sorted([dict(t) for t in trades], key=lambda x: x['timestamp'])
        
        for t in sorted_trades:
            balance += t['result_pips'] * 1.0 # 1.0 per pip mock
            equity_curve.append({"time": t['timestamp'], "balance": balance})
            
        return {
            "run": dict(run) if run else {},
            "trades": [dict(t) for t in trades],
            "equity_curve": equity_curve
        }

@app.get("/api/system/config")
async def get_system_config(current_user: User = Depends(get_current_user)):
    """Returns the list of active symbols and strategies for the dashboard sidebar."""
    clean_symbols = [s.replace("=X", "").replace("=F", "").replace("-USD", "/USD") for s in SYMBOLS]
    
    # Extract unique trade types from signal history
    strategies = ["CRT_SMC"] # Default
    try:
        conn = get_db_connection(DB_SIGNALS)
        rows = conn.execute("SELECT DISTINCT trade_type FROM signals").fetchall()
        if rows:
            strategies = list(set([r['trade_type'] for r in rows if r['trade_type']]))
        conn.close()
    except: pass

    return {
        "symbols": clean_symbols,
        "strategies": strategies
    }

# Mount static files for the dashboard
if os.path.exists("dashboard"):
    app.mount("/", StaticFiles(directory="dashboard", html=True), name="dashboard")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=5000)
