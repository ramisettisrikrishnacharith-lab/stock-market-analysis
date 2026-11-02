"""Reusable MySQL access layer.

Every SQL statement uses parameter placeholders for user-controlled values.
Database and table identifiers are validated before being interpolated.
Connections and cursors are always closed.
"""

from __future__ import annotations

import re
from contextlib import contextmanager
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Iterable, Sequence

import mysql.connector
from mysql.connector import Error as MySQLError

from config import Settings, load_settings

_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9_]+$")
_SETTINGS: Settings | None = None


class DatabaseError(RuntimeError):
    """A safe, user-facing database error (no credentials or stack traces)."""


class DuplicateWatchlistError(Exception):
    """Raised when a stock is already present in the watchlist."""


def configure(settings: Settings) -> None:
    """Set the module-wide settings (used by the Flask app factory and tests)."""
    global _SETTINGS
    _SETTINGS = settings


def _resolve(settings: Settings | None = None) -> Settings:
    return settings or _SETTINGS or load_settings()


def _check_identifier(name: str, label: str = "identifier") -> str:
    if not name or not _IDENTIFIER_RE.fullmatch(name):
        raise DatabaseError(f"Invalid {label}.")
    return name


def get_connection(
    settings: Settings | None = None,
    *,
    database: str | None = None,
    admin: bool = False,
):
    """Open a MySQL connection.

    ``database`` defaults to the configured database name. Pass an empty
    string to connect at server level (needed to create a database).
    """
    cfg = _resolve(settings)
    db_name = cfg.db_name if database is None else database
    if db_name:
        _check_identifier(db_name, "database name")

    params = {
        "host": cfg.db_host,
        "port": cfg.db_port,
        "user": cfg.admin_user if admin else cfg.db_user,
        "password": cfg.admin_password if admin else cfg.db_password,
        "connection_timeout": 10,
        "charset": "utf8mb4",
        "use_unicode": True,
        "autocommit": False,
    }
    if db_name:
        params["database"] = db_name

    if cfg.db_ssl_ca:
        params["ssl_ca"] = cfg.db_ssl_ca
        params["ssl_verify_cert"] = True
        params["ssl_verify_identity"] = True

    try:
        return mysql.connector.connect(**params)
    except MySQLError as exc:
        # Keep the original error number for logs, but never expose credentials.
        errno = getattr(exc, "errno", None)
        if errno == 1045:
            message = "MySQL access denied. Check DB_USER and DB_PASSWORD in .env."
        elif errno == 1049:
            message = f"MySQL database '{db_name}' does not exist. Run init_db.py first."
        elif errno in {2003, 2005}:
            message = "Could not reach MySQL. Is the MySQL80 service running?"
        else:
            message = "Could not connect to MySQL. Check the database configuration."
        raise DatabaseError(message) from exc


@contextmanager
def cursor(
    settings: Settings | None = None,
    *,
    dictionary: bool = True,
    database: str | None = None,
    admin: bool = False,
):
    conn = get_connection(settings, database=database, admin=admin)
    cur = conn.cursor(dictionary=dictionary)
    try:
        yield conn, cur
    finally:
        cur.close()
        conn.close()


def _json_value(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, datetime):
        return value.isoformat(sep=" ")
    if isinstance(value, date):
        return value.isoformat()
    return value


def _clean_row(row: dict | None) -> dict | None:
    if row is None:
        return None
    return {key: _json_value(value) for key, value in row.items()}


def fetch_all(
    sql: str,
    params: Sequence[Any] = (),
    settings: Settings | None = None,
) -> list[dict]:
    try:
        with cursor(settings) as (_conn, cur):
            cur.execute(sql, params)
            rows = cur.fetchall()
    except MySQLError as exc:
        raise DatabaseError("The database query failed.") from exc
    return [_clean_row(row) for row in rows]


def fetch_one(
    sql: str,
    params: Sequence[Any] = (),
    settings: Settings | None = None,
) -> dict | None:
    try:
        with cursor(settings) as (_conn, cur):
            cur.execute(sql, params)
            row = cur.fetchone()
    except MySQLError as exc:
        raise DatabaseError("The database query failed.") from exc
    return _clean_row(row)


def execute(
    sql: str,
    params: Sequence[Any] = (),
    settings: Settings | None = None,
) -> int:
    """Execute one statement in its own transaction; return lastrowid."""
    with cursor(settings) as (conn, cur):
        try:
            cur.execute(sql, params)
            conn.commit()
            return cur.lastrowid
        except MySQLError as exc:
            conn.rollback()
            raise DatabaseError("The database rejected the operation.") from exc


