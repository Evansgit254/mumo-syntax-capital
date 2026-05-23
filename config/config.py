import os
from dotenv import load_dotenv

load_dotenv()

# Trading Settings
SYMBOLS = ["EURUSD=X", "GBPUSD=X", "NZDUSD=X", "USDJPY=X", "AUDUSD=X", "GBPJPY=X", "GC=F", "CL=F", "BTC-USD"] # Alpha Core Plus (V16.0)
DXY_SYMBOL = "DX-Y.NYB"
TNX_SYMBOL = "^TNX"
NARRATIVE_TF = "1h"
INSTITUTIONAL_TF = "4h"
STRUCTURE_TF = "15m"
ENTRY_TF = "5m" # Switched to 5m for better intraday consistency
# RSI THRESHOLDS
RSI_BUY_LOW = 25
RSI_BUY_HIGH = 40
RSI_SELL_LOW = 60
RSI_SELL_HIGH = 75

# INDICATOR PERIODS (V31.1 Recovery)
EMA_FAST = 20
EMA_SLOW = 50
EMA_TREND = 200
RSI_PERIOD = 14
ATR_PERIOD = 14
ATR_AVG_PERIOD = 5
ADR_PERIOD = 14

# TELEGRAM
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
# Optional: comma-separated list of extra group Chat IDs to also broadcast signals to
# e.g. TELEGRAM_EXTRA_CHAT_IDS=-1001234567890,-1009876543210
_extra = os.getenv("TELEGRAM_EXTRA_CHAT_IDS", "")
TELEGRAM_EXTRA_CHAT_IDS = [cid.strip() for cid in _extra.split(",") if cid.strip()]
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# MT5 CREDENTIALS
MT5_LOGIN = os.getenv("MT5_LOGIN")
MT5_LOGIN = int(MT5_LOGIN) if MT5_LOGIN and MT5_LOGIN.strip() else 0
MT5_PASSWORD = os.getenv("MT5_PASSWORD", "")
MT5_SERVER = os.getenv("MT5_SERVER", "")

# MT5 AUTO-TRADING via MetaAPI (Linux-compatible REST bridge)
# Sign up free at https://metaapi.cloud to get these values
METAAPI_TOKEN = os.getenv("METAAPI_TOKEN", "")
METAAPI_ACCOUNT_ID = os.getenv("METAAPI_ACCOUNT_ID", "")
MT5_AUTO_TRADE = os.getenv("MT5_AUTO_TRADE", "false").lower() == "true"
MT5_PAPER_MODE = os.getenv("MT5_PAPER_MODE", "true").lower() == "true"  # Default: paper mode for safety
MT5_SYMBOL_SUFFIX = os.getenv("MT5_SYMBOL_SUFFIX", "")  # e.g., "c" for HFM Cent accounts (EURUSDc)

# SESSION TIMES (UTC)
# London: 08:00 - 16:00
# NY: 13:00 - 21:00
LONDON_OPEN = 8
LONDON_CLOSE = 16
NY_OPEN = 13
NY_CLOSE = 21
ASIAN_RANGE_MIN_PIPS = 15 # Minimum range for sweep validity (Reserved for filtering)

# NEWS FILTER
NEWS_WASH_ZONE = 30 # Minutes before/after high-impact news
NEWS_IMPACT_LEVELS = ["High", "Medium"] # Impact levels to track

# MULTI-CLIENT SETTINGS (V11.0)
MULTI_CLIENT_MODE = os.getenv("MULTI_CLIENT_MODE", "true").lower() == "true"

# SCORING (V15.0 Golden Threshold)
MIN_CONFIDENCE_SCORE = 8.0
GOLD_CONFIDENCE_THRESHOLD = 5.5  # V15.5 Extreme Volume (Alpha Core)

# RISK MANAGEMENT V4.0 (Scalable Account Sizing)
ACCOUNT_BALANCE = float(os.getenv("ACCOUNT_BALANCE", "200.0"))  # Configurable via env (V10.1: Increased for Gold trading)
RISK_PER_TRADE_PERCENT = float(os.getenv("RISK_PER_TRADE_PERCENT", "2.0"))  # Standard 2% risk
MAX_CONCURRENT_TRADES = int(os.getenv("MAX_CONCURRENT_TRADES", "4"))  # Increased from 2
MAX_CURRENCY_EXPOSURE = int(os.getenv("MAX_CURRENCY_EXPOSURE", "2"))  # Increased from 1
MIN_LOT_SIZE = 0.01
USE_KELLY_SIZING = os.getenv("USE_KELLY_SIZING", "false").lower() == "true"  # Dynamic sizing
MIN_QUALITY_SCORE = float(os.getenv("MIN_QUALITY_SCORE", "7.0"))
MIN_QUALITY_SCORE_INTRADAY = 5.0
ATR_MULTIPLIER = 2.0

# EXECUTION REALISM (V18.1 Audit)
SPREAD_PIPS = 0.8 # Average Retail Spread
SLIPPAGE_PIPS = 0.2 # Expected Execution Slippage

# DATABASE PATHS (V22.7.5)
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_CLIENTS = os.path.join(BASE_DIR, "database/clients.db")
DB_SIGNALS = os.path.join(BASE_DIR, "database/signals.db")
# V22.2 PER-SYMBOL ALPHA WEIGHTS (IC-Derived from 60-day analysis)
# Format: { symbol: { regime: { factor: weight } } }
SYMBOL_ALPHA_WEIGHTS = {
    "EURUSD=X": {"TRENDING": {"velocity": 0.1, "zscore": 0.1, "momentum": 0.7, "volatility": 0.1}},
    "GBPUSD=X": {"TRENDING": {"velocity": 0.2, "zscore": 0.5, "momentum": 0.2, "volatility": 0.1}},
    "USDJPY=X": {"TRENDING": {"velocity": 0.1, "zscore": 0.1, "momentum": 0.7, "volatility": 0.1}},
    "NZDUSD=X": {"TRENDING": {"velocity": 0.3, "zscore": 0.3, "momentum": 0.3, "volatility": 0.1}},
    "AUDUSD=X": {"TRENDING": {"velocity": 0.1, "zscore": 0.7, "momentum": 0.1, "volatility": 0.1}},
    "GBPJPY=X": {"TRENDING": {"velocity": 0.1, "zscore": 0.1, "momentum": 0.7, "volatility": 0.1}},
    "GC=F":     {"TRENDING": {"velocity": 0.1, "zscore": 0.1, "momentum": 0.1, "volatility": 0.7}},
    "CL=F":     {"TRENDING": {"velocity": 0.1, "zscore": 0.1, "momentum": 0.7, "volatility": 0.1}},
    "BTC-USD":  {"TRENDING": {"velocity": 0.1, "zscore": 0.1, "momentum": 0.7, "volatility": 0.1}},
}


