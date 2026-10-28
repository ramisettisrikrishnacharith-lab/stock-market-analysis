"""Flask route, API, validation, and CSV export tests."""

from __future__ import annotations

import csv
import io

import pytest

import analysis
import data_fetcher
import database

RANGE = "start=2025-01-01&end=2025-06-30"


def test_pages_render(seeded_client):
    client, _stock_a, _stock_b = seeded_client
    for path in ("/", "/analysis", "/compare", "/watchlist", "/reports"):
        response = client.get(path)
        assert response.status_code == 200
        assert b"MarketLens" in response.data


def test_stock_catalogue_and_search(seeded_client):
    client, stock_a, _stock_b = seeded_client
    response = client.get("/api/stocks")
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["count"] == 2
    assert {item["symbol"] for item in payload["stocks"]} == {"TSTA", "TSTB"}

    search = client.get("/api/stocks/search?q=alpha")
    assert search.status_code == 200
    results = search.get_json()["results"]
    assert len(results) == 1
    assert results[0]["stock_id"] == stock_a["stock_id"]
    assert client.get("/api/stocks/search").status_code == 400


def test_dashboard_and_history_from_stored_data(seeded_client):
    client, _stock_a, _stock_b = seeded_client
    dashboard = client.get(f"/api/dashboard?symbol=TSTA&{RANGE}")
    assert dashboard.status_code == 200
    data = dashboard.get_json()
    assert data["stats"]["observations"] > 100
    assert data["source"] == "yfinance"
    assert data["is_sample"] is False
    assert len(data["series"]["dates"]) == len(data["series"]["close"])
    assert data["latest"]["close"] is not None

    history = client.get(f"/api/stocks/TSTA/history?{RANGE}&page=1&per_page=10")
    assert history.status_code == 200
    page = history.get_json()
    assert page["total"] > 100
    assert len(page["rows"]) == 10
    assert page["total_pages"] > 1
    assert page["rows"][0]["data_source"] == "yfinance"


def test_analysis_endpoint_and_json_shape(seeded_client):
    client, _stock_a, _stock_b = seeded_client
    response = client.get(f"/api/stocks/TSTA/analysis?{RANGE}")
    assert response.status_code == 200
    data = response.get_json()
    assert data["symbol"] == "TSTA"
    assert data["moving_averages"]["sma20"] is not None
    assert data["moving_averages"]["sma50"] is not None
    assert data["daily_returns"]["volatility_percent"] is not None
    assert data["daily_returns"]["method"].startswith("Sample standard deviation")
    for key in ("stats", "latest", "series", "moving_averages", "total_return_percent"):
        assert key in data


def test_validation_errors(seeded_client):
    client, _stock_a, _stock_b = seeded_client
    assert client.get("/api/stocks/TSTA/analysis?start=not-a-date").status_code == 400
    mismatch = client.get("/api/stocks/TSTA/history?start=2025-06-01&end=2025-01-01")
    assert mismatch.status_code == 400
    assert mismatch.get_json()["error"]["code"] == "invalid_date_range"
    assert client.get("/api/stocks/BAD%20SYMBOL/history").status_code == 400
    assert client.get(f"/api/stocks/TSTA/history?{RANGE}&per_page=abc").status_code == 400
    assert client.get("/api/compare?symbols=TSTA").status_code == 400
    assert client.get("/api/compare").status_code == 400
    assert client.get("/api/reports/export?symbol=TSTA&type=evil").status_code == 400


def test_watchlist_api_flow(seeded_client):
    client, stock_a, _stock_b = seeded_client
    add = client.post("/api/watchlist", json={"symbol": "TSTA"})
    assert add.status_code == 201

    duplicate = client.post("/api/watchlist", json={"symbol": "TSTA"})
    assert duplicate.status_code == 409

    listing = client.get("/api/watchlist")
    assert listing.status_code == 200
    payload = listing.get_json()
    assert payload["count"] == 1
    item = payload["items"][0]
    assert item["stock_id"] == stock_a["stock_id"]
    assert item["close_price"] is not None
    assert item["change_percent"] is not None
    assert item["data_source"] == "yfinance"

    missing = client.post("/api/watchlist", json={"stock_id": 999999})
    assert missing.status_code == 404
    assert client.post("/api/watchlist", json={}).status_code == 400

    removed = client.delete(f"/api/watchlist/{stock_a['stock_id']}")
    assert removed.status_code == 200
    assert client.get("/api/watchlist").get_json()["count"] == 0
    assert client.delete(f"/api/watchlist/{stock_a['stock_id']}").status_code == 404