def execute_many(
    sql: str,
    rows: Iterable[Sequence[Any]],
    settings: Settings | None = None,
) -> int:
    rows = list(rows)
    if not rows:
        return 0
    with cursor(settings) as (conn, cur):
        try:
            cur.executemany(sql, rows)
            conn.commit()
            return cur.rowcount
        except MySQLError as exc:
            conn.rollback()
            raise DatabaseError("The database rejected the batch operation.") from exc


# ---------------------------------------------------------------------------
# Schema helpers
# ---------------------------------------------------------------------------

def create_database(settings: Settings | None = None) -> None:
    """Create the configured database if missing using administrator credentials."""
    cfg = _resolve(settings)
    db_name = _check_identifier(cfg.db_name, "database name")
    try:
        conn = get_connection(cfg, database="", admin=True)
    except DatabaseError:
        # Fall back to the normal user, which may have CREATE privileges.
        conn = get_connection(cfg, database="", admin=False)
    try:
        cur = conn.cursor()
        try:
            cur.execute(
                f"CREATE DATABASE IF NOT EXISTS `{db_name}` "
                "CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
            )
            conn.commit()
        finally:
            cur.close()
    except MySQLError as exc:
        conn.rollback()
        raise DatabaseError(
            "Could not create the database. The configured MySQL user needs "
            "CREATE privileges, or DB_ADMIN_USER/DB_ADMIN_PASSWORD must be set."
        ) from exc
    finally:
        conn.close()


def table_exists(table: str, settings: Settings | None = None) -> bool:
    row = fetch_one(
        "SELECT COUNT(*) AS count FROM information_schema.tables "
        "WHERE table_schema = DATABASE() AND table_name = %s",
        (table,),
        settings,
    )
    return bool(row and row["count"])


# ---------------------------------------------------------------------------
# Stocks
# ---------------------------------------------------------------------------

_STOCK_COLUMNS = """
    s.stock_id, s.symbol, s.company_name, s.exchange, s.created_at
"""


def list_stocks(settings: Settings | None = None) -> list[dict]:
    return fetch_all(
        f"""
        SELECT {_STOCK_COLUMNS},
               COUNT(p.price_id) AS price_count,
               MAX(p.trade_date) AS last_trade_date
        FROM stocks s
        LEFT JOIN stock_prices p ON p.stock_id = s.stock_id
        GROUP BY s.stock_id, s.symbol, s.company_name, s.exchange, s.created_at
        ORDER BY s.symbol
        """,
        settings=settings,
    )


def search_stocks(query: str, limit: int = 20, settings: Settings | None = None) -> list[dict]:
    like = f"%{query.strip()}%"
    limit = max(1, min(int(limit), 50))
    return fetch_all(
        f"""
        SELECT {_STOCK_COLUMNS},
               COUNT(p.price_id) AS price_count,
               MAX(p.trade_date) AS last_trade_date
        FROM stocks s
        LEFT JOIN stock_prices p ON p.stock_id = s.stock_id
        WHERE s.symbol LIKE %s OR s.company_name LIKE %s
        GROUP BY s.stock_id, s.symbol, s.company_name, s.exchange, s.created_at
        ORDER BY
            CASE WHEN s.symbol = %s THEN 0
                 WHEN s.symbol LIKE %s THEN 1
                 ELSE 2 END,
            s.symbol
        LIMIT %s
        """,
        (like, like, query.strip().upper(), f"{query.strip().upper()}%", limit),
        settings,
    )


def get_stock_by_symbol(symbol: str, settings: Settings | None = None) -> dict | None:
    return fetch_one(
        f"SELECT {_STOCK_COLUMNS} FROM stocks s WHERE s.symbol = %s",
        (symbol.upper(),),
        settings,
    )


def get_stock_with_stats_by_symbol(symbol: str, settings: Settings | None = None) -> dict | None:
    """Fetch a single stock with its price count and last trade date."""
    return fetch_one(
        f"""
        SELECT {_STOCK_COLUMNS},
               COUNT(p.price_id) AS price_count,
               MAX(p.trade_date) AS last_trade_date
        FROM stocks s
        LEFT JOIN stock_prices p ON p.stock_id = s.stock_id
        WHERE s.symbol = %s
        GROUP BY s.stock_id, s.symbol, s.company_name, s.exchange, s.created_at
        """,
        (symbol.upper(),),
        settings,
    )


