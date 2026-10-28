"""Unit tests for the Pandas/NumPy analysis engine (no database required)."""

from __future__ import annotations

import json
import math
from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest

import analysis


def make_rows(closes, start=date(2025, 1, 1), volume_start=1000, source="yfinance"):
    rows = []
    for index, close in enumerate(closes):
        rows.append({
            "trade_date": start + timedelta(days=index),
            "open_price": close - 0.5,
            "high_price": close + 1.0,
            "low_price": close - 1.0,
            "close_price": close,
            "volume": volume_start + index * 10,
            "data_source": source,
        })
    return rows


def test_daily_returns_known_values_and_first_row():
    returns = analysis.calculate_daily_returns(pd.Series([100.0, 110.0, 99.0]))
    assert math.isnan(returns.iloc[0])
    assert returns.iloc[1] == pytest.approx(10.0)
    assert returns.iloc[2] == pytest.approx(-10.0)


def test_daily_returns_zero_and_missing_previous_close():
    zero_based = analysis.calculate_daily_returns(pd.Series([0.0, 10.0, 11.0]))
    assert math.isnan(zero_based.iloc[0])
    assert math.isnan(zero_based.iloc[1])
    assert zero_based.iloc[2] == pytest.approx(10.0)

    with_gap = analysis.calculate_daily_returns(pd.Series([100.0, np.nan, 110.0]))
    assert with_gap.isna().all()


def test_moving_average_window_and_insufficient_data():
    closes = pd.Series(range(1, 61), dtype=float)
    sma20 = analysis.simple_moving_average(closes, 20)
    sma50 = analysis.simple_moving_average(closes, 50)
    assert sma20.iloc[:19].isna().all()
    assert sma20.iloc[19] == pytest.approx(10.5)
    assert sma20.iloc[-1] == pytest.approx(50.5)
    assert sma50.iloc[:49].isna().all()
    assert sma50.iloc[-1] == pytest.approx(35.5)

    short = analysis.simple_moving_average(pd.Series([1.0, 2.0, 3.0]), 20)
    assert short.isna().all()


def test_volatility_uses_sample_standard_deviation():
    returns = pd.Series([10.0, -10.0])
    assert analysis.calculate_volatility(returns) == pytest.approx(14.1421, abs=1e-4)
    # ddof=1 (sample), not ddof=0 (population)
    assert analysis.calculate_volatility(returns) != pytest.approx(10.0)
    assert analysis.calculate_volatility(pd.Series([5.0])) is None
    assert analysis.calculate_volatility(pd.Series([], dtype=float)) is None


def test_basic_statistics_and_latest_change():
    result = analysis.calculate_analysis(make_rows([100, 110, 99, 121, 120, 132]))
    stats = result["stats"]

    assert stats["observations"] == 6
    assert stats["average_close"] == pytest.approx(113.6667, abs=1e-4)
    assert stats["highest_close"] == 132
    assert stats["lowest_close"] == 99
    assert stats["highest_high"] == 133
    assert stats["lowest_low"] == 98
    assert stats["average_volume"] == pytest.approx(1025.0)

    latest = result["latest"]
    assert latest["close"] == 132
    assert latest["previous_close"] == 120
    assert latest["change"] == 12
    assert latest["change_percent"] == pytest.approx(10.0)

    assert result["total_return_percent"] == pytest.approx(32.0)
    assert result["moving_averages"]["sma20"] is None
    assert result["moving_averages"]["sma50"] is None
    assert result["is_sample"] is False


def test_analysis_json_serialization_and_empty_data():
    result = analysis.calculate_analysis(make_rows([100, 101, 102]))
    encoded = json.dumps(result)
    assert '"stats"' in encoded
    assert isinstance(result["stats"]["average_close"], float)

    empty = analysis.calculate_analysis([])
    assert empty["stats"]["observations"] == 0
    assert empty["latest"]["close"] is None
    assert empty["daily_returns"]["volatility_percent"] is None
    assert empty["series"]["dates"] == []
    json.dumps(empty)


def test_to_json_safe_handles_numpy_and_non_finite_values():
    assert analysis.to_json_safe(np.int64(7)) == 7
    assert analysis.to_json_safe(np.float64(2.5)) == 2.5
    assert analysis.to_json_safe(np.nan) is None
    assert analysis.to_json_safe(np.inf) is None
    assert analysis.to_json_safe({"a": [np.float32(1.5), np.nan]}) == {"a": [1.5, None]}


def test_source_labelling_sample_and_mixed():
    sample = analysis.calculate_analysis(make_rows([100, 101, 102], source="sample"))
    assert sample["data_source"] == "sample"
    assert sample["is_sample"] is True

    mixed_rows = make_rows([100, 101, 102])
    mixed_rows[0]["data_source"] = "sample"
    mixed = analysis.calculate_analysis(mixed_rows)
    assert mixed["data_source"] == "mixed"
    assert mixed["is_sample"] is True


def test_comparison_normalisation_common_dates_and_stats():
    start = date(2025, 1, 1)
    rows_a = make_rows([100, 110, 120, 115, 130], start=start)
    rows_b = make_rows([50, 55, 52, 60, 62], start=start + timedelta(days=1))
    frames = {
        "A": analysis.prepare_frame(rows_a),
        "B": analysis.prepare_frame(rows_b),
    }
    result = analysis.compare_stocks(frames)

    assert result["symbols"] == ["A", "B"]
    assert len(result["dates"]) == 6
    assert result["methodology"]["common_dates"] == 4
    assert result["stats"]["A"]["total_return_percent"] == pytest.approx(18.1818, abs=1e-3)
    assert result["stats"]["B"]["total_return_percent"] == pytest.approx(20.0)

    a_series = result["series"]["A"]["normalized"]
    b_series = result["series"]["B"]["normalized"]
    assert a_series[0] == 100
    assert a_series[1] == pytest.approx(110.0)
    assert b_series[0] is None
    assert b_series[1] == 100


def test_comparison_requires_two_stocks_with_data():
    frame = analysis.prepare_frame(make_rows([100, 101, 102]))
    with pytest.raises(ValueError):
        analysis.compare_stocks({"A": frame})
    with pytest.raises(ValueError):
        analysis.compare_stocks({"A": frame, "B": pd.DataFrame()})