def test_comparison_endpoint(seeded_client):
    client, _stock_a, _stock_b = seeded_client
    response = client.get(f"/api/compare?symbols=TSTA,TSTB&{RANGE}")
    assert response.status_code == 200
    data = response.get_json()
    assert data["symbols"] == ["TSTA", "TSTB"]
    assert len(data["dates"]) > 100
    assert data["methodology"]["common_dates"] > 100
    assert data["series"]["TSTA"]["normalized"][0] == 100
    assert data["stats"]["TSTA"]["total_return_percent"] is not None
    assert data["stats"]["TSTB"]["volatility_percent"] is not None
    assert len(data["metadata"]) == 2


def test_comparison_handles_missing_data(seeded_client, monkeypatch):
    client, _stock_a, _stock_b = seeded_client

    def unavailable(*_args, **_kwargs):
        raise data_fetcher.MarketDataError("No historical data available.", code="no_data", status=404)

    monkeypatch.setattr(data_fetcher, "ensure_history", unavailable)
    response = client.get(f"/api/compare?symbols=TSTA,TSTB&{RANGE}")
    assert response.status_code == 422
    assert response.get_json()["error"]["code"] == "comparison_unavailable"


def test_csv_export_prices_and_analysis(seeded_client):
    client, _stock_a, _stock_b = seeded_client
    response = client.get(f"/api/reports/export?symbol=TSTA&{RANGE}&type=prices")
    assert response.status_code == 200
    disposition = response.headers["Content-Disposition"]
    assert 'filename="prices_TSTA_2025-01-01_2025-06-30.csv"' in disposition
    rows = list(csv.reader(io.StringIO(response.data.decode("utf-8-sig"))))
    assert rows[0] == ["Date", "Open", "High", "Low", "Close", "Volume", "Data source"]
    assert len(rows) > 100
    assert rows[1][6] == "yfinance"

    analysis_response = client.get(f"/api/reports/export?symbol=TSTA&{RANGE}&type=analysis")
    assert analysis_response.status_code == 200
    text = analysis_response.data.decode("utf-8-sig")
    assert "Stock Market Analysis Report" in text
    assert "Symbol,TSTA" in text
    assert "Daily return volatility %" in text
    assert "Date,Close,Daily return %,SMA 20,SMA 50,Volume" in text


def test_demo_load_and_sample_labelling(seeded_client):
    client, _stock_a, _stock_b = seeded_client
    response = client.post("/api/demo/load")
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["is_sample"] is True
    assert payload["rows_written"] > 0
    assert "AAPL" in payload["loaded_symbols"]

    analysis_response = client.get("/api/stocks/AAPL/analysis?start=2025-01-01&end=2026-10-23")
    assert analysis_response.status_code == 200
    data = analysis_response.get_json()
    assert data["source"] == "sample"
    assert data["is_sample"] is True
    assert data["stats"]["observations"] > 100


def test_export_rejects_empty_result(seeded_client, monkeypatch):
    client, _stock_a, _stock_b = seeded_client
    empty = data_fetcher.HistoryResult(
        symbol="TSTA",
        frame=analysis.prepare_frame([]),
        source="yfinance",
        is_sample=False,
    )
    monkeypatch.setattr(data_fetcher, "ensure_history", lambda *a, **k: empty)
    response = client.get(f"/api/reports/export?symbol=TSTA&start=2020-01-01&end=2020-12-31&type=prices")
    assert response.status_code == 404


def test_database_outage_returns_json_error(seeded_client, monkeypatch):
    client, _stock_a, _stock_b = seeded_client

    def unavailable(*_args, **_kwargs):
        raise database.DatabaseError("Database unavailable for testing.")

    monkeypatch.setattr(database, "list_stocks", unavailable)
    response = client.get("/api/stocks")
    assert response.status_code == 503
    payload = response.get_json()
    assert payload["error"]["code"] == "database_unavailable"
    assert "password" not in response.get_data(as_text=True).lower()


def test_api_404_is_json(seeded_client):
    client, _stock_a, _stock_b = seeded_client
    response = client.get("/api/does-not-exist")
    assert response.status_code == 404
    assert response.is_json