def get_stock_by_id(stock_id: int, settings: Settings | None = None) -> dict | None:
    return fetch_one(
        f"SELECT {_STOCK_COLUMNS} FROM stocks s WHERE s.stock_id = %s",
        (stock_id,),
        settings,
    )


def get_or_create_stock(
    symbol: str,
    company_name: str | None = None,
    exchange: str | None = None,
    settings: Settings | None = None,
) -> dict:
    """Insert a stock if it does not exist, then return its row."""
    symbol = symbol.upper().strip()
    company_name = (company_name or symbol).strip() or symbol
    try:
        execute(
            """
            INSERT INTO stocks (symbol, company_name, exchange)
            VALUES (%s, %s, %s)
            ON DUPLICATE KEY UPDATE
                stock_id = LAST_INSERT_ID(stock_id),
                company_name = IF(company_name = symbol, VALUES(company_name), company_name),
                exchange = COALESCE(exchange, VALUES(exchange))
            """,
            (symbol, company_name, exchange),
            settings,
        )
    except DatabaseError:
        raise
    row = get_stock_by_symbol(symbol, settings)
    if row is None:
        raise DatabaseError("Could not create the stock record.")
    return row


def count_stocks(settings: Settings | None = None) -> int:
    row = fetch_one("SELECT COUNT(*) AS count FROM stocks", settings=settings)
    return int(row["count"]) if row else 0


# ---------------------------------------------------------------------------
# Historical prices
# ---------------------------------------------------------------------------

# Analysis only uses completed daily sessions. The current day's provider bar can
# still be an in-progress (intraday) price, so it is excluded from all reads.
_COMPLETED_DAY = "trade_date < CURDATE()"


def get_price_bounds(stock_id: int, settings: Settings | None = None) -> dict | None:
    return fetch_one(
        f"""
        SELECT MIN(trade_date) AS first_date, MAX(trade_date) AS last_date,
               COUNT(*) AS row_count
        FROM stock_prices WHERE stock_id = %s AND {_COMPLETED_DAY}
        """,
        (stock_id,),
        settings,
    )


def get_prices(
    stock_id: int,
    start: str,
    end: str,
    settings: Settings | None = None,
) -> list[dict]:
    return fetch_all(
        f"""
        SELECT trade_date, open_price, high_price, low_price, close_price,
               volume, data_source
        FROM stock_prices
        WHERE stock_id = %s AND trade_date BETWEEN %s AND %s AND {_COMPLETED_DAY}
        ORDER BY trade_date ASC
        """,
        (stock_id, start, end),
        settings,
    )


def get_price_page(
    stock_id: int,
    start: str,
    end: str,
    limit: int,
    offset: int,
    settings: Settings | None = None,
) -> tuple[list[dict], int]:
    total_row = fetch_one(
        f"""
        SELECT COUNT(*) AS count FROM stock_prices
        WHERE stock_id = %s AND trade_date BETWEEN %s AND %s AND {_COMPLETED_DAY}
        """,
        (stock_id, start, end),
        settings,
    )
    rows = fetch_all(
        f"""
        SELECT trade_date, open_price, high_price, low_price, close_price,
               volume, data_source
        FROM stock_prices
        WHERE stock_id = %s AND trade_date BETWEEN %s AND %s AND {_COMPLETED_DAY}
        ORDER BY trade_date ASC
        LIMIT %s OFFSET %s
        """,
        (stock_id, start, end, limit, offset),
        settings,
    )
    return rows, int(total_row["count"]) if total_row else 0


def get_latest_prices(stock_id: int, count: int = 2, settings: Settings | None = None) -> list[dict]:
    return fetch_all(
        f"""
        SELECT trade_date, open_price, high_price, low_price, close_price,
               volume, data_source
        FROM stock_prices
        WHERE stock_id = %s AND {_COMPLETED_DAY}
        ORDER BY trade_date DESC
        LIMIT %s
        """,
        (stock_id, max(1, min(count, 10))),
        settings,
    )


