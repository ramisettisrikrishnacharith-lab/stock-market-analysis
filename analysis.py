"""Pandas/NumPy statistical analysis.

This module contains pure calculation functions. It performs no database
access and no HTTP work, which keeps the statistics easy to test.
"""

from __future__ import annotations

import math
from typing import Any, Iterable

import numpy as np
import pandas as pd

REQUIRED_COLUMNS = ["open_price", "high_price", "low_price", "close_price", "volume"]
VOLATILITY_METHOD = (
    "Sample standard deviation (ddof=1) of daily percentage returns; "
    "not annualized."
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def to_json_safe(value: Any) -> Any:
    """Recursively convert NumPy/Pandas types and non-finite floats to JSON-safe values."""
    if isinstance(value, dict):
        return {str(key): to_json_safe(val) for key, val in value.items()}
    if isinstance(value, (list, tuple, np.ndarray, pd.Series)):
        return [to_json_safe(item) for item in value]
    if isinstance(value, (pd.Timestamp,)):
        return value.strftime("%Y-%m-%d")
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        number = float(value)
        return None if not math.isfinite(number) else number
    if value is pd.NaT:
        return None
    if value is None or isinstance(value, (str, int, bool)):
        return value
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    return value


def prepare_frame(data: Iterable[dict] | pd.DataFrame) -> pd.DataFrame:
    """Validate and normalise price rows into a sorted DatetimeIndex frame.

    Expected input columns: trade_date, open_price, high_price, low_price,
    close_price, volume (and optionally data_source). Rows without a usable
    close price are discarded.
    """
    df = data.copy() if isinstance(data, pd.DataFrame) else pd.DataFrame(list(data))
    if "trade_date" not in df.columns and isinstance(df.index, pd.DatetimeIndex):
        df = df.reset_index()
    expected = ["trade_date"] + REQUIRED_COLUMNS
    if df.empty:
        return pd.DataFrame(columns=expected + ["data_source"]).set_index("trade_date")

    if "trade_date" not in df.columns:
        raise ValueError("Price data is missing the trade_date column.")
    for column in REQUIRED_COLUMNS:
        if column not in df.columns:
            raise ValueError(f"Price data is missing the {column} column.")

    df = df.copy()
    df["trade_date"] = pd.to_datetime(df["trade_date"], errors="coerce")
    for column in REQUIRED_COLUMNS:
        df[column] = pd.to_numeric(df[column], errors="coerce")
    if "data_source" not in df.columns:
        df["data_source"] = "unknown"

    df = df.dropna(subset=["trade_date", "close_price"])
    df = df[df["close_price"] > 0]
    df = df.sort_values("trade_date")
    df = df.drop_duplicates(subset=["trade_date"], keep="last")
    return df.set_index("trade_date")


def calculate_daily_returns(closes: pd.Series) -> pd.Series:
    """Percentage daily returns; the first row and invalid bases become NaN."""
    closes = pd.to_numeric(pd.Series(closes), errors="coerce").astype(float)
    if closes.empty:
        return pd.Series(dtype=float)
    returns = closes.pct_change(fill_method=None) * 100.0
    returns = returns.replace([np.inf, -np.inf], np.nan)
    return returns


def simple_moving_average(closes: pd.Series, window: int) -> pd.Series:
    """Simple moving average that stays NaN until ``window`` observations exist."""
    if window < 1:
        raise ValueError("window must be a positive integer")
    closes = pd.to_numeric(pd.Series(closes), errors="coerce").astype(float)
    return closes.rolling(window=window, min_periods=window).mean()


def calculate_volatility(returns: pd.Series) -> float | None:
    """Sample standard deviation (ddof=1) of daily returns, or None."""
    values = pd.to_numeric(pd.Series(returns), errors="coerce").dropna().to_numpy(dtype=float)
    if values.size < 2:
        return None
    return _round(np.std(values, ddof=1), 4)


def calculate_basic_statistics(frame: pd.DataFrame) -> dict:
    """Basic descriptive statistics from a prepared price frame."""
    if frame.empty:
        return {
            "average_close": None,
            "highest_close": None,
            "lowest_close": None,
            "highest_high": None,
            "lowest_low": None,
            "average_volume": None,
            "observations": 0,
            "first_date": None,
            "last_date": None,
        }

    def _mean(column: str) -> float | None:
        values = pd.to_numeric(frame[column], errors="coerce").dropna()
        return _round(values.mean(), 4) if not values.empty else None

    def _min(column: str) -> float | None:
        values = pd.to_numeric(frame[column], errors="coerce").dropna()
        return _round(values.min(), 4) if not values.empty else None

    def _max(column: str) -> float | None:
        values = pd.to_numeric(frame[column], errors="coerce").dropna()
        return _round(values.max(), 4) if not values.empty else None

    return {
        "average_close": _mean("close_price"),
        "highest_close": _max("close_price"),
        "lowest_close": _min("close_price"),
        "highest_high": _max("high_price"),
        "lowest_low": _min("low_price"),
        "average_volume": _mean("volume"),
        "observations": int(len(frame)),
        "first_date": frame.index.min().strftime("%Y-%m-%d"),
        "last_date": frame.index.max().strftime("%Y-%m-%d"),
    }


def _round(value: Any, digits: int = 4) -> float | None:
    if value is None:
        return None
    number = float(value)
    if not math.isfinite(number):
        return None
    return round(number, digits)


def _last_or_none(series: pd.Series) -> float | None:
    if series.empty:
        return None
    value = series.iloc[-1]
    return None if pd.isna(value) else _round(value, 4)


def _source_info(frame: pd.DataFrame) -> tuple[str, bool]:
    if frame.empty or "data_source" not in frame.columns:
        return "unknown", False
    sources = sorted({str(item) for item in frame["data_source"].dropna().unique()})
    if not sources:
        return "unknown", False
    label = sources[0] if len(sources) == 1 else "mixed"
    return label, "sample" in sources


# ---------------------------------------------------------------------------
# Public analysis API
# ---------------------------------------------------------------------------

def calculate_analysis(data: Iterable[dict] | pd.DataFrame) -> dict:
    """Return a complete JSON-safe analysis result for one stock."""
    frame = prepare_frame(data)
    stats = calculate_basic_statistics(frame)
    source, is_sample = _source_info(frame)

    if frame.empty:
        return {
            "stats": stats,
            "latest": {
                "trade_date": None,
                "close": None,
                "previous_close": None,
                "change": None,
                "change_percent": None,
            },
            "daily_returns": {
                "average_percent": None,
                "latest_percent": None,
                "volatility_percent": None,
                "method": VOLATILITY_METHOD,
            },
            "moving_averages": {
                "sma20": None,
                "sma50": None,
                "sma20_window": 20,
                "sma50_window": 50,
                "note": "Moving averages require at least 20 and 50 observations respectively.",
            },
            "total_return_percent": None,
            "data_source": source,
            "is_sample": is_sample,
            "series": {
                "dates": [],
                "close": [],
                "volume": [],
                "sma20": [],
                "sma50": [],
                "daily_returns": [],
            },
        }

    closes = frame["close_price"].astype(float)
    returns = calculate_daily_returns(closes)
    sma20 = simple_moving_average(closes, 20)
    sma50 = simple_moving_average(closes, 50)

    latest_row = frame.iloc[-1]
    previous_close = float(frame["close_price"].iloc[-2]) if len(frame) >= 2 else None
    latest_close = float(latest_row["close_price"])
    change = (latest_close - previous_close) if previous_close is not None else None
    change_percent = (
        (change / previous_close) * 100.0
        if change is not None and previous_close and previous_close > 0
        else None
    )

    first_close = float(closes.iloc[0])
    total_return = ((latest_close - first_close) / first_close) * 100.0 if first_close > 0 else None
    valid_returns = returns.dropna()
    average_daily_return = (
        _round(valid_returns.mean(), 4) if not valid_returns.empty else None
    )

    volume_series = pd.to_numeric(frame["volume"], errors="coerce")
    series = {
        "dates": [index.strftime("%Y-%m-%d") for index in frame.index],
        "close": [to_json_safe(value) for value in closes],
        "volume": [
            None if pd.isna(value) else int(value) for value in volume_series
        ],
        "sma20": [to_json_safe(value) for value in sma20],
        "sma50": [to_json_safe(value) for value in sma50],
        "daily_returns": [to_json_safe(value) for value in returns],
    }

    result = {
        "stats": stats,
        "latest": {
            "trade_date": latest_row.name.strftime("%Y-%m-%d"),
            "close": _round(latest_close, 4),
            "previous_close": _round(previous_close, 4),
            "change": _round(change, 4),
            "change_percent": _round(change_percent, 4),
        },
        "daily_returns": {
            "average_percent": average_daily_return,
            "latest_percent": _round(returns.iloc[-1], 4) if not returns.empty else None,
            "volatility_percent": calculate_volatility(returns),
            "method": VOLATILITY_METHOD,
        },
        "moving_averages": {
            "sma20": _last_or_none(sma20),
            "sma50": _last_or_none(sma50),
            "sma20_window": 20,
            "sma50_window": 50,
            "note": "A moving average is shown only after enough trading days exist.",
        },
        "total_return_percent": _round(total_return, 4),
        "data_source": source,
        "is_sample": is_sample,
        "series": series,
    }
    return to_json_safe(result)


# ---------------------------------------------------------------------------
# Comparison
# ---------------------------------------------------------------------------

def compare_stocks(frames: dict[str, pd.DataFrame]) -> dict:
    """Compare two or more prepared price frames on a common date range.

    Methodology:
    * The normalised chart forward-fills each stock's close to the union of
      trading dates and divides by that stock's first available close
      (start index = 100). Values before a stock's first date stay empty.
    * Return statistics use only dates on which *every* compared stock traded,
      so returns are not computed across stale forward-filled prices.
    * Volatility is the sample standard deviation of daily percentage returns
      on those common dates. It is not annualized.
    """
    valid: dict[str, pd.DataFrame] = {
        symbol: frame for symbol, frame in frames.items() if frame is not None and not frame.empty
    }
    if len(valid) < 2:
        raise ValueError("At least two stocks with historical data are required.")

    close_map = {symbol: frame["close_price"].astype(float) for symbol, frame in valid.items()}
    closes = pd.concat(close_map, axis=1).sort_index()
    closes.columns = list(close_map.keys())

    common_dates = closes.dropna(how="any").index
    warnings: list[str] = []
    if len(common_dates) < 2:
        warnings.append(
            "Fewer than two common trading dates were found; return statistics "
            "may be unavailable."
        )

    volume_map = {}
    for symbol, frame in valid.items():
        volume = pd.to_numeric(frame["volume"], errors="coerce")
        volume_map[symbol] = volume
    volumes = pd.concat(volume_map, axis=1).sort_index()
    volumes.columns = list(volume_map.keys())

    # Normalised values on the union of dates, forward-filled only after listing.
    filled = closes.ffill()
    bases = {}
    for symbol in filled.columns:
        series = filled[symbol].dropna()
        bases[symbol] = float(series.iloc[0]) if not series.empty else None
    normalized = pd.DataFrame(index=filled.index)
    for symbol in filled.columns:
        base = bases.get(symbol)
        normalized[symbol] = (filled[symbol] / base * 100.0) if base else np.nan

    stats: dict[str, dict] = {}
    for symbol in closes.columns:
        common_close = closes.loc[common_dates, symbol].dropna()
        if len(common_close) >= 1:
            start_price = float(common_close.iloc[0])
            end_price = float(common_close.iloc[-1])
            total_return = (
                ((end_price - start_price) / start_price) * 100.0
                if start_price > 0 else None
            )
        else:
            start_price = end_price = total_return = None

        if len(common_close) >= 2:
            returns = calculate_daily_returns(common_close)
            avg_daily = _round(returns.dropna().mean(), 4) if returns.notna().any() else None
            volatility = calculate_volatility(returns)
        else:
            avg_daily = volatility = None

        common_volume = volumes.loc[common_dates, symbol] if len(common_dates) else pd.Series(dtype=float)
        avg_volume = (
            _round(pd.to_numeric(common_volume, errors="coerce").dropna().mean(), 0)
            if not common_volume.dropna().empty else None
        )

        stats[symbol] = {
            "start_price": _round(start_price, 4),
            "end_price": _round(end_price, 4),
            "total_return_percent": _round(total_return, 4),
            "average_daily_return_percent": avg_daily,
            "volatility_percent": volatility,
            "average_volume": avg_volume,
            "observations": int(len(common_close)),
            "first_date": common_close.index.min().strftime("%Y-%m-%d") if len(common_close) else None,
            "last_date": common_close.index.max().strftime("%Y-%m-%d") if len(common_close) else None,
            "base_close": _round(bases.get(symbol), 4),
        }

    def _series_values(series: pd.Series, digits: int = 4) -> list:
        return [
            None if pd.isna(value) else round(float(value), digits)
            for value in series.reindex(filled.index)
        ]

    source_labels = sorted({str(s) for frame in valid.values() for s in frame["data_source"].dropna().unique()})
    return to_json_safe({
        "dates": [index.strftime("%Y-%m-%d") for index in filled.index],
        "symbols": list(closes.columns),
        "series": {
            symbol: {
                "normalized": _series_values(normalized[symbol]),
                "close": _series_values(filled[symbol]),
                "volume": [
                    None if pd.isna(value) else int(value)
                    for value in volumes[symbol].reindex(filled.index)
                ],
            }
            for symbol in closes.columns
        },
        "stats": stats,
        "warnings": warnings,
        "data_sources": source_labels,
        "is_sample": any(label == "sample" for label in source_labels),
        "methodology": {
            "normalization": (
                "Each stock's closing price is divided by its first available close "
                "in the selected range and multiplied by 100."
            ),
            "common_dates": int(len(common_dates)),
            "volatility": VOLATILITY_METHOD,
            "volume_note": "Average volume is computed on the common trading dates.",
            "disclaimer": "Historical comparison only; not an investment recommendation.",
        },
    })
