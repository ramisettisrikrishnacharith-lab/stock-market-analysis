"""Shared pytest fixtures.

The database fixtures use a dedicated database named stock_market_db_test.
They never touch the real stock_market_db database.
"""

from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import database  # noqa: E402
import init_db  # noqa: E402
from config import load_settings  # noqa: E402

TEST_DB_NAME = "stock_market_db_test"


@pytest.fixture(scope="session")
def mysql_settings():
    """Create the isolated test database, or skip database tests if MySQL is unavailable."""
    if not TEST_DB_NAME.endswith("_test"):
        raise RuntimeError("Refusing to run tests against a non-test database.")
    settings = load_settings(db_name=TEST_DB_NAME)
    assert settings.db_name != load_settings().db_name
    try:
        database.create_database(settings)
        database.configure(settings)
        init_db.apply_schema(settings)
    except database.DatabaseError as exc:
        pytest.skip(f"MySQL test database is not available: {exc}")
    return settings


@pytest.fixture()
def db(mysql_settings):
    """Provide the configured test database with all tables emptied first."""
    database.configure(mysql_settings)
    for table in ("watchlist", "stock_prices", "stocks"):
        database.execute(f"DELETE FROM {table}", settings=mysql_settings)
    return mysql_settings


def _price_rows(start_value: float, step: float, start: date, end: date):
    rows = []
    day = start
    index = 0
    while day <= end:
        if day.weekday() < 5:
            close = round(start_value + step * index, 4)
            rows.append((day, round(close - 1, 4), round(close + 2, 4),
                         round(close - 2, 4), close, 1_000_000 + index * 2_500))
            index += 1
        day += timedelta(days=1)
    return rows


@pytest.fixture()
def seeded_client(db):
    """Flask test client backed by two stocks and stored historical rows."""
    import app as app_module

    start = date(2025, 1, 1)
    end = date(2025, 6, 30)
    stock_a = database.get_or_create_stock("TSTA", "Test Alpha Corp", "TEST", db)
    stock_b = database.get_or_create_stock("TSTB", "Test Beta Corp", "TEST", db)
    database.upsert_prices(stock_a["stock_id"], _price_rows(100, 0.4, start, end), "yfinance", db)
    database.upsert_prices(stock_b["stock_id"], _price_rows(200, -0.3, start, end), "yfinance", db)

    application = app_module.create_app(db)
    application.config.update(TESTING=True)
    with application.test_client() as client:
        yield client, stock_a, stock_b
