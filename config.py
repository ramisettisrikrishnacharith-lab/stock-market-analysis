"""Central configuration for the Stock Market Analysis System.

All values can be supplied through environment variables. For local
development, copy ``.env.example`` to ``.env`` and fill in your own values.
Never commit the real ``.env`` file.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")


def _env(name: str, default: str = "") -> str:
    value = os.getenv(name)
    return value.strip() if value is not None else default


def _int_env(name: str, default: int) -> int:
    try:
        return int(_env(name, str(default)))
    except ValueError:
        return default


def _bool_env(name: str, default: bool = False) -> bool:
    value = _env(name, "1" if default else "0").lower()
    return value in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    """Immutable application settings."""

    db_host: str = "localhost"
    db_port: int = 3306
    db_user: str = "root"
    db_password: str = ""
    db_name: str = "stock_market_db"
    db_ssl_ca: str = ""

    # Optional administrator credentials used only to CREATE DATABASE.
    # They fall back to the normal application credentials.
    db_admin_user: str = ""
    db_admin_password: str = ""

    flask_secret_key: str = "dev-only-secret-change-me"
    flask_debug: bool = False
    flask_host: str = "127.0.0.1"
    flask_port: int = 5000

    max_range_days: int = 3650          # ~10 years
    max_page_size: int = 500
    default_page_size: int = 50
    fetch_timeout_seconds: int = 25
    exports_dir: Path = BASE_DIR / "exports"
    sample_data_file: Path = BASE_DIR / "data" / "sample_stock_data.csv"
    twelve_data_api_key: str = ""

    @property
    def admin_user(self) -> str:
        return self.db_admin_user or self.db_user

    @property
    def admin_password(self) -> str:
        return self.db_admin_password or self.db_password

    @property
    def has_twelve_data_key(self) -> bool:
        return bool(self.twelve_data_api_key and self.twelve_data_api_key.strip() and self.twelve_data_api_key.strip() != "YOUR_API_KEY_HERE")


def load_settings(**overrides) -> Settings:
    """Build Settings from environment variables plus optional overrides."""
    load_dotenv(BASE_DIR / ".env", override=True)
    values = {
        "db_host": _env("DB_HOST", "localhost"),
        "db_port": _int_env("DB_PORT", 3306),
        "db_user": _env("DB_USER", "root"),
        "db_password": os.getenv("DB_PASSWORD", ""),
        "db_name": _env("DB_NAME", "stock_market_db"),
        "db_ssl_ca": _env("DB_SSL_CA", ""),
        "db_admin_user": _env("DB_ADMIN_USER", ""),
        "db_admin_password": os.getenv("DB_ADMIN_PASSWORD", ""),
        "flask_secret_key": _env("FLASK_SECRET_KEY", "dev-only-secret-change-me"),
        "flask_debug": _bool_env("FLASK_DEBUG", False),
        "flask_host": _env("FLASK_HOST", "127.0.0.1"),
        "flask_port": _int_env("FLASK_PORT", 5000),
        "fetch_timeout_seconds": _int_env("FETCH_TIMEOUT_SECONDS", 25),
        "twelve_data_api_key": _env("TWELVE_DATA_API_KEY", ""),
    }
    values.update({k: v for k, v in overrides.items() if v is not None})
    return Settings(**values)
