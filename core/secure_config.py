import base64
import hashlib
import os
from typing import Optional

from cryptography.fernet import Fernet, InvalidToken


SECRET_KEYS = {"mt5_login", "mt5_password", "mt5_server"}
REDACTED = "********"


def _fernet() -> Optional[Fernet]:
    raw_key = os.getenv("CONFIG_ENCRYPTION_KEY") or os.getenv("JWT_SECRET")
    if not raw_key:
        return None
    digest = hashlib.sha256(raw_key.encode()).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encryption_available() -> bool:
    return _fernet() is not None


def protect_config_value(key: str, value: str) -> str:
    if key not in SECRET_KEYS or value is None:
        return value
    fernet = _fernet()
    if not fernet:
        return value
    if str(value).startswith("enc:"):
        return value
    return "enc:" + fernet.encrypt(str(value).encode()).decode()


def reveal_config_value(key: str, value: Optional[str]) -> Optional[str]:
    if value is None or key not in SECRET_KEYS:
        return value
    raw = str(value)
    if not raw.startswith("enc:"):
        return raw
    fernet = _fernet()
    if not fernet:
        return None
    try:
        return fernet.decrypt(raw[4:].encode()).decode()
    except InvalidToken:
        return None


def redact_config_value(key: str, value: Optional[str]) -> Optional[str]:
    if key in SECRET_KEYS and value:
        return REDACTED
    return value
