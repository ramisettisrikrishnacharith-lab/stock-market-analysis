"""Market-data retrieval, validation, caching, and MySQL persistence.

Data sources
------------
* ``yfinance`` - historical prices retrieved from Yahoo Finance. Availability
  and usage are subject to the provider.
* ``sample``   - a bundled CSV snapshot used only for offline demonstrations.

The two sources are always stored and labelled separately. Sample data never
overwrites retrieved market data, and no other ticker is substituted when a
symbol is invalid.
"""

from __future__ import annotations

import logging
import re
import threading
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

import pandas as pd

import analysis
import database
from config import Settings, load_settings

logger = logging.getLogger(__name__)

SYMBOL_RE = re.compile(r"^[A-Z0-9][A-Z0-9.\-^=]{0,19}$")

SEED_STOCKS: list[dict[str, str]] = [
    {"symbol": "RELIANCE.NS", "company_name": "Reliance Industries Ltd.", "exchange": "NSE"},
    {"symbol": "TCS.NS", "company_name": "Tata Consultancy Services Ltd.", "exchange": "NSE"},
    {"symbol": "INFY.NS", "company_name": "Infosys Ltd.", "exchange": "NSE"},
    {"symbol": "HDFCBANK.NS", "company_name": "HDFC Bank Ltd.", "exchange": "NSE"},
    {"symbol": "ICICIBANK.NS", "company_name": "ICICI Bank Ltd.", "exchange": "NSE"},
    {"symbol": "AAPL", "company_name": "Apple Inc.", "exchange": "NASDAQ"},
    {"symbol": "MSFT", "company_name": "Microsoft Corp.", "exchange": "NASDAQ"},
    {"symbol": "GOOGL", "company_name": "Alphabet Inc.", "exchange": "NASDAQ"},
    {"symbol": "AMZN", "company_name": "Amazon.com Inc.", "exchange": "NASDAQ"},
    {"symbol": "NVDA", "company_name": "NVIDIA Corp.", "exchange": "NASDAQ"},
]

SEED_BY_SYMBOL = {item["symbol"]: item for item in SEED_STOCKS}
SOURCE_LABELS = {
    "twelve_data": "Retrieved market data (Twelve Data)",
    "yfinance": "Retrieved market data (yfinance)",
    "sample": "Sample snapshot data (offline demo)",
    "mixed": "Mixed retrieved and sample data",
    "unknown": "Unknown data source",
}


class MarketDataError(Exception):
    """Friendly error for missing/invalid market data."""

    def __init__(self, message: str, *, code: str = "market_data_unavailable", status: int = 422):
        super().__init__(message)
        self.message = message
        self.code = code
        self.status = status


@dataclass
class HistoryResult:
    symbol: str
    frame: pd.DataFrame
    source: str
    is_sample: bool
    warning: str | None = None

    @property
    def source_label(self) -> str:
        return SOURCE_LABELS.get(self.source, SOURCE_LABELS["unknown"])


def normalize_symbol(symbol: str) -> str:
    if not isinstance(symbol, str):
        raise MarketDataError("A valid ticker symbol is required.", code="invalid_symbol", status=400)
    value = symbol.strip().upper()
    if not SYMBOL_RE.fullmatch(value):
        raise MarketDataError(
            "Ticker symbols may contain letters, numbers, '.', '-' or '^' (max 20 characters).",
            code="invalid_symbol",
            status=400,
        )
    return value


def exchange_for_symbol(symbol: str) -> str | None:
    if symbol.endswith(".NS"):
        return "NSE"
    if symbol.endswith(".BO"):
        return "BSE"
    if symbol.startswith("^"):
        return "INDEX"
    if symbol in SEED_BY_SYMBOL:
        return SEED_BY_SYMBOL[symbol]["exchange"]
    return None


