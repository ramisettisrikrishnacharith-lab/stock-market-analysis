"""Database integration tests against the isolated test database."""

from __future__ import annotations

from datetime import date

import pytest

from unittest.mock import patch

import database
from config import Settings, load_settings


def test_connection_and_schema(db):
    row = database.fetch_one("SELECT 1 AS ok", settings=db)
    assert row["ok"] == 1
    for table in ("stocks", "stock_prices", "watchlist"):
        assert database.table_exists(table, db)


def test_stock_insert_lookup_and_duplicate_handling(db):
    stock = database.get_or_create_stock("DBTST", "Database Test Corp", "TEST", db)
    assert stock["stock_id"] > 0
    assert stock["symbol"] == "DBTST"

    duplicate = database.get_or_create_stock("DBTST", "Different Name", "TEST", db)
    assert duplicate["stock_id"] == stock["stock_id"]
    assert duplicate["company_name"] == "Database Test Corp"
    assert database.count_stocks(db) == 1

    found = database.get_stock_by_symbol("dbtst", db)
    assert found["stock_id"] == stock["stock_id"]
    assert database.get_stock_by_id(stock["stock_id"], db)["symbol"] == "DBTST"
    assert len(database.search_stocks("Database", 10, db)) == 1
    assert database.get_stock_by_symbol("MISSING", db) is None


def test_price_insert_update_and_duplicate_prevention(db):
    stock = database.get_or_create_stock("DBTST", "Database Test Corp", "TEST", db)
    rows = [
        (date(2025, 1, 2), 100.0, 102.0, 99.0, 101.0, 1000),
        (date(2025, 1, 3), 101.0, 104.0, 100.0, 103.0, 1100),
        (date(2025, 1, 6), 103.0, 105.0, 102.0, 104.0, 1200),
    ]
    database.upsert_prices(stock["stock_id"], rows, "yfinance", db)

    stored = database.get_prices(stock["stock_id"], "2025-01-01", "2025-01-31", db)
    assert len(stored) == 3
    assert stored[0]["close_price"] == 101.0
    assert stored[0]["data_source"] == "yfinance"

    # Upserting the same date must update, not duplicate.
    database.upsert_prices(
        stock["stock_id"],
        [(date(2025, 1, 2), 100.0, 106.0, 99.0, 105.5, 2000)],
        "yfinance",
        db,
    )
    stored = database.get_prices(stock["stock_id"], "2025-01-01", "2025-01-31", db)
    assert len(stored) == 3
    assert stored[0]["close_price"] == 105.5
    assert stored[0]["volume"] == 2000

    page, total = database.get_price_page(stock["stock_id"], "2025-01-01", "2025-01-31", 2, 0, db)
    assert total == 3
    assert len(page) == 2

    bounds = database.get_price_bounds(stock["stock_id"], db)
    assert bounds["first_date"] == "2025-01-02"
    assert bounds["last_date"] == "2025-01-06"
    assert bounds["row_count"] == 3


def test_sample_rows_never_overwrite_market_data(db):
    stock = database.get_or_create_stock("DBTST", "Database Test Corp", "TEST", db)
    database.upsert_prices(
        stock["stock_id"],
        [(date(2025, 1, 2), 100.0, 102.0, 99.0, 101.0, 1000)],
        "yfinance",
        db,
    )
    database.upsert_prices(
        stock["stock_id"],
        [(date(2025, 1, 2), 999.0, 999.0, 999.0, 999.0, 1)],
        "sample",
        db,
    )
    stored = database.get_prices(stock["stock_id"], "2025-01-01", "2025-01-31", db)
    assert stored[0]["close_price"] == 101.0
    assert stored[0]["data_source"] == "yfinance"

    # A later retrieved row updates a sample row.
    database.upsert_prices(
        stock["stock_id"],
        [(date(2025, 1, 3), 101.0, 103.0, 100.0, 102.0, 1500)],
        "sample",
        db,
    )
    database.upsert_prices(
        stock["stock_id"],
        [(date(2025, 1, 3), 101.5, 104.0, 101.0, 103.5, 1800)],
        "yfinance",
        db,
    )
    stored = database.get_prices(stock["stock_id"], "2025-01-03", "2025-01-03", db)
    assert stored[0]["close_price"] == 103.5
    assert stored[0]["data_source"] == "yfinance"


def test_watchlist_add_duplicate_remove(db):
    stock = database.get_or_create_stock("DBTST", "Database Test Corp", "TEST", db)
    watchlist_id = database.add_to_watchlist(stock["stock_id"], db)
    assert watchlist_id > 0
    assert database.count_watchlist(db) == 1

    with pytest.raises(database.DuplicateWatchlistError):
        database.add_to_watchlist(stock["stock_id"], db)

    items = database.get_watchlist(db)
    assert len(items) == 1
    assert items[0]["symbol"] == "DBTST"
    assert items[0]["close_price"] is None

    assert database.remove_from_watchlist(stock["stock_id"], db) == 1
    assert database.count_watchlist(db) == 0
    assert database.remove_from_watchlist(stock["stock_id"], db) == 0


def test_foreign_key_rejects_unknown_stock(db):
    with pytest.raises(LookupError):
        database.add_to_watchlist(999999, db)


def test_ssl_connection_parameters():
    cfg = Settings(db_ssl_ca="/path/to/aiven-ca.pem")
    assert cfg.db_ssl_ca == "/path/to/aiven-ca.pem"

    with patch("mysql.connector.connect") as mock_connect:
        mock_connect.return_value = "mock_conn"
        conn = database.get_connection(cfg)
        assert conn == "mock_conn"
        mock_connect.assert_called_once()
        kwargs = mock_connect.call_args.kwargs
        assert kwargs["ssl_ca"] == "/path/to/aiven-ca.pem"
        assert kwargs["ssl_verify_cert"] is True
        assert kwargs["ssl_verify_identity"] is True


def test_no_ssl_connection_parameters_by_default():
    cfg = Settings(db_ssl_ca="")
    with patch("mysql.connector.connect") as mock_connect:
        mock_connect.return_value = "mock_conn"
        conn = database.get_connection(cfg)
        assert conn == "mock_conn"
        mock_connect.assert_called_once()
        kwargs = mock_connect.call_args.kwargs
        assert "ssl_ca" not in kwargs
        assert "ssl_verify_cert" not in kwargs
        assert "ssl_verify_identity" not in kwargs
