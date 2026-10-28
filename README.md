# MarketLens — Stock Market Analysis System

A complete college Python project that combines a **Flask** backend, **MySQL 8** storage,
**Pandas/NumPy** statistics, **yfinance** historical prices, **Chart.js** charts and a
responsive **Bootstrap 5** dark-navy dashboard.

All charts and figures are generated from backend data. When the market-data provider is
unavailable, the app can use a bundled **sample snapshot** — it is always visibly labelled
and is never presented as live data.

> Historical data is for education only. This is **not investment advice**.

---

## 1. Features

| Feature | What it does |
|---|---|
| Dashboard | Tracked-stock count, latest close, daily change, period high/low, average volume, closing-price chart, volume chart, ticker/company search with autocomplete, stock selector and date-range filter |
| Stock analysis | Historical OHLCV table with pagination, average/high/low statistics, daily returns, 20/50-trading-day SMAs, sample volatility, price/SMA chart, returns chart |
| Comparison | 2–6 stocks, common date range, normalised performance (start = 100) or raw close, total return, average daily return, volatility, average volume, aligned common trading dates, methodology notes |
| Watchlist | Add/remove stocks, latest stored close and daily change, persistent in MySQL, duplicate prevention, shortcut to analysis |
| Reports | Filter stored records, paginated preview, server-generated prices CSV and analysis CSV, safe filenames |
| Data pipeline | yfinance download → validation/cleaning → MySQL upsert → cached reads → Pandas analysis |
| Offline demo | Bundled `data/sample_stock_data.csv` and a "Sample data" button; automatic fallback when the provider is unreachable |
| Error handling | JSON error bodies, HTTP status codes, loading/empty/error states, no stack traces or credentials sent to the browser |

Single-user watchlist only — there are no accounts or authentication, and the UI does not
claim otherwise.

---

## 2. Technology stack

- **Python 3.12.14** (tested in this build; 3.10+ should work with the pinned packages)
- **Flask 3.1.2**, Jinja templates, JSON APIs
- **MySQL 8.0.46** + `mysql-connector-python` 9.4.0
- **Pandas 2.3.3**, **NumPy 2.3.4**
- **yfinance 0.2.66** (provider availability and terms apply)
- **Bootstrap 5.3.3**, Bootstrap Icons, **Chart.js 4.4.7**, custom CSS/JS
- **pytest 8.4.2**

Frontend libraries are loaded from jsDelivr CDNs. The app itself must be served by Flask —
opening templates with `file://` will not work.

---

## 3. Project structure

```text
stock_market_analysis/
├── app.py                    # Flask app factory, pages, JSON APIs, CSV export
├── config.py                 # Environment-based settings
├── database.py               # Connections, parameterized queries, repositories
├── init_db.py                # Create DB, apply schema, seed companies (idempotent)
├── data_fetcher.py           # yfinance + sample CSV, cleaning, caching, upserts
├── analysis.py               # Pure Pandas/NumPy calculations
├── requirements.txt
├── pytest.ini
├── .env.example
├── .gitignore
├── README.md
├── database/
│   └── schema.sql
├── templates/
│   ├── base.html
│   ├── index.html
│   ├── stock_analysis.html
│   ├── compare.html
│   ├── watchlist.html
│   ├── reports.html
│   └── error.html
├── static/
│   ├── favicon.svg
│   ├── css/style.css
│   └── js/
│       ├── common.js
│       ├── dashboard.js
│       ├── stock_analysis.js
│       ├── compare.js
│       ├── watchlist.js
│       └── reports.js
├── data/
│   └── sample_stock_data.csv # clearly labelled offline snapshot
├── exports/
│   └── .gitkeep
└── tests/
    ├── conftest.py
    ├── test_analysis.py
    ├── test_database.py
    ├── test_fetcher.py
    └── test_routes.py
```

---

## 4. Windows PowerShell setup

### Step A — Open the project

In VS Code: **File → Open Folder →** `C:\Users\Charith\stockmarket\stock_market_analysis`.