def _frame_rows(frame: pd.DataFrame) -> list[tuple]:
    rows: list[tuple] = []
    for timestamp, row in frame.iterrows():
        def _number(column: str) -> float | None:
            value = row.get(column)
            return None if value is None or pd.isna(value) else round(float(value), 4)

        volume_value = row.get("volume")
        volume = None if volume_value is None or pd.isna(volume_value) else int(volume_value)
        rows.append((
            timestamp.date() if hasattr(timestamp, "date") else timestamp,
            _number("open_price"),
            _number("high_price"),
            _number("low_price"),
            _number("close_price"),
            volume,
        ))
    return rows


def _frame_from_db(rows: list[dict]) -> pd.DataFrame:
    return analysis.prepare_frame(rows)


def _sources(frame: pd.DataFrame) -> list[str]:
    if frame.empty or "data_source" not in frame.columns:
        return []
    return sorted({str(value) for value in frame["data_source"].dropna().unique()})


def _source_label(sources: list[str]) -> str:
    if not sources:
        return "unknown"
    if len(sources) == 1:
        return sources[0]
    return "mixed"


def _has_coverage(bounds: dict | None, start: date, end: date) -> bool:
    """True when stored data covers the request, allowing for weekends/holidays."""
    if not bounds or not bounds.get("first_date") or not bounds.get("last_date"):
        return False
    first = date.fromisoformat(str(bounds["first_date"]))
    last = date.fromisoformat(str(bounds["last_date"]))
    # A range may start on a weekend/holiday, so the first stored trading day can
    # legitimately be a few days after the requested start.
    return first <= (start + timedelta(days=5)) and last >= (end - timedelta(days=5))


def _validate_range(start: date, end: date) -> None:
    if start > end:
        raise MarketDataError("Start date must be on or before the end date.", code="invalid_date_range", status=400)
    if (end - start).days > 3650:
        raise MarketDataError("Date range is too large (maximum 10 years).", code="invalid_date_range", status=400)


# ---------------------------------------------------------------------------
# yfinance retrieval
# ---------------------------------------------------------------------------

def _download_yfinance(symbol: str, start: date, end: date, timeout: int) -> tuple[pd.DataFrame, dict]:
    """Download data in a daemon thread so a stalled request cannot block Flask."""
    result: dict[str, Any] = {}

    def worker() -> None:
        try:
            import yfinance as yf

            ticker = yf.Ticker(symbol)
            raw = ticker.history(
                start=start.isoformat(),
                end=(end + timedelta(days=1)).isoformat(),
                auto_adjust=False,
                actions=False,
                timeout=timeout,
            )
            metadata: dict = {}
            try:
                meta = ticker.history_metadata or {}
                metadata = {
                    "company_name": meta.get("longName") or meta.get("shortName"),
                    "exchange": meta.get("fullExchangeName") or meta.get("exchangeName"),
                }
            except Exception:  # metadata is optional
                metadata = {}
            result["data"] = (raw, metadata)
        except Exception as exc:  # network, provider, or parsing error
            result["error"] = exc

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()
    thread.join(timeout=timeout + 3)
    if thread.is_alive():
        raise MarketDataError(
            "The market-data provider did not respond in time. Try again or use sample data.",
            code="provider_timeout",
            status=504,
        )
    if "error" in result:
        logger.warning("yfinance request failed for %s: %s", symbol, result["error"])
        raise MarketDataError(
            "The market-data provider could not be reached. Check your internet connection "
            "or load the sample data for an offline demonstration.",
            code="provider_unavailable",
            status=503,
        )
    return result["data"]


