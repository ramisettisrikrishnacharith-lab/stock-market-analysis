"""Stock Market Analysis System - Flask application.

Pages are rendered with Jinja templates; all data is loaded through the JSON
API in this module. Market-data access, SQL, and statistics live in separate
modules (data_fetcher.py, database.py, analysis.py).
"""

from __future__ import annotations

import csv
import io
import logging
import math
from datetime import date, timedelta

from flask import Flask, Response, jsonify, render_template, request
from werkzeug.exceptions import HTTPException

import analysis
import database
import data_fetcher
from config import Settings, load_settings

logger = logging.getLogger(__name__)


class ApiError(Exception):
    def __init__(self, message: str, status: int = 400, code: str = "bad_request", details=None):
        super().__init__(message)
        self.message = message
        self.status = status
        self.code = code
        self.details = details


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------

def parse_date(value, field: str) -> date:
    if value is None or str(value).strip() == "":
        raise ApiError(f"'{field}' is required (YYYY-MM-DD).", 400, "missing_parameter")
    try:
        return date.fromisoformat(str(value).strip())
    except ValueError as exc:
        raise ApiError(f"'{field}' must be a valid date in YYYY-MM-DD format.", 400, "invalid_date") from exc


def resolve_range(args, default_days: int = 365, settings: Settings | None = None) -> tuple[date, date, Settings]:
    settings = settings or load_settings()
    today = date.today()
    end = parse_date(args.get("end"), "end") if args.get("end") else today
    start = parse_date(args.get("start"), "start") if args.get("start") else end - timedelta(days=default_days)
    if start > end:
        raise ApiError("Start date must be on or before the end date.", 400, "invalid_date_range")
    if (end - start).days > settings.max_range_days:
        raise ApiError(
            f"Date range is too large. The maximum is {settings.max_range_days} days.",
            400,
            "invalid_date_range",
        )
    return start, end, settings


def parse_page(args, settings: Settings) -> tuple[int, int]:
    try:
        page = int(args.get("page", 1))
        per_page = int(args.get("per_page", settings.default_page_size))
    except (TypeError, ValueError) as exc:
        raise ApiError("Pagination values must be integers.", 400, "invalid_pagination") from exc
    if page < 1:
        raise ApiError("Page must be at least 1.", 400, "invalid_pagination")
    per_page = max(1, min(per_page, settings.max_page_size))
    return page, per_page


def parse_bool(value) -> bool:
    return str(value).lower() in {"1", "true", "yes", "on"}


def json_body() -> dict:
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        raise ApiError("A JSON object body is required.", 400, "invalid_json")
    return payload


def error_json(message: str, status: int, code: str, details=None) -> tuple[Response, int]:
    body = {"error": {"code": code, "message": message}}
    if details:
        body["error"]["details"] = details
    return jsonify(body), status


def _stock_payload(stock: dict) -> dict:
    return {
        "stock_id": stock["stock_id"],
        "symbol": stock["symbol"],
        "company_name": stock["company_name"],
        "exchange": stock["exchange"],
        "has_data": bool(stock.get("price_count", 0)),
        "last_trade_date": stock.get("last_trade_date"),
        "price_count": int(stock.get("price_count", 0) or 0),
    }


# ---------------------------------------------------------------------------
# Application factory
# ---------------------------------------------------------------------------