Or from PowerShell:

```powershell
cd C:\Users\Charith\stockmarket\stock_market_analysis
code .
```

The same folder can be opened in OpenCode. Run every command below from the
`stock_market_analysis` folder.

### Step B — Create a virtual environment

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
```

If PowerShell blocks activation with an execution-policy error, use one of these safe options:

```powershell
# Option 1: allow scripts only for the current PowerShell process
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1

# Option 2: skip activation entirely
.\.venv\Scripts\python.exe --version
```

`py -m venv .venv` uses your default Python. This project was verified with Python 3.12.14.
If your default is a version the pinned packages do not support, install Python 3.12 and run:

```powershell
py -3.12 -m venv .venv
```

### Step C — Install dependencies

```powershell
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

### Step D — Configure MySQL

1. **Check the service** (this machine has `MySQL80`, running automatically):

   ```powershell
   Get-Service -Name '*mysql*' | Select-Object Name, Status, StartType
   ```

   Start it safely if it is stopped (may require an Administrator PowerShell):

   ```powershell
   Start-Service MySQL80
   ```

2. **Connect** with MySQL Workbench or the command-line client:

   ```powershell
   & 'C:\Program Files\MySQL\MySQL Server 8.0\bin\mysql.exe' -u root -p
   ```

3. **Optional: create a dedicated app user.** For a local college demo, using `root` also
   works. A dedicated user is better practice. Run once as an administrator user:

   ```sql
   CREATE DATABASE IF NOT EXISTS stock_market_db
     CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

   CREATE USER IF NOT EXISTS 'stock_app'@'localhost'
     IDENTIFIED BY 'choose-a-strong-local-password';

   GRANT SELECT, INSERT, UPDATE, DELETE, CREATE, ALTER, INDEX, REFERENCES
     ON stock_market_db.* TO 'stock_app'@'localhost';

   FLUSH PRIVILEGES;
   ```

   `init_db.py` needs the database to exist when the app user cannot create databases.
   For full automation, set `DB_ADMIN_USER` / `DB_ADMIN_PASSWORD` in `.env`; those are used
   only for `CREATE DATABASE`.

4. **Copy the environment template** and edit it privately:

   ```powershell
   Copy-Item .env.example .env
   notepad .env
   ```

   ```text
   DB_HOST=localhost
   DB_PORT=3306
   DB_USER=stock_app
   DB_PASSWORD=your-real-password
   DB_NAME=stock_market_db
   DB_ADMIN_USER=
   DB_ADMIN_PASSWORD=
   FLASK_SECRET_KEY=some-long-random-string
   FLASK_DEBUG=1
   FLASK_HOST=127.0.0.1
   FLASK_PORT=5000
   ```

   Never commit `.env`; it is already in `.gitignore`. Never put credentials in JavaScript
   or `app.py`.

5. **Initialise the database** (creates tables and the 10 starting companies; safe to re-run):

   ```powershell
   .\.venv\Scripts\python.exe init_db.py
   ```

   Expected output ends with `Success. Database 'stock_market_db' is ready.`

6. **Verify** in Workbench or the CLI:

   ```sql
   USE stock_market_db;
   SHOW TABLES;
   SELECT symbol, company_name, exchange FROM stocks ORDER BY symbol;
   DESCRIBE stock_prices;
   ```

### Step E — Start Flask

```powershell
.\.venv\Scripts\python.exe app.py
```

Open **http://127.0.0.1:5000/** (the actual host/port are printed on startup and controlled
by `FLASK_HOST` / `FLASK_PORT`).

If your database is empty and you want an immediate offline demo, click **Sample data** on
the dashboard. It loads the bundled snapshot into MySQL. When online, clicking **Refresh**
retrieves historical data from yfinance.

### Step F — Run the tests

```powershell
.\.venv\Scripts\python.exe -m pytest
```

Tests that require MySQL use an isolated database named `stock_market_db_test` and skip
cleanly if MySQL is unavailable. They never clear `stock_market_db`.