def _clean_yfinance(raw: pd.DataFrame, start: date, end: date, symbol: str) -> pd.DataFrame:
    if raw is None or raw.empty:
        raise MarketDataError(
            f"No historical data was returned for '{symbol}'. Check that the ticker is valid "
            "and that the selected dates include trading days.",
            code="no_data",
            status=404,
        )

    frame = raw.copy()
    if isinstance(frame.columns, pd.MultiIndex):
        frame.columns = frame.columns.get_level_values(0)
    frame = frame.reset_index()
    rename = {
        "Date": "trade_date",
        "Datetime": "trade_date",
        "Open": "open_price",
        "High": "high_price",
        "Low": "low_price",
        "Close": "close_price",
        "Volume": "volume",
    }
    frame = frame.rename(columns=rename)
    if "trade_date" not in frame.columns:
        raise MarketDataError("Unexpected data format received from the provider.", code="bad_provider_data")

    frame["trade_date"] = pd.to_datetime(frame["trade_date"], errors="coerce")
    if frame["trade_date"].dt.tz is not None:
        frame["trade_date"] = frame["trade_date"].dt.tz_localize(None)
    frame["data_source"] = "yfinance"
    # Only completed sessions are stored. The provider's row for the current day
    # can still be an in-progress intraday price, not a final daily close.
    frame = frame[frame["trade_date"].dt.date < date.today()]
    frame = analysis.prepare_frame(frame)
    frame = frame[(frame.index.date >= start) & (frame.index.date <= end)]
    if frame.empty:
        raise MarketDataError(
            f"No trading data for '{symbol}' falls within the selected dates.",
            code="no_data_in_range",
            status=404,
        )
    return frame


# ---------------------------------------------------------------------------
# Twelve Data retrieval
# ---------------------------------------------------------------------------

def _download_twelve_data(
    symbol: str,
    start: date,
    end: date,
    api_key: str,
    timeout: int,
) -> tuple[pd.DataFrame, dict]:
    """Download historical daily prices from Twelve Data REST API."""
    if not api_key or not api_key.strip() or api_key.strip() == "YOUR_API_KEY_HERE":
        raise MarketDataError(
            "Twelve Data API key is missing or not configured. Add TWELVE_DATA_API_KEY to your .env file or use sample data.",
            code="missing_api_key",
            status=401,
        )

    # For Indian stocks: Twelve Data uses e.g. symbol=RELIANCE, exchange=NSE
    req_symbol = symbol
    exchange_param = None
    if symbol.endswith(".NS"):
        req_symbol = symbol[:-3]
        exchange_param = "NSE"
    elif symbol.endswith(".BO"):
        req_symbol = symbol[:-3]
        exchange_param = "BSE"

    url = "https://api.twelvedata.com/time_series"
    params = {
        "symbol": req_symbol,
        "interval": "1day",
        "start_date": start.isoformat(),
        "end_date": (end + timedelta(days=1)).isoformat(),
        "apikey": api_key.strip(),
        "outputsize": 5000,
    }
    if exchange_param:
        params["exchange"] = exchange_param

    result: dict[str, Any] = {}

    def worker() -> None:
        try:
            import requests

            resp = requests.get(url, params=params, timeout=timeout)
            result["data"] = resp.json()
        except Exception as exc:
            result["error"] = exc

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()
    thread.join(timeout=timeout + 3)

    if thread.is_alive():
        raise MarketDataError(
            "The Twelve Data API did not respond in time. Try again or use sample data.",
            code="provider_timeout",
            status=504,
        )

    if "error" in result:
        logger.warning("Twelve Data request failed for %s: %s", symbol, type(result["error"]).__name__)
        raise MarketDataError(
            "Twelve Data service could not be reached. Check your network or use sample data.",
            code="provider_unavailable",
            status=503,
        )

    data = result.get("data")
    if not isinstance(data, dict):
        raise MarketDataError("Unexpected response format from Twelve Data API.", code="bad_provider_data", status=502)

    if data.get("status") == "error":
        msg = data.get("message", "Twelve Data API error.")
        code = data.get("code", 400)
        # Avoid leaking key
        if "api_key" in msg.lower() or "apikey" in msg.lower() or code in (401, 403):
            raise MarketDataError(
                "Invalid or unauthorized Twelve Data API key. Check TWELVE_DATA_API_KEY in .env.",
                code="invalid_api_key",
                status=401,
            )
        raise MarketDataError(
            f"Twelve Data error: {msg}",
            code="provider_error",
            status=400,
        )

    values = data.get("values")
    if not values:
        raise MarketDataError(
            f"No historical prices returned from Twelve Data for '{symbol}'.",
            code="no_data",
            status=404,
        )

    meta = data.get("meta") or {}
    metadata = {
        "company_name": meta.get("symbol"),
        "exchange": meta.get("exchange") or exchange_param,
    }
    frame = pd.DataFrame(values)
    frame = frame.rename(columns={
        "datetime": "trade_date",
        "open": "open_price",
        "high": "high_price",
        "low": "low_price",
        "close": "close_price",
    })
    frame["trade_date"] = pd.to_datetime(frame["trade_date"], errors="coerce")
    for col in ["open_price", "high_price", "low_price", "close_price", "volume"]:
        if col in frame.columns:
            frame[col] = pd.to_numeric(frame[col], errors="coerce")
    frame["data_source"] = "twelve_data"
    frame = frame[frame["trade_date"].dt.date < date.today()]
    frame = analysis.prepare_frame(frame)
    frame = frame[(frame.index.date >= start) & (frame.index.date <= end)]
    if frame.empty:
        raise MarketDataError(
            f"No trading data for '{symbol}' falls within the selected dates.",
            code="no_data_in_range",
            status=404,
        )
    return frame, metadata