def create_app(settings: Settings | None = None) -> Flask:
    cfg = settings or load_settings()
    database.configure(cfg)

    app = Flask(__name__)
    app.config.update(
        SECRET_KEY=cfg.flask_secret_key,
        DEBUG=cfg.flask_debug,
        JSON_SORT_KEYS=False,
    )
    app.extensions["app_settings"] = cfg
    app.json.ensure_ascii = False

    # ------------------------------------------------------------------
    # Pages
    # ------------------------------------------------------------------
    @app.route("/")
    def index():
        return render_template("index.html")

    @app.route("/analysis")
    def analysis_page():
        return render_template("stock_analysis.html")

    @app.route("/compare")
    def compare_page():
        return render_template("compare.html")

    @app.route("/watchlist")
    def watchlist_page():
        return render_template("watchlist.html")

    @app.route("/reports")
    def reports_page():
        return render_template("reports.html")

    @app.context_processor
    def inject_globals():
        return {
            "current_year": date.today().year,
            "has_twelve_data": cfg.has_twelve_data_key,
        }

    # ------------------------------------------------------------------
    # Stock catalogue
    # ------------------------------------------------------------------
    @app.get("/api/health")
    def health():
        try:
            database.fetch_one("SELECT 1 AS ok", settings=cfg)
            db_ok = True
        except database.DatabaseError:
            db_ok = False
        if not db_ok:
            return jsonify({"status": "degraded", "database": False}), 503
        return jsonify({"status": "ok", "database": True})

    @app.get("/api/stocks")
    def api_stocks():
        stocks = database.list_stocks(cfg)
        return jsonify({
            "stocks": [_stock_payload(stock) for stock in stocks],
            "count": len(stocks),
            "sample_symbols": data_fetcher.available_sample_symbols(cfg),
        })

    @app.get("/api/stocks/search")
    def api_search_stocks():
        query = (request.args.get("q") or "").strip()
        if not query:
            raise ApiError("Provide a search query using ?q=.", 400, "missing_parameter")
        if len(query) > 80:
            raise ApiError("Search query is too long.", 400, "invalid_parameter")
        results = database.search_stocks(query, 20, cfg)
        return jsonify({"query": query, "results": [_stock_payload(row) for row in results]})

    # ------------------------------------------------------------------
    # History and analysis
    # ------------------------------------------------------------------
    @app.get("/api/stocks/<symbol>/history")
    def api_history(symbol: str):
        symbol = data_fetcher.normalize_symbol(symbol)
        start, end, _ = resolve_range(request.args, settings=cfg)
        page, per_page = parse_page(request.args, cfg)
        refresh = parse_bool(request.args.get("refresh", "false"))

        try:
            result = data_fetcher.ensure_history(symbol, start, end, refresh=refresh, settings=cfg)
        except data_fetcher.MarketDataError as exc:
            raise ApiError(exc.message, exc.status, exc.code) from exc

        stock = database.get_stock_by_symbol(symbol, cfg)
        if stock is None:
            raise ApiError("Stock not found.", 404, "stock_not_found")

        offset = (page - 1) * per_page
        rows, total = database.get_price_page(stock["stock_id"], start.isoformat(), end.isoformat(), per_page, offset, cfg)
        total_pages = math.ceil(total / per_page) if total else 0

        return jsonify({
            "symbol": symbol,
            "company_name": stock["company_name"],
            "exchange": stock["exchange"],
            "start": start.isoformat(),
            "end": end.isoformat(),
            "source": result.source,
            "source_label": result.source_label,
            "is_sample": result.is_sample,
            "warning": result.warning,
            "page": page,
            "per_page": per_page,
            "total": total,
            "total_pages": total_pages,
            "rows": rows,
        })

    @app.get("/api/stocks/<symbol>/analysis")
    def api_analysis(symbol: str):
        symbol = data_fetcher.normalize_symbol(symbol)
        start, end, _ = resolve_range(request.args, settings=cfg)
        refresh = parse_bool(request.args.get("refresh", "false"))
        try:
            result = data_fetcher.ensure_history(symbol, start, end, refresh=refresh, settings=cfg)
        except data_fetcher.MarketDataError as exc:
            raise ApiError(exc.message, exc.status, exc.code) from exc

        stock = database.get_stock_by_symbol(symbol, cfg)
        info = analysis.calculate_analysis(result.frame)
        return jsonify({
            **info,
            "symbol": symbol,
            "company_name": stock["company_name"] if stock else symbol,
            "exchange": stock["exchange"] if stock else None,
            "start": start.isoformat(),
            "end": end.isoformat(),
            "source": result.source,
            "source_label": result.source_label,
            "warning": result.warning,
        })

    @app.get("/api/dashboard")
    def api_dashboard():
        start, end, _ = resolve_range(request.args, settings=cfg)
        requested = (request.args.get("symbol") or "").strip().upper()
        refresh = parse_bool(request.args.get("refresh", "false"))

        stock = None
        if requested:
            stock = database.get_stock_with_stats_by_symbol(requested, cfg)

        # If no specific symbol was requested or requested stock wasn't found, find default
        if stock is None:
            stocks = database.list_stocks(cfg)
            if not stocks:
                raise ApiError("No stocks are configured. Run init_db.py first.", 404, "no_stocks")
            stock = next((item for item in stocks if item.get("price_count")), stocks[0])
            total_stocks = len(stocks)
            tracked_stocks = [_stock_payload(item) for item in stocks]
        else:
            total_stocks = database.count_stocks(cfg)
            tracked_stocks = []

        try:
            result = data_fetcher.ensure_history(stock["symbol"], start, end, refresh=refresh, settings=cfg)
        except data_fetcher.MarketDataError as exc:
            raise ApiError(exc.message, exc.status, exc.code) from exc

        info = analysis.calculate_analysis(result.frame)
        return jsonify({
            "stocks_count": total_stocks,
            "watchlist_count": database.count_watchlist(cfg),
            "tracked_stocks": tracked_stocks,
            "stock": _stock_payload(stock),
            "start": start.isoformat(),
            "end": end.isoformat(),
            "source": result.source,
            "source_label": result.source_label,
            "is_sample": result.is_sample,
            "warning": result.warning,
            **info,
        })

    @app.post("/api/stocks/refresh")
    def api_refresh_stock():
        payload = json_body()
        symbol = data_fetcher.normalize_symbol(payload.get("symbol", ""))
        end = parse_date(payload.get("end"), "end") if payload.get("end") else date.today()
        start = parse_date(payload.get("start"), "start") if payload.get("start") else end - timedelta(days=365)
        if start > end:
            raise ApiError("Start date must be on or before the end date.", 400, "invalid_date_range")
        use_sample = parse_bool(payload.get("use_sample", False))

        try:
            if use_sample:
                result = data_fetcher.store_sample_for_symbol(symbol, start, end, cfg)
            else:
                result = data_fetcher.ensure_history(symbol, start, end, refresh=True, settings=cfg)
        except data_fetcher.MarketDataError as exc:
            raise ApiError(exc.message, exc.status, exc.code) from exc

        return jsonify({
            "message": "Stock data refreshed.",
            "symbol": symbol,
            "rows": int(len(result.frame)),
            "source": result.source,
            "source_label": result.source_label,
            "is_sample": result.is_sample,
            "warning": result.warning,
            "start": start.isoformat(),
            "end": end.isoformat(),
        })

    @app.post("/api/demo/load")
    def api_load_demo():
        end = date.today()
        start = end - timedelta(days=730)
        try:
            summary = data_fetcher.load_demo_data(start, end, cfg)
        except data_fetcher.MarketDataError as exc:
            raise ApiError(exc.message, exc.status, exc.code) from exc
        return jsonify(summary)

    # ------------------------------------------------------------------
    # Comparison
    # ------------------------------------------------------------------
    @app.get("/api/compare")
    def api_compare():
        raw_symbols = (request.args.get("symbols") or "").strip()
        if not raw_symbols:
            raise ApiError("Provide at least two ticker symbols using ?symbols=.", 400, "missing_parameter")
        symbols = []
        for raw in raw_symbols.split(","):
            if raw.strip():
                symbol = data_fetcher.normalize_symbol(raw)
                if symbol not in symbols:
                    symbols.append(symbol)
        if len(symbols) < 2:
            raise ApiError("Select at least two different stocks to compare.", 400, "insufficient_symbols")
        if len(symbols) > 6:
            raise ApiError("Compare at most six stocks at once.", 400, "too_many_symbols")

        start, end, _ = resolve_range(request.args, default_days=180, settings=cfg)
        frames: dict = {}
        metadata: dict = {}
        failures: dict = {}
        warnings: list[str] = []

        for symbol in symbols:
            try:
                result = data_fetcher.ensure_history(symbol, start, end, settings=cfg)
            except data_fetcher.MarketDataError as exc:
                failures[symbol] = exc.message
                continue
            if result.frame.empty:
                failures[symbol] = "No historical data in the selected range."
                continue
            frames[symbol] = result.frame
            stock = database.get_stock_by_symbol(symbol, cfg)
            metadata[symbol] = {
                "company_name": stock["company_name"] if stock else symbol,
                "exchange": stock["exchange"] if stock else None,
                "source": result.source,
                "is_sample": result.is_sample,
            }
            if result.warning:
                warnings.append(f"{symbol}: {result.warning}")

        if len(frames) < 2:
            raise ApiError(
                "At least two stocks need historical data for a comparison.",
                422,
                "comparison_unavailable",
                details=failures,
            )

        try:
            result = analysis.compare_stocks(frames)
        except ValueError as exc:
            raise ApiError(str(exc), 422, "comparison_unavailable", details=failures or None) from exc

        result["metadata"] = metadata
        result["failures"] = failures
        result["warnings"] = warnings + result.get("warnings", [])
        result["start"] = start.isoformat()
        result["end"] = end.isoformat()
        return jsonify(result)

    # ------------------------------------------------------------------
    # Watchlist
    # ------------------------------------------------------------------
    @app.get("/api/watchlist")
    def api_watchlist():
        rows = database.get_watchlist(cfg)
        items = []
        for row in rows:
            close = row.get("close_price")
            previous = row.get("previous_close")
            change = change_percent = None
            if close is not None and previous not in (None, 0):
                change = round(float(close) - float(previous), 4)
                change_percent = round((float(close) - float(previous)) / float(previous) * 100, 4)
            items.append({
                "watchlist_id": row["watchlist_id"],
                "stock_id": row["stock_id"],
                "symbol": row["symbol"],
                "company_name": row["company_name"],
                "exchange": row["exchange"],
                "added_at": row.get("added_at"),
                "trade_date": row.get("trade_date"),
                "close_price": float(close) if close is not None else None,
                "previous_close": float(previous) if previous is not None else None,
                "change": change,
                "change_percent": change_percent,
                "data_source": row.get("latest_source"),
            })
        return jsonify({"items": items, "count": len(items)})

    @app.post("/api/watchlist")
    def api_add_watchlist():
        payload = json_body()
        stock = None
        if payload.get("symbol"):
            symbol = data_fetcher.normalize_symbol(payload.get("symbol"))
            stock = database.get_stock_by_symbol(symbol, cfg)
        elif payload.get("stock_id") is not None:
            try:
                stock_id = int(payload.get("stock_id"))
            except (TypeError, ValueError) as exc:
                raise ApiError("stock_id must be an integer.", 400, "invalid_parameter") from exc
            stock = database.get_stock_by_id(stock_id, cfg)
        else:
            raise ApiError("Provide a stock_id or symbol.", 400, "missing_parameter")

        if stock is None:
            raise ApiError(
                "Stock not found. Open its analysis page once to load its data first.",
                404,
                "stock_not_found",
            )
        try:
            watchlist_id = database.add_to_watchlist(stock["stock_id"], cfg)
        except database.DuplicateWatchlistError as exc:
            raise ApiError(str(exc), 409, "duplicate_watchlist") from exc
        except LookupError as exc:
            raise ApiError("Stock does not exist.", 404, "stock_not_found") from exc

        return jsonify({
            "message": f"{stock['symbol']} added to the watchlist.",
            "watchlist_id": watchlist_id,
            "stock": _stock_payload(stock),
        }), 201

    @app.delete("/api/watchlist/<int:stock_id>")
    def api_remove_watchlist(stock_id: int):
        removed = database.remove_from_watchlist(stock_id, cfg)
        if not removed:
            raise ApiError("This stock is not in the watchlist.", 404, "not_in_watchlist")
        return jsonify({"message": "Removed from watchlist.", "stock_id": stock_id})

    # ------------------------------------------------------------------
    # Reports and CSV export
    # ------------------------------------------------------------------
    @app.get("/api/reports")
    def api_reports():
        symbol = data_fetcher.normalize_symbol(request.args.get("symbol", ""))
        start, end, _ = resolve_range(request.args, settings=cfg)
        page, per_page = parse_page(request.args, cfg)
        try:
            result = data_fetcher.ensure_history(symbol, start, end, settings=cfg)
        except data_fetcher.MarketDataError as exc:
            raise ApiError(exc.message, exc.status, exc.code) from exc

        stock = database.get_stock_by_symbol(symbol, cfg)
        offset = (page - 1) * per_page
        rows, total = database.get_price_page(stock["stock_id"], start.isoformat(), end.isoformat(), per_page, offset, cfg)
        return jsonify({
            "symbol": symbol,
            "company_name": stock["company_name"],
            "exchange": stock["exchange"],
            "start": start.isoformat(),
            "end": end.isoformat(),
            "source": result.source,
            "source_label": result.source_label,
            "is_sample": result.is_sample,
            "warning": result.warning,
            "page": page,
            "per_page": per_page,
            "total": total,
            "total_pages": math.ceil(total / per_page) if total else 0,
            "rows": rows,
        })

    @app.get("/api/reports/export")
    def api_export_report():
        symbol = data_fetcher.normalize_symbol(request.args.get("symbol", ""))
        start, end, _ = resolve_range(request.args, settings=cfg)
        export_type = (request.args.get("type") or "prices").strip().lower()
        if export_type not in {"prices", "analysis"}:
            raise ApiError("Export type must be 'prices' or 'analysis'.", 400, "invalid_export_type")

        try:
            data_fetcher.ensure_history(symbol, start, end, settings=cfg)
        except data_fetcher.MarketDataError as exc:
            raise ApiError(exc.message, exc.status, exc.code) from exc

        stock = database.get_stock_by_symbol(symbol, cfg)
        rows = database.get_prices(stock["stock_id"], start.isoformat(), end.isoformat(), cfg)
        if not rows:
            raise ApiError("No stored data matches this export request.", 404, "no_data")

        output = io.StringIO()
        writer = csv.writer(output, lineterminator="\n")

        if export_type == "prices":
            writer.writerow(["Date", "Open", "High", "Low", "Close", "Volume", "Data source"])
            for row in rows:
                writer.writerow([
                    row["trade_date"],
                    row["open_price"],
                    row["high_price"],
                    row["low_price"],
                    row["close_price"],
                    row["volume"],
                    row["data_source"],
                ])
        else:
            info = analysis.calculate_analysis(rows)
            writer.writerow(["Stock Market Analysis Report"])
            writer.writerow(["Symbol", symbol])
            writer.writerow(["Company", stock["company_name"]])
            writer.writerow(["Period start", start.isoformat()])
            writer.writerow(["Period end", end.isoformat()])
            writer.writerow(["Data source", info.get("data_source")])
            writer.writerow(["Observations", info["stats"]["observations"]])
            writer.writerow(["Average close", info["stats"]["average_close"]])
            writer.writerow(["Highest close", info["stats"]["highest_close"]])
            writer.writerow(["Lowest close", info["stats"]["lowest_close"]])
            writer.writerow(["Highest high", info["stats"]["highest_high"]])
            writer.writerow(["Lowest low", info["stats"]["lowest_low"]])
            writer.writerow(["Average volume", info["stats"]["average_volume"]])
            writer.writerow(["Total return %", info["total_return_percent"]])
            writer.writerow(["Average daily return %", info["daily_returns"]["average_percent"]])
            writer.writerow(["Daily return volatility %", info["daily_returns"]["volatility_percent"]])
            writer.writerow(["Volatility method", info["daily_returns"]["method"]])
            writer.writerow(["SMA 20", info["moving_averages"]["sma20"]])
            writer.writerow(["SMA 50", info["moving_averages"]["sma50"]])
            writer.writerow([])
            writer.writerow(["Date", "Close", "Daily return %", "SMA 20", "SMA 50", "Volume"])
            series = info["series"]
            for index, trade_date in enumerate(series["dates"]):
                writer.writerow([
                    trade_date,
                    series["close"][index],
                    series["daily_returns"][index],
                    series["sma20"][index],
                    series["sma50"][index],
                    series["volume"][index],
                ])

        filename = f"{export_type}_{symbol}_{start.isoformat()}_{end.isoformat()}.csv"
        payload = ("\ufeff" + output.getvalue()).encode("utf-8")
        return Response(
            payload,
            mimetype="text/csv",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    # ------------------------------------------------------------------
    # Error handling
    # ------------------------------------------------------------------
    @app.errorhandler(ApiError)
    def handle_api_error(exc: ApiError):
        return error_json(exc.message, exc.status, exc.code, exc.details)

    @app.errorhandler(database.DatabaseError)
    def handle_database_error(exc: database.DatabaseError):
        logger.exception("Database error")
        return error_json(str(exc), 503, "database_unavailable")

    @app.errorhandler(data_fetcher.MarketDataError)
    def handle_market_error(exc: data_fetcher.MarketDataError):
        return error_json(exc.message, exc.status, exc.code)

    @app.errorhandler(HTTPException)
    def handle_http_error(exc: HTTPException):
        if request.path.startswith("/api/"):
            message = exc.description or "HTTP error"
            return error_json(message, exc.code or 500, "http_error")
        return render_template(
            "error.html",
            code=exc.code or 500,
            message=exc.description or "Something went wrong.",
        ), exc.code or 500

    @app.errorhandler(Exception)
    def handle_unexpected_error(exc: Exception):
        logger.exception("Unhandled application error")
        if request.path.startswith("/api/"):
            return error_json(
                "An unexpected server error occurred. Please try again.",
                500,
                "internal_error",
            )
        return render_template(
            "error.html",
            code=500,
            message="An unexpected server error occurred. Check the server log for details.",
        ), 500

    return app


app = create_app()


if __name__ == "__main__":
    config = load_settings()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    print(f"Stock Market Analysis System running at http://{config.flask_host}:{config.flask_port}/")
    app.run(host=config.flask_host, port=config.flask_port, debug=config.flask_debug)
