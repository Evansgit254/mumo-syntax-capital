import os
from dotenv import load_dotenv
from config.manager import config_manager

load_dotenv()
_settings = config_manager.snapshot()

# Trading Settings
SYMBOLS = _settings.symbols # Alpha Core Plus (V16.0)
DXY_SYMBOL = _settings.dxy_symbol
TNX_SYMBOL = _settings.tnx_symbol
NARRATIVE_TF = _settings.narrative_tf
INSTITUTIONAL_TF = _settings.institutional_tf
STRUCTURE_TF = _settings.structure_tf
ENTRY_TF = _settings.entry_tf # Switched to 5m for better intraday consistency
# RSI THRESHOLDS
RSI_BUY_LOW = _settings.rsi_buy_low
RSI_BUY_HIGH = _settings.rsi_buy_high
RSI_SELL_LOW = _settings.rsi_sell_low
RSI_SELL_HIGH = _settings.rsi_sell_high

# INDICATOR PERIODS (V31.1 Recovery)
EMA_FAST = _settings.ema_fast
EMA_SLOW = _settings.ema_slow
EMA_TREND = _settings.ema_trend
RSI_PERIOD = _settings.rsi_period
ATR_PERIOD = _settings.atr_period
ATR_AVG_PERIOD = _settings.atr_avg_period
ADR_PERIOD = _settings.adr_period

# TELEGRAM
TELEGRAM_BOT_TOKEN = _settings.telegram_bot_token
TELEGRAM_CHAT_ID = _settings.telegram_chat_id
# Optional: comma-separated list of extra group Chat IDs to also broadcast signals to
# e.g. TELEGRAM_EXTRA_CHAT_IDS=-1001234567890,-1009876543210
TELEGRAM_EXTRA_CHAT_IDS = _settings.telegram_extra_chat_ids
GEMINI_API_KEY = _settings.gemini_api_key

# MT5 CREDENTIALS
MT5_LOGIN = _settings.mt5_login
MT5_PASSWORD = _settings.mt5_password
MT5_SERVER = _settings.mt5_server

# MT5 AUTO-TRADING via MetaAPI (Linux-compatible REST bridge)
# Sign up free at https://metaapi.cloud to get these values
METAAPI_TOKEN = _settings.metaapi_token
METAAPI_ACCOUNT_ID = _settings.metaapi_account_id
MT5_AUTO_TRADE = _settings.mt5_auto_trade
MT5_PAPER_MODE = _settings.mt5_paper_mode  # Default: paper mode for safety
MT5_USE_DIRECT = _settings.mt5_use_direct  # V5.3.3 Native Windows Library support
MT5_SYMBOL_SUFFIX = _settings.mt5_symbol_suffix  # e.g., "c" for HFM Cent accounts (EURUSDc)
LIVE_TRADING_APPROVED = _settings.live_trading_approved
REQUIRE_BROKER_DATA_FOR_LIVE = _settings.require_broker_data_for_live
MAX_PRETRADE_SPREAD_PIPS = _settings.max_pretrade_spread_pips

# SESSION TIMES (UTC)
# London: 08:00 - 16:00
# NY: 13:00 - 21:00
LONDON_OPEN = _settings.london_open
LONDON_CLOSE = _settings.london_close
NY_OPEN = _settings.ny_open
NY_CLOSE = _settings.ny_close
ASIAN_RANGE_MIN_PIPS = _settings.asian_range_min_pips # Minimum range for sweep validity (Reserved for filtering)

# NEWS FILTER
NEWS_WASH_ZONE = _settings.news_wash_zone # Minutes before/after high-impact news
NEWS_IMPACT_LEVELS = _settings.news_impact_levels # Impact levels to track

# MULTI-CLIENT SETTINGS (V11.0)
MULTI_CLIENT_MODE = _settings.multi_client_mode

# SCORING (V15.0 Golden Threshold)
MIN_CONFIDENCE_SCORE = _settings.min_confidence_score
GOLD_CONFIDENCE_THRESHOLD = _settings.gold_confidence_threshold  # V15.5 Extreme Volume (Alpha Core)

# RISK MANAGEMENT V4.0 (Scalable Account Sizing)
ACCOUNT_BALANCE = _settings.account_balance  # Configurable via env (V10.1: Increased for Gold trading)
RISK_PER_TRADE_PERCENT = _settings.risk_per_trade_percent  # Standard 2% risk
MAX_CONCURRENT_TRADES = _settings.max_concurrent_trades  # Increased from 2
MAX_CURRENCY_EXPOSURE = _settings.max_currency_exposure  # Increased from 1
MAX_CORRELATED_EXPOSURE = _settings.max_correlated_exposure
MAX_STRATEGY_EXPOSURE = _settings.max_strategy_exposure
MAX_SESSION_EXPOSURE = _settings.max_session_exposure
MIN_LOT_SIZE = _settings.min_lot_size
USE_KELLY_SIZING = _settings.use_kelly_sizing  # Dynamic sizing
MIN_QUALITY_SCORE = _settings.min_quality_score
MIN_QUALITY_SCORE_INTRADAY = _settings.min_quality_score_intraday
ATR_MULTIPLIER = _settings.atr_multiplier

# EXECUTION REALISM (V18.1 Audit)
SPREAD_PIPS = _settings.spread_pips # Average Retail Spread
SLIPPAGE_PIPS = _settings.slippage_pips # Expected Execution Slippage