---

## 5. Database design

### `stocks`

| Column | Type | Notes |
|---|---|---|
| `stock_id` | INT | PK, auto-increment |
| `symbol` | VARCHAR(20) | unique, not null |
| `company_name` | VARCHAR(150) | not null |
| `exchange` | VARCHAR(20) | nullable |
| `created_at` | TIMESTAMP | default current timestamp |

### `stock_prices`

| Column | Type | Notes |
|---|---|---|
| `price_id` | BIGINT | PK, auto-increment |
| `stock_id` | INT | FK → `stocks.stock_id`, `ON DELETE CASCADE` |
| `trade_date` | DATE | not null |
| `open_price` … `close_price` | DECIMAL(15,4) | nullable |
| `volume` | BIGINT | nullable |
| `data_source` | VARCHAR(20) | `yfinance` or `sample` (added to distinguish sources) |
| `created_at` | TIMESTAMP | default current timestamp |

Unique `(stock_id, trade_date)` prevents duplicates. Indexes support stock/date and
date-only queries. InnoDB + utf8mb4.

### `watchlist`

| Column | Type | Notes |
|---|---|---|
| `watchlist_id` | INT | PK, auto-increment |
| `stock_id` | INT | FK → `stocks.stock_id`, unique (single-user version) |
| `created_at` | TIMESTAMP | default current timestamp |

`schema.sql` is idempotent (`CREATE ... IF NOT EXISTS`) and never drops data.

---

## 6. Data sources and caching

1. **Retrieved data** — yfinance historical OHLCV, stored with `data_source = 'yfinance'`.
2. **Sample data** — `data/sample_stock_data.csv`, a two-year snapshot captured for offline
   demonstrations, stored with `data_source = 'sample'`. The dashboard and API show a
   "Sample data" badge and warning whenever it is used.
3. **Caching** — if stored rows already cover the requested range (allowing for weekends),
   no provider request is made.
4. **Fallback** — on provider timeout/network failure, sample rows are used if available;
   otherwise previously stored rows are shown with an out-of-date warning. An invalid ticker
   is never silently replaced with another stock.
5. **Source protection** — sample rows can fill missing dates but can never overwrite rows
   retrieved from yfinance. A later yfinance fetch can upgrade sample rows.
6. **Completed sessions only** — the current day's provider bar can still be an in-progress
   intraday price, so it is not stored or analysed as a daily close. Read queries also exclude
   the current date; the latest analysis date is therefore the last completed session.

Supported example symbols: `RELIANCE.NS`, `TCS.NS`, `INFY.NS`, `HDFCBANK.NS`,
`ICICIBANK.NS`, `AAPL`, `MSFT`, `GOOGL`, `AMZN`, `NVDA`. yfinance also supports other valid
tickers; new symbols are added to the database only after a successful retrieval.

---

## 7. Statistical methodology

- **Daily return** = `(current close − previous close) / previous close × 100`.
  The first row is `null`; zero or missing previous closes become `null`.
- **SMA 20 / SMA 50** = simple rolling means over 20/50 trading observations.
  The result is `null` until enough observations exist.
- **Volatility** = **sample** standard deviation (`ddof=1`) of daily percentage returns.
  It is **not annualized**.
- **Total return** = `(last close − first close) / first close × 100`.
- **Comparison statistics** use only dates on which every selected stock traded (inner
  alignment). The chart uses the union of dates and forward-fills each series for display.
- **Normalisation** = each close divided by that stock's first available close × 100.
- Raw close levels are not treated as comparable investment performance, and INR/USD
  currencies are not mixed in the normalised view.

All NumPy/Pandas values (`numpy.int64`, `NaN`, `NaT`, etc.) are converted to JSON-safe
values before leaving the backend.

---

## 8. API reference

Base URL: `http://127.0.0.1:5000`. All responses are JSON unless the endpoint is a CSV export.
Dates must be `YYYY-MM-DD`. Default range is the last 365 days (180 days for comparison).