def upsert_prices(
    stock_id: int,
    rows: Iterable[Sequence[Any]],
    source: str = "yfinance",
    settings: Settings | None = None,
) -> int:
    """Insert or update OHLCV rows.

    Each row is ``(trade_date, open, high, low, close, volume)``.
    Existing rows are preserved when the incoming row is sample data,
    so a sample fallback can never overwrite retrieved market data.
    """
    if source not in {"twelve_data", "yfinance", "sample"}:
        raise DatabaseError("Unknown data source.")
    values = [
        (stock_id, trade_date, open_p, high_p, low_p, close_p, volume, source)
        for trade_date, open_p, high_p, low_p, close_p, volume in rows
    ]
    if not values:
        return 0

    sql = """
        INSERT INTO stock_prices
            (stock_id, trade_date, open_price, high_price, low_price,
             close_price, volume, data_source)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        ON DUPLICATE KEY UPDATE
            open_price = IF(VALUES(data_source) IN ('twelve_data', 'yfinance') OR data_source = 'sample',
                            VALUES(open_price), open_price),
            high_price = IF(VALUES(data_source) IN ('twelve_data', 'yfinance') OR data_source = 'sample',
                            VALUES(high_price), high_price),
            low_price = IF(VALUES(data_source) IN ('twelve_data', 'yfinance') OR data_source = 'sample',
                            VALUES(low_price), low_price),
            close_price = IF(VALUES(data_source) IN ('twelve_data', 'yfinance') OR data_source = 'sample',
                             VALUES(close_price), close_price),
            volume = IF(VALUES(data_source) IN ('twelve_data', 'yfinance') OR data_source = 'sample',
                        VALUES(volume), volume),
            data_source = IF(VALUES(data_source) IN ('twelve_data', 'yfinance'), VALUES(data_source), data_source)
    """
    # Chunk to keep every statement comfortably below MySQL limits.
    total = 0
    for index in range(0, len(values), 500):
        total += execute_many(sql, values[index:index + 500], settings)
    return total


def delete_prices(stock_id: int, settings: Settings | None = None) -> None:
    """Remove all stored prices for one stock (used only by tests)."""
    execute("DELETE FROM stock_prices WHERE stock_id = %s", (stock_id,), settings)


# ---------------------------------------------------------------------------
# Watchlist (single-user version)
# ---------------------------------------------------------------------------

def get_watchlist(settings: Settings | None = None) -> list[dict]:
    return fetch_all(
        """
        WITH ranked AS (
            SELECT stock_id, trade_date, close_price, data_source,
                   ROW_NUMBER() OVER (PARTITION BY stock_id ORDER BY trade_date DESC) AS rn
            FROM stock_prices
            WHERE trade_date < CURDATE()
        )
        SELECT w.watchlist_id, s.stock_id, s.symbol, s.company_name, s.exchange,
               w.created_at AS added_at,
               MAX(CASE WHEN r.rn = 1 THEN r.trade_date END) AS trade_date,
               MAX(CASE WHEN r.rn = 1 THEN r.close_price END) AS close_price,
               MAX(CASE WHEN r.rn = 2 THEN r.close_price END) AS previous_close,
               MAX(CASE WHEN r.rn = 1 THEN r.data_source END) AS latest_source
        FROM watchlist w
        JOIN stocks s ON s.stock_id = w.stock_id
        LEFT JOIN ranked r ON r.stock_id = w.stock_id AND r.rn <= 2
        GROUP BY w.watchlist_id, s.stock_id, s.symbol, s.company_name,
                 s.exchange, w.created_at
        ORDER BY w.created_at DESC, s.symbol
        """,
        settings=settings,
    )


def add_to_watchlist(stock_id: int, settings: Settings | None = None) -> int:
    cfg = _resolve(settings)
    try:
        with cursor(cfg) as (conn, cur):
            try:
                cur.execute(
                    "INSERT INTO watchlist (stock_id) VALUES (%s)",
                    (stock_id,),
                )
                conn.commit()
                return cur.lastrowid
            except MySQLError as exc:
                conn.rollback()
                if getattr(exc, "errno", None) == 1062:
                    raise DuplicateWatchlistError("This stock is already in the watchlist.") from exc
                if getattr(exc, "errno", None) == 1452:
                    raise LookupError("Stock does not exist.") from exc
                raise DatabaseError("Could not add the stock to the watchlist.") from exc
    except MySQLError as exc:  # pragma: no cover - defensive
        raise DatabaseError("Could not add the stock to the watchlist.") from exc


def remove_from_watchlist(stock_id: int, settings: Settings | None = None) -> int:
    with cursor(settings) as (conn, cur):
        try:
            cur.execute("DELETE FROM watchlist WHERE stock_id = %s", (stock_id,))
            conn.commit()
            return cur.rowcount
        except MySQLError as exc:
            conn.rollback()
            raise DatabaseError("Could not remove the stock from the watchlist.") from exc


def count_watchlist(settings: Settings | None = None) -> int:
    row = fetch_one("SELECT COUNT(*) AS count FROM watchlist", settings=settings)
    return int(row["count"]) if row else 0
