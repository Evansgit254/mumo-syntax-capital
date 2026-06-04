import json
import os
import sqlite3
from pathlib import Path
from threading import RLock
from typing import Any, Optional, get_args, get_origin

from dotenv import load_dotenv
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from core.secure_config import reveal_config_value, redact_config_value


load_dotenv()

BASE_DIR = Path(__file__).resolve().parents[1]


class AppConfig(BaseModel):
    model_config = ConfigDict(validate_assignment=True)

    symbols: list[str] = Field(default_factory=lambda: [
        "EURUSD=X", "GBPUSD=X", "NZDUSD=X", "USDJPY=X", "AUDUSD=X",
        "GBPJPY=X", "GC=F", "CL=F", "BTC-USD",
    ])
    dxy_symbol: str = "DX-Y.NYB"
    tnx_symbol: str = "^TNX"
    narrative_tf: str = "1h"
    institutional_tf: str = "4h"
    structure_tf: str = "15m"
    entry_tf: str = "5m"

    rsi_buy_low: int = 25
    rsi_buy_high: int = 40
    rsi_sell_low: int = 60
    rsi_sell_high: int = 75
    ema_fast: int = 20
    ema_slow: int = 50
    ema_trend: int = 200
    rsi_period: int = 14
    atr_period: int = 14
    atr_avg_period: int = 5
    adr_period: int = 14

    telegram_bot_token: Optional[str] = None
    telegram_chat_id: Optional[str] = None
    telegram_extra_chat_ids: list[str] = Field(default_factory=list)
    gemini_api_key: Optional[str] = None

    mt5_login: int = 0
    mt5_password: str = ""
    mt5_server: str = ""
    metaapi_token: str = ""
    metaapi_account_id: str = ""
    mt5_auto_trade: bool = False
    mt5_paper_mode: bool = True
    mt5_use_direct: bool = False # Flag for native Windows MT5 library (v5.3.3)
    mt5_symbol_suffix: str = ""
    live_trading_approved: bool = False
    require_broker_data_for_live: bool = True
    max_pretrade_spread_pips: float = 3.0

    london_open: int = 8
    london_close: int = 16
    ny_open: int = 13
    ny_close: int = 21
    asian_range_min_pips: int = 15

    news_wash_zone: int = 30
    news_impact_levels: list[str] = Field(default_factory=lambda: ["High", "Medium"])
    multi_client_mode: bool = True
    min_confidence_score: float = 8.0
    gold_confidence_threshold: float = 5.5

    account_balance: float = 200.0
    risk_per_trade_percent: float = 2.0
    max_concurrent_trades: int = 4
    max_currency_exposure: int = 2
    max_correlated_exposure: int = 2
    max_strategy_exposure: int = 3
    max_session_exposure: int = 4
    min_lot_size: float = 0.01
    use_kelly_sizing: bool = False
    min_quality_score: float = 7.0
    min_quality_score_intraday: float = 5.0
    atr_multiplier: float = 2.0

    spread_pips: float = 0.8
    slippage_pips: float = 0.2

    db_clients: str = str(BASE_DIR / "database/clients.db")
    db_signals: str = str(BASE_DIR / "database/signals.db")
    data_provider: str = "yfinance"
    system_status: str = "ACTIVE"

    active_strategies: list[str] = Field(default_factory=lambda: ["crt", "advanced_pattern"])


DB_KEY_ALIASES = {
    "risk_per_trade": "risk_per_trade_percent",
    "news_filter_minutes": "news_wash_zone",
}