# ---------------------------------------------------------------------------
# Sample CSV retrieval
# ---------------------------------------------------------------------------

def sample_data_path(settings: Settings | None = None):
    return (settings or load_settings()).sample_data_file


def available_sample_symbols(settings: Settings | None = None) -> list[str]:
    path = sample_data_path(settings)
    if not path.exists():
        return []
    try:
        frame = pd.read_csv(path, usecols=["symbol"])
    except (ValueError, pd.errors.ParserError):
        return []
    return sorted({str(value).upper() for value in frame["symbol"].dropna().unique()})


def load_sample_data(symbol: str, start: date, end: date, settings: Settings | None = None) -> pd.DataFrame:
    path = sample_data_path(settings)
    if not path.exists():
        raise MarketDataError(
            "No sample data file is available. Add data/sample_stock_data.csv.",
            code="sample_unavailable",
            status=404,
        )
    symbol = normalize_symbol(symbol)
    try:
        raw = pd.read_csv(path)
    except (OSError, pd.errors.ParserError, pd.errors.EmptyDataError) as exc:
        raise MarketDataError("The sample data file could not be read.", code="sample_unavailable") from exc

    required = {"symbol", "trade_date", "open", "high", "low", "close", "volume"}
    missing = required.difference(raw.columns)
    if missing:
        raise MarketDataError(
            f"Sample data is missing columns: {', '.join(sorted(missing))}.",
            code="sample_invalid",
        )
    raw["symbol"] = raw["symbol"].astype(str).str.upper().str.strip()
    raw = raw[raw["symbol"] == symbol]
    if raw.empty:
        raise MarketDataError(
            f"No sample data is bundled for '{symbol}'.",
            code="sample_missing_symbol",
            status=404,
        )
    frame = raw.rename(columns={
        "open": "open_price", "high": "high_price", "low": "low_price",
        "close": "close_price",
    })
    frame["trade_date"] = pd.to_datetime(frame["trade_date"], errors="coerce")
    frame["data_source"] = "sample"
    frame = analysis.prepare_frame(frame)
    frame = frame[(frame.index.date >= start) & (frame.index.date <= end)]
    if frame.empty:
        raise MarketDataError(
            f"Sample data for '{symbol}' does not cover the selected dates.",
            code="sample_no_range",
            status=404,
        )
    return frame


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------

def _stored_result(stock: dict, start: date, end: date, warning: str | None = None, settings: Settings | None = None) -> HistoryResult | None:
    rows = database.get_prices(stock["stock_id"], start.isoformat(), end.isoformat(), settings)
    if not rows:
        return None
    frame = _frame_from_db(rows)
    if frame.empty:
        return None
    sources = _sources(frame)
    label = _source_label(sources)
    return HistoryResult(
        symbol=stock["symbol"],
        frame=frame,
        source=label,
        is_sample="sample" in sources,
        warning=warning,
    )