# DATABASE PATHS (V22.7.5)
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_CLIENTS = _settings.db_clients
DB_SIGNALS = _settings.db_signals
# V35.1r: PER-SYMBOL ALPHA WEIGHTS — expanded to 4-cluster regime model
# Old "TRENDING" key never matched TRENDING_BULL/TRENDING_BEAR, causing silent fallback.
SYMBOL_ALPHA_WEIGHTS = {
    "EURUSD=X": {
        "TRENDING_BULL":  {"velocity": 0.1, "zscore": 0.1, "momentum": 0.7, "volatility": 0.1},
        "TRENDING_BEAR":  {"velocity": 0.1, "zscore": 0.1, "momentum": 0.7, "volatility": 0.1},
        "VOLATILE_RANGE": {"velocity": 0.3, "zscore": 0.5, "momentum": 0.1, "volatility": 0.1},
        "LOW_VOL_RANGE":  {"velocity": 0.4, "zscore": 0.5, "momentum": 0.05, "volatility": 0.05},
    },
    "GBPUSD=X": {
        "TRENDING_BULL":  {"velocity": 0.2, "zscore": 0.5, "momentum": 0.2, "volatility": 0.1},
        "TRENDING_BEAR":  {"velocity": 0.2, "zscore": 0.5, "momentum": 0.2, "volatility": 0.1},
        "VOLATILE_RANGE": {"velocity": 0.3, "zscore": 0.4, "momentum": 0.2, "volatility": 0.1},
        "LOW_VOL_RANGE":  {"velocity": 0.4, "zscore": 0.5, "momentum": 0.05, "volatility": 0.05},
    },
    "USDJPY=X": {
        "TRENDING_BULL":  {"velocity": 0.1, "zscore": 0.1, "momentum": 0.7, "volatility": 0.1},
        "TRENDING_BEAR":  {"velocity": 0.1, "zscore": 0.1, "momentum": 0.7, "volatility": 0.1},
        "VOLATILE_RANGE": {"velocity": 0.1, "zscore": 0.6, "momentum": 0.2, "volatility": 0.1},
        "LOW_VOL_RANGE":  {"velocity": 0.4, "zscore": 0.5, "momentum": 0.05, "volatility": 0.05},
    },
    "NZDUSD=X": {
        "TRENDING_BULL":  {"velocity": 0.3, "zscore": 0.3, "momentum": 0.3, "volatility": 0.1},
        "TRENDING_BEAR":  {"velocity": 0.3, "zscore": 0.3, "momentum": 0.3, "volatility": 0.1},
        "VOLATILE_RANGE": {"velocity": 0.4, "zscore": 0.2, "momentum": 0.3, "volatility": 0.1},
        "LOW_VOL_RANGE":  {"velocity": 0.5, "zscore": 0.3, "momentum": 0.1, "volatility": 0.1},
    },
    "AUDUSD=X": {
        "TRENDING_BULL":  {"velocity": 0.1, "zscore": 0.7, "momentum": 0.1, "volatility": 0.1},
        "TRENDING_BEAR":  {"velocity": 0.1, "zscore": 0.7, "momentum": 0.1, "volatility": 0.1},
        "VOLATILE_RANGE": {"velocity": 0.3, "zscore": 0.4, "momentum": 0.2, "volatility": 0.1},
        "LOW_VOL_RANGE":  {"velocity": 0.4, "zscore": 0.5, "momentum": 0.05, "volatility": 0.05},
    },
    "GBPJPY=X": {
        "TRENDING_BULL":  {"velocity": 0.1, "zscore": 0.1, "momentum": 0.7, "volatility": 0.1},
        "TRENDING_BEAR":  {"velocity": 0.1, "zscore": 0.1, "momentum": 0.7, "volatility": 0.1},
        "VOLATILE_RANGE": {"velocity": 0.2, "zscore": 0.3, "momentum": 0.4, "volatility": 0.1},
        "LOW_VOL_RANGE":  {"velocity": 0.4, "zscore": 0.5, "momentum": 0.05, "volatility": 0.05},
    },
    "GC=F": {
        "TRENDING_BULL":  {"velocity": 0.1, "zscore": 0.1, "momentum": 0.1, "volatility": 0.7},
        "TRENDING_BEAR":  {"velocity": 0.1, "zscore": 0.1, "momentum": 0.1, "volatility": 0.7},
        "VOLATILE_RANGE": {"velocity": 0.2, "zscore": 0.2, "momentum": 0.1, "volatility": 0.5},
        "LOW_VOL_RANGE":  {"velocity": 0.3, "zscore": 0.4, "momentum": 0.1, "volatility": 0.2},
    },
    "CL=F": {
        "TRENDING_BULL":  {"velocity": 0.1, "zscore": 0.1, "momentum": 0.7, "volatility": 0.1},
        "TRENDING_BEAR":  {"velocity": 0.1, "zscore": 0.1, "momentum": 0.7, "volatility": 0.1},
        "VOLATILE_RANGE": {"velocity": 0.3, "zscore": 0.3, "momentum": 0.3, "volatility": 0.1},
        "LOW_VOL_RANGE":  {"velocity": 0.4, "zscore": 0.5, "momentum": 0.05, "volatility": 0.05},
    },
    "BTC-USD": {
        "TRENDING_BULL":  {"velocity": 0.1, "zscore": 0.1, "momentum": 0.7, "volatility": 0.1},
        "TRENDING_BEAR":  {"velocity": 0.1, "zscore": 0.1, "momentum": 0.7, "volatility": 0.1},
        "VOLATILE_RANGE": {"velocity": 0.2, "zscore": 0.3, "momentum": 0.3, "volatility": 0.2},
        "LOW_VOL_RANGE":  {"velocity": 0.3, "zscore": 0.5, "momentum": 0.1, "volatility": 0.1},
    },
}
