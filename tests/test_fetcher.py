"""Unit tests for data_fetcher helpers that do not require network or MySQL."""

from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
import pytest

import data_fetcher


def raw_frame(today: date) -> pd.DataFrame:
    """Build a yfinance-shaped frame containing yesterday and today."""
    index = pd.DatetimeIndex([today - timedelta(days=1), today], name="Date")
    return pd.DataFrame(
        {
            "Open": [100.0, 200.0],
            "High": [101.0, 201.0],
            "Low": [99.0, 199.0],
            "Close": [100.5, 200.5],
            "Volume": [1000, 2000],
        },
        index=index,
    )


def test_clean_yfinance_excludes_current_incomplete_day():
    today = date.today()
    frame = data_fetcher._clean_yfinance(raw_frame(today), today - timedelta(days=7), today, "TEST")
    assert len(frame) == 1
    assert frame.index[0].date() == today - timedelta(days=1)
    assert "data_source" in frame.columns
    assert frame["data_source"].iloc[0] == "yfinance"


def test_clean_yfinance_rejects_a_today_only_range():
    today = date.today()
    with pytest.raises(data_fetcher.MarketDataError) as excinfo:
        data_fetcher._clean_yfinance(raw_frame(today), today, today, "TEST")
    assert excinfo.value.code == "no_data_in_range"


def test_coverage_tolerates_weekend_shift_at_range_start():
    today = date.today()
    # Requested start is a Sunday; the first stored trading day is Monday.
    weekend_start = date(2026, 10, 25)
    monday = weekend_start + timedelta(days=1)
    bounds = {"first_date": monday.isoformat(), "last_date": (monday + timedelta(days=100)).isoformat()}
    assert data_fetcher._has_coverage(bounds, weekend_start, monday + timedelta(days=100))
    # A genuinely missing start (more than five days later) must refetch.
    late = {"first_date": (weekend_start + timedelta(days=10)).isoformat(),
            "last_date": (weekend_start + timedelta(days=200)).isoformat()}
    assert not data_fetcher._has_coverage(late, weekend_start, weekend_start + timedelta(days=200))
    assert not data_fetcher._has_coverage(None, weekend_start, today)


def test_twelve_data_missing_or_placeholder_key():
    today = date.today()
    start = today - timedelta(days=30)
    with pytest.raises(data_fetcher.MarketDataError) as exc_missing:
        data_fetcher._download_twelve_data("AAPL", start, today, "", 5)
    assert exc_missing.value.code == "missing_api_key"

    with pytest.raises(data_fetcher.MarketDataError) as exc_placeholder:
        data_fetcher._download_twelve_data("AAPL", start, today, "YOUR_API_KEY_HERE", 5)
    assert exc_placeholder.value.code == "missing_api_key"


def test_ensure_history_prioritizes_stored_coverage(monkeypatch):
    """ensure_history must return existing stored data even when Twelve Data API key is configured."""
    from unittest.mock import MagicMock
    from config import Settings

    settings = Settings(twelve_data_api_key="mock-key-123")
    assert settings.has_twelve_data_key is True

    fake_stock = {"stock_id": 1, "symbol": "AAPL", "company_name": "Apple Inc.", "exchange": "NASDAQ"}
    monkeypatch.setattr("database.get_stock_by_symbol", lambda symbol, cfg: fake_stock)
    monkeypatch.setattr(
        "database.get_price_bounds",
        lambda stock_id, cfg: {"first_date": "2024-01-01", "last_date": "2025-01-01"},
    )

    mock_stored = data_fetcher.HistoryResult(
        symbol="AAPL",
        frame=pd.DataFrame({"close_price": [150.0]}, index=pd.DatetimeIndex(["2024-06-01"])),
        source="yfinance",
        is_sample=False,
    )
    monkeypatch.setattr("data_fetcher._stored_result", lambda stock, start, end, **kwargs: mock_stored)

    # _download_twelve_data should NOT be called if coverage exists and refresh=False
    mock_twelve = MagicMock()
    monkeypatch.setattr("data_fetcher._download_twelve_data", mock_twelve)

    res = data_fetcher.ensure_history(
        "AAPL",
        date(2024, 1, 1),
        date(2025, 1, 1),
        refresh=False,
        settings=settings,
    )
    assert res == mock_stored
    mock_twelve.assert_not_called()