def ensure_history(
    symbol: str,
    start: date,
    end: date,
    *,
    refresh: bool = False,
    settings: Settings | None = None,
) -> HistoryResult:
    """Return validated history for a symbol, fetching and caching as needed.

    Order of operations:
    1. Use sufficient stored data when available.
    2. Try yfinance and persist retrieved rows.
    3. Fall back to the labelled sample CSV if the provider is unavailable.
    4. Otherwise fall back to any previously stored rows, with a warning.
    """
    cfg = settings or load_settings()
    symbol = normalize_symbol(symbol)
    _validate_range(start, end)
    stock = database.get_stock_by_symbol(symbol, cfg)

    if stock and not refresh:
        bounds = database.get_price_bounds(stock["stock_id"], cfg)
        if _has_coverage(bounds, start, end):
            stored = _stored_result(stock, start, end, settings=cfg)
            if stored is not None:
                # If Twelve Data is configured as the preferred provider, only use
                # cached data if it was already retrieved from Twelve Data.
                # If cached rows came from yfinance or sample, proceed to Twelve Data to upgrade.
                if not cfg.has_twelve_data_key or stored.source == "twelve_data":
                    return stored

    provider_error: MarketDataError | None = None

    # 1. Try Twelve Data when configured
    if cfg.has_twelve_data_key:
        try:
            frame, meta = _download_twelve_data(symbol, start, end, cfg.twelve_data_api_key, cfg.fetch_timeout_seconds)
            seed = SEED_BY_SYMBOL.get(symbol, {})
            company_name = (
                (stock or {}).get("company_name")
                or seed.get("company_name")
                or meta.get("company_name")
                or symbol
            )
            exchange = (stock or {}).get("exchange") or seed.get("exchange") or exchange_for_symbol(symbol) or meta.get("exchange")
            stock = database.get_or_create_stock(symbol, company_name, exchange, cfg)
            database.upsert_prices(stock["stock_id"], _frame_rows(frame), "twelve_data", cfg)
            stored = _stored_result(stock, start, end, settings=cfg)
            if stored is not None:
                return stored
        except Exception as exc:
            if isinstance(exc, MarketDataError):
                provider_error = exc
            else:
                provider_error = MarketDataError(str(exc))
            logger.info("Twelve Data fetch failed for %s: %s", symbol, exc)
            # If we already have stored data in MySQL, fall back to it with a clear note
            if stock:
                stored = _stored_result(
                    stock,
                    start,
                    end,
                    warning=f"Twelve Data retrieval unavailable ({provider_error.message}). Showing cached historical data.",
                    settings=cfg,
                )
                if stored is not None:
                    return stored

    # 2. Try yfinance
    try:
        raw, meta = _download_yfinance(symbol, start, end, cfg.fetch_timeout_seconds)
        frame = _clean_yfinance(raw, start, end, symbol)
        seed = SEED_BY_SYMBOL.get(symbol, {})
        company_name = (
            (stock or {}).get("company_name")
            or seed.get("company_name")
            or meta.get("company_name")
            or symbol
        )
        exchange = (stock or {}).get("exchange") or seed.get("exchange") or exchange_for_symbol(symbol) or meta.get("exchange")
        stock = database.get_or_create_stock(symbol, company_name, exchange, cfg)
        database.upsert_prices(stock["stock_id"], _frame_rows(frame), "yfinance", cfg)
        stored = _stored_result(stock, start, end, settings=cfg)
        if stored is None:
            raise MarketDataError("The retrieved data could not be stored.", code="storage_error")
        return stored
    except MarketDataError as exc:
        if not provider_error:
            provider_error = exc
        logger.info("Falling back to sample/stored data for %s: %s", symbol, exc.message)

    # Sample CSV fallback (clearly labelled, never overwrites retrieved data).
    try:
        sample_frame = load_sample_data(symbol, start, end, cfg)
        seed = SEED_BY_SYMBOL.get(symbol, {})
        stock = database.get_or_create_stock(
            symbol,
            (stock or {}).get("company_name") or seed.get("company_name") or symbol,
            (stock or {}).get("exchange") or seed.get("exchange") or exchange_for_symbol(symbol),
            cfg,
        )
        database.upsert_prices(stock["stock_id"], _frame_rows(sample_frame), "sample", cfg)
        stored = _stored_result(
            stock,
            start,
            end,
            warning=(
                "Market data could not be retrieved, so the bundled sample snapshot "
                "is shown. It is not live or current market data."
            ),
            settings=cfg,
        )
        if stored is not None:
            return stored
        raise MarketDataError("The sample data could not be stored.", code="storage_error")
    except MarketDataError as sample_error:
        # Last resort: show whatever is already stored, clearly flagged as stale.
        if stock:
            stored = _stored_result(
                stock,
                start,
                end,
                warning=(
                    "Market data could not be refreshed. Showing previously stored data; "
                    "it may be out of date. " + (sample_error.message if sample_error.code != "sample_missing_symbol" else "")
                ).strip(),
                settings=cfg,
            )
            if stored is not None:
                return stored
        message = provider_error.message if provider_error else sample_error.message
        raise MarketDataError(
            f"{message} No sample data is available for '{symbol}' in this date range.",
            code=provider_error.code if provider_error else sample_error.code,
            status=provider_error.status if provider_error else sample_error.status,
        ) from provider_error


