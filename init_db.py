"""Create stock_market_db, apply the schema, and seed initial company records.

This script is idempotent: it never drops, truncates, or resets tables.
Run it from the project folder:

    .\\.venv\\Scripts\\python.exe init_db.py
"""

from __future__ import annotations

import re
import sys

import mysql.connector
from mysql.connector import Error as MySQLError

import database
from config import BASE_DIR, load_settings
from data_fetcher import SEED_STOCKS


SCHEMA_FILE = BASE_DIR / "database" / "schema.sql"


def split_sql_statements(sql_text: str) -> list[str]:
    """Split a simple SQL script into statements, ignoring comments."""
    without_comments = re.sub(r"--[^\n]*", "", sql_text)
    without_comments = re.sub(r"/\*.*?\*/", "", without_comments, flags=re.DOTALL)
    statements = []
    for chunk in without_comments.split(";"):
        statement = chunk.strip()
        if statement:
            statements.append(statement)
    return statements


def apply_schema(settings) -> int:
    if not SCHEMA_FILE.exists():
        raise FileNotFoundError(f"Schema file not found: {SCHEMA_FILE}")
    statements = split_sql_statements(SCHEMA_FILE.read_text(encoding="utf-8"))
    table_statements = [
        statement for statement in statements
        if not statement.upper().startswith(("CREATE DATABASE", "USE "))
    ]
    conn = database.get_connection(settings)
    cur = conn.cursor()
    applied = 0
    try:
        for statement in table_statements:
            cur.execute(statement)
            applied += 1
        conn.commit()
    finally:
        cur.close()
        conn.close()
    return applied


def seed_stocks(settings) -> tuple[int, int]:
    created = 0
    existing = 0
    for item in SEED_STOCKS:
        before = database.get_stock_by_symbol(item["symbol"], settings)
        database.get_or_create_stock(
            item["symbol"], item["company_name"], item["exchange"], settings
        )
        if before is None:
            created += 1
        else:
            existing += 1
    return created, existing


def main() -> int:
    settings = load_settings()
    print("Stock Market Analysis System - database initialisation")
    print(f"MySQL host : {settings.db_host}:{settings.db_port}")
    print(f"Database   : {settings.db_name}")
    print(f"User       : {settings.db_user}")
    print()

    try:
        print("1/4 Creating the database if it does not exist...")
        database.create_database(settings)
        database.configure(settings)

        print("2/4 Applying database/schema.sql (non-destructive)...")
        applied = apply_schema(settings)
        print(f"    {applied} table statement(s) applied.")

        print("3/4 Inserting initial company records...")
        created, existing = seed_stocks(settings)
        print(f"    {created} created, {existing} already present.")

        print("4/4 Verifying tables...")
        for table in ("stocks", "stock_prices", "watchlist"):
            if not database.table_exists(table, settings):
                raise RuntimeError(f"Table '{table}' was not created.")
            print(f"    OK  {table}")

        print()
        print(f"Success. Database '{settings.db_name}' is ready.")
        print(f"Tracked companies: {database.count_stocks(settings)}")
        print("Next: start the app with  .\\.venv\\Scripts\\python.exe app.py")
        print("Then open http://127.0.0.1:5000/")
        return 0
    except MySQLError as exc:
        print(f"\nMySQL error: {exc.msg}", file=sys.stderr)
        return 1
    except (database.DatabaseError, RuntimeError, FileNotFoundError) as exc:
        print(f"\nInitialisation failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
