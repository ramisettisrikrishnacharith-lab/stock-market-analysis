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