class ConfigManager:
    """Central config authority: SQLite overrides > environment > defaults."""

    _instance: Optional["ConfigManager"] = None
    _instance_lock = RLock()

    def __new__(cls):
        with cls._instance_lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._initialized = False
            return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._lock = RLock()
        self._runtime_overrides: dict[str, Any] = {}
        self._defaults = AppConfig()
        self._config = self._load_config()
        self._initialized = True

    def refresh(self) -> AppConfig:
        with self._lock:
            self._config = self._load_config()
            return self._config

    def snapshot(self) -> AppConfig:
        with self._lock:
            return self._config.model_copy(deep=True)

    def set_runtime_override(self, key: str, value: Any) -> AppConfig:
        with self._lock:
            self._runtime_overrides[self._normalize_key(key)] = value
            self._config = self._load_config()
            return self._config

    def clear_runtime_overrides(self) -> AppConfig:
        with self._lock:
            self._runtime_overrides.clear()
            self._config = self._load_config()
            return self._config

    def get(self, key: str, default: Any = None, refresh: bool = False) -> Any:
        if refresh:
            self.refresh()
        field = self._normalize_key(key)
        with self._lock:
            if hasattr(self._config, field):
                return getattr(self._config, field)
        return self._get_unknown_value(key, default)

    def get_redacted(self, key: str, default: Any = None) -> Any:
        value = self.get(key, default)
        return redact_config_value(self._normalize_key(key), value)

    def as_public_dict(self, include_unknown_db: bool = True) -> dict[str, Any]:
        config = self.refresh().model_dump()
        if include_unknown_db:
            for key, value in self._read_db_values().items():
                field = self._normalize_key(key)
                if field not in config:
                    config[key] = value
        return {key: redact_config_value(key, value) for key, value in config.items()}

    def _load_config(self) -> AppConfig:
        values = self._defaults.model_dump()
        env_values = self._env_values()
        for source in (env_values, self._runtime_overrides):
            for key, raw_value in source.items():
                field = self._normalize_key(key)
                if field not in AppConfig.model_fields:
                    continue
                parsed = self._coerce_field(field, raw_value)
                if parsed is not _INVALID:
                    values[field] = parsed
        db_values = self._read_db_values(db_path=values["db_clients"])

        for source in (db_values, self._runtime_overrides):
            for key, raw_value in source.items():
                field = self._normalize_key(key)
                if field not in AppConfig.model_fields:
                    continue
                parsed = self._coerce_field(field, raw_value)
                if parsed is not _INVALID:
                    values[field] = parsed

        try:
            return AppConfig.model_validate(values)
        except ValidationError:
            return self._defaults.model_copy(update=values)

    def _env_values(self) -> dict[str, Any]:
        values: dict[str, Any] = {}
        for field in AppConfig.model_fields:
            env_key = field.upper()
            if env_key in os.environ:
                values[field] = os.environ[env_key]
        if "DATA_MODE" in os.environ and "data_provider" not in values:
            mode = os.environ["DATA_MODE"].lower()
            values["data_provider"] = "mt5" if mode in {"mt5", "mt5_bridge"} else "yfinance"
        return values

    def _read_db_values(self, db_path: Optional[str] = None) -> dict[str, Any]:
        if db_path:
            path = db_path
        elif hasattr(self, "_config"):
            path = self._config.db_clients
        else:
            path = self._defaults.db_clients
        values: dict[str, Any] = {}
        try:
            conn = sqlite3.connect(path)
            conn.row_factory = sqlite3.Row
            rows = conn.execute("SELECT key, value, type FROM system_config").fetchall()
            conn.close()
        except Exception:
            return values

        for row in rows:
            key = row["key"]
            field = self._normalize_key(key)
            value = reveal_config_value(field, row["value"])
            if value is None:
                continue
            values[key] = value
        return values

    def _get_unknown_value(self, key: str, default: Any = None) -> Any:
        values = self._read_db_values()
        if key in values:
            return values[key]
        env_key = self._normalize_key(key).upper()
        return os.getenv(env_key, default)

    def _normalize_key(self, key: str) -> str:
        normalized = key.strip().lower()
        return DB_KEY_ALIASES.get(normalized, normalized)

    def _coerce_field(self, field: str, value: Any) -> Any:
        annotation = AppConfig.model_fields[field].annotation
        try:
            return self._coerce_value(annotation, value)
        except Exception:
            return _INVALID

    def _coerce_value(self, annotation: Any, value: Any) -> Any:
        origin = get_origin(annotation)
        args = get_args(annotation)
        if origin is Optional:
            annotation = args[0]
        elif origin is list:
            if isinstance(value, list):
                return value
            raw = str(value).strip()
            if not raw:
                return []
            if raw.startswith("["):
                loaded = json.loads(raw)
                if not isinstance(loaded, list):
                    raise ValueError("expected list")
                return loaded
            return [item.strip() for item in raw.split(",") if item.strip()]
        elif origin is not None and type(None) in args:
            non_none = [arg for arg in args if arg is not type(None)]
            annotation = non_none[0] if non_none else str

        if annotation is bool:
            if isinstance(value, bool):
                return value
            raw = str(value).strip().lower()
            if raw in {"1", "true", "yes", "on"}:
                return True
            if raw in {"0", "false", "no", "off"}:
                return False
            raise ValueError("expected bool")
        if annotation is int:
            return int(str(value).strip())
        if annotation is float:
            return float(str(value).strip())
        if annotation is str:
            return "" if value is None else str(value)
        return value


class _Invalid:
    pass


_INVALID = _Invalid()
config_manager = ConfigManager()