def load_demo_data(
    start: date,
    end: date,
    settings: Settings | None = None,
) -> dict:
    """Load every bundled sample symbol into MySQL (for offline demonstrations)."""
    cfg = settings or load_settings()
    _validate_range(start, end)
    symbols = available_sample_symbols(cfg)
    if not symbols:
        raise MarketDataError(
            "Sample data is unavailable. Check data/sample_stock_data.csv.",
            code="sample_unavailable",
            status=404,
        )
    loaded: list[str] = []
    skipped: list[str] = []
    total_rows = 0
    for symbol in symbols:
        try:
            frame = load_sample_data(symbol, start, end, cfg)
        except MarketDataError:
            skipped.append(symbol)
            continue
        seed = SEED_BY_SYMBOL.get(symbol, {})
        existing = database.get_stock_by_symbol(symbol, cfg)
        if existing:
            bounds = database.get_price_bounds(existing["stock_id"], cfg)
            if bounds and bounds.get("row_count"):
                # Never mix sample history into a stock that already has stored data.
                skipped.append(symbol)
                continue
        stock = database.get_or_create_stock(
            symbol,
            seed.get("company_name") or symbol,
            seed.get("exchange") or exchange_for_symbol(symbol),
            cfg,
        )
        database.upsert_prices(stock["stock_id"], _frame_rows(frame), "sample", cfg)
        loaded.append(symbol)
        total_rows += len(frame)
    if not loaded:
        raise MarketDataError(
            "The sample file does not contain data for the selected date range.",
            code="sample_no_range",
            status=404,
        )
    return {
        "loaded_symbols": loaded,
        "skipped_symbols": skipped,
        "rows_written": total_rows,
        "start": start.isoformat(),
        "end": end.isoformat(),
        "is_sample": True,
        "message": "Sample snapshot data loaded. These are not live market prices.",
    }


def store_sample_for_symbol(
    symbol: str,
    start: date,
    end: date,
    settings: Settings | None = None,
) -> HistoryResult:
    """Explicitly load one symbol from the sample CSV."""
    cfg = settings or load_settings()
    symbol = normalize_symbol(symbol)
    _validate_range(start, end)
    frame = load_sample_data(symbol, start, end, cfg)
    stock = database.get_stock_by_symbol(symbol, cfg)
    if stock is None:
        seed = SEED_BY_SYMBOL.get(symbol, {})
        stock = database.get_or_create_stock(
            symbol,
            seed.get("company_name") or symbol,
            seed.get("exchange") or exchange_for_symbol(symbol),
            cfg,
        )
    database.upsert_prices(stock["stock_id"], _frame_rows(frame), "sample", cfg)
    stored = _stored_result(
        stock,
        start,
        end,
        warning="Sample snapshot loaded explicitly. It is not live market data.",
        settings=cfg,
    )
    if stored is None:
        raise MarketDataError("Sample data could not be stored.", code="storage_error")
    return stored