| Method | Endpoint | Purpose |
|---|---|---|
| GET | `/api/health` | Database health check |
| GET | `/api/stocks` | All tracked stocks with stored row counts |
| GET | `/api/stocks/search?q=...` | Search by symbol or company name |
| GET | `/api/stocks/<symbol>/history?start=&end=&page=&per_page=&refresh=` | Paginated stored OHLCV records |
| GET | `/api/stocks/<symbol>/analysis?start=&end=&refresh=` | Full statistical analysis + series |
| GET | `/api/dashboard?symbol=&start=&end=` | Dashboard cards, tracked list, analysis |
| POST | `/api/stocks/refresh` | JSON `{symbol, start, end, use_sample?}`; force a refresh |
| POST | `/api/demo/load` | Load the bundled sample snapshot into MySQL |
| GET | `/api/compare?symbols=AAPL,MSFT&start=&end=` | Compare 2–6 stocks |
| GET | `/api/watchlist` | Saved stocks with latest stored close/change |
| POST | `/api/watchlist` | JSON `{stock_id}` or `{symbol}` |
| DELETE | `/api/watchlist/<stock_id>` | Remove a saved stock |
| GET | `/api/reports?symbol=&start=&end=&page=&per_page=` | Paginated report preview |
| GET | `/api/reports/export?symbol=&start=&end=&type=prices\|analysis` | Download CSV |

**Success examples**

```json
{
  "symbol": "AAPL",
  "latest": {"trade_date": "2026-10-23", "close": 347.73, "change_percent": -0.1407},
  "stats": {"average_close": 290.13, "observations": 250},
  "source": "yfinance",
  "is_sample": false
}
```

**Error shape**

```json
{
  "error": {
    "code": "invalid_date",
    "message": "'start' must be a valid date in YYYY-MM-DD format."
  }
}
```

Common statuses: `400` validation, `404` stock/data not found, `409` duplicate watchlist,
`422` insufficient comparison data, `503` database/provider unavailable, `504` provider
timeout, `500` unexpected (logged server-side, safe message returned).

`/api/reports/export` returns `Content-Disposition: attachment` with a server-generated
filename such as `prices_AAPL_2025-01-01_2025-12-31.csv`. The CSV contains only selected
database records/calculated values.

---

## 9. Demonstration walkthrough (viva)

1. Run `init_db.py`, then `app.py`; open the dashboard.
2. The dashboard loads Apple's last year (if stored) or retrieves it from yfinance.
   Point out the data-source badge.
3. Use the **Search stock** box: type `MSFT` or `Apple` and press **Apply**; the chart and
   cards update. An unknown term such as `ZZZZ` shows a clear warning and leaves the
   current stock selected. You can also switch stocks from the dropdown.
4. Open **Stock Analysis**; scroll to show average/high/low, SMAs, volatility, daily-return
   chart and the paginated OHLCV table.
5. Open **Compare**; select `AAPL` + `MSFT`, choose dates, run the comparison. Toggle
   **Normalised (100)** / **Raw close** and explain the methodology.
6. Open **Watchlist**; add a stock, refresh the page/browser to show it persists in MySQL,
   then remove it.
7. Open **Reports**; preview rows and download both CSV files.
8. Stop the internet (or the provider) and click **Sample data** / refresh to demonstrate
   the clearly labelled offline fallback.

Useful MySQL checks:

```sql
SELECT COUNT(*) AS stocks FROM stocks;
SELECT s.symbol, COUNT(*) AS rows_stored, MAX(p.trade_date) AS latest
FROM stocks s LEFT JOIN stock_prices p ON p.stock_id = s.stock_id
GROUP BY s.stock_id, s.symbol ORDER BY s.symbol;
SELECT * FROM watchlist;
```

---

## 10. Testing performed in this build

Environment: Windows, MySQL 8.0.46 running as `MySQL80`, Python 3.12.14 virtual environment,
Chrome headless (Selenium) for browser checks.

```text
$ .\.venv\Scripts\python.exe -m pytest
................................                                         [100%]
32 passed in 13.19s
```

Covered:

- daily returns, zero/missing bases, SMA windows and insufficient data
- sample-standard-deviation volatility
- basic statistics, latest change, total return, empty datasets
- JSON serialization of NumPy/NaN values
- comparison normalisation, common-date alignment, invalid comparison input
- completed-session filtering (current day excluded) and weekend/holiday coverage tolerance
- MySQL connection, tables, stock insert/lookup/deduplication
- price upsert, update-on-duplicate, sample never overwriting retrieved data
- watchlist insert, duplicate rejection, removal, FK rejection
- sample demo loading and sample labelling
- Flask pages, stock/search/history/analysis/dashboard APIs
- input validation (dates, symbols, pagination, comparison count)
- comparison missing-data behaviour
- CSV prices/analysis content, headers, filenames, empty-result handling
- database-outage JSON error without credential leakage
- browser checks: charts render/update, ticker/company dashboard search (valid, company-name
  and invalid terms), stock switch, watchlist add/remove, mobile sidebar, no severe console
  errors

Limitations: automated tests run against `stock_market_db_test`; browser testing was
headless Chrome only. yfinance is an external service — tests avoid network calls by using
stored data.

---

## 11. Troubleshooting

| Symptom | Fix |
|---|---|
| `Could not reach MySQL. Is the MySQL80 service running?` | `Get-Service MySQL80`; `Start-Service MySQL80` (admin shell if required); confirm port 3306 with `Test-NetConnection localhost -Port 3306`. |
| `MySQL access denied ... DB_USER/DB_PASSWORD` | Re-check `.env`; ensure the user exists and has privileges on `stock_market_db`; if the password has special characters, quote it correctly in `.env`. |
| `Unknown database 'stock_market_db'` | Run `init_db.py`, or create the database in Workbench first. |
| `ModuleNotFoundError` / missing Flask/pandas | Activate the venv and run `python -m pip install -r requirements.txt`. Remember `python` may not be on PATH — use `.\.venv\Scripts\python.exe`. |
| `Activate.ps1 cannot be loaded` | Use `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass`, or run `.\.venv\Scripts\python.exe` directly. |
| `python` opens the Microsoft Store | Use `py` or the full venv path shown above. |
| Provider timeout / network error | Check internet and provider status; use **Sample data** for the offline demo. Invalid symbols are not substituted. |
| Invalid ticker / empty charts | Check the exact symbol and suffix (`.NS` for NSE, `.BO` for BSE, plain US ticker). Use **Refresh**; verify rows exist in `stock_prices`. |
| Port 5000 already in use | Stop the other process (`Get-NetTCPConnection -LocalPort 5000`), or set `FLASK_PORT=5001` in `.env`. |
| Chart is empty after choosing dates | The selected period may have no trading days or no stored data. Widen the range, run Refresh, or load sample data. |
| CSV export returns 404 | No stored records match the filters; run a preview/refresh first. |
| MySQL Workbench not installed | Not required. Use Workbench if available, or the MySQL CLI commands above. |

---

## 12. Security and scope notes

- All SQL values are parameterized; database identifiers are validated and quoted.
- Credentials live only in `.env` (git-ignored) and are never sent to the frontend.
- Stack traces are logged server-side; API clients receive safe messages.
- CSV filenames are generated from a validated symbol and validated dates — no
  user-controlled filesystem paths.
- The app runs on Flask's development server for local use. For a public deployment, use a
  production WSGI server, HTTPS, authentication and proper MySQL grants.
- This is a single-user, educational application. It does not provide live prices,
  brokerage integration, or investment recommendations.
- yfinance data availability, delays and usage terms are controlled by the provider.

---

## 13. Quick reference

```powershell
cd C:\Users\Charith\stockmarket\stock_market_analysis
.\.venv\Scripts\python.exe init_db.py
.\.venv\Scripts\python.exe app.py
# open http://127.0.0.1:5000/
.\.venv\Scripts\python.exe -m pytest
```
