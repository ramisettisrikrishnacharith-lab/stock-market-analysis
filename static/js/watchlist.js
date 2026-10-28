/* Watchlist page */
(function () {
  "use strict";

  const $ = (id) => document.getElementById(id);

  document.addEventListener("DOMContentLoaded", init);

  async function init() {
    $("watchlistAddForm").addEventListener("submit", addStock);
    $("refreshWatchlist").addEventListener("click", reload);

    try {
      const stocks = await StockApp.getStocks();
      StockApp.populateStockSelect($("watchlistSelect"), stocks.stocks);
      await loadWatchlist();
    } catch (error) {
      StockApp.showAlert(error.message);
    }
  }

  async function reload() {
    const button = $("refreshWatchlist");
    StockApp.setBusy(button, true, "Reloading…");
    try {
      await loadWatchlist();
      StockApp.hideAlert();
    } catch (error) {
      StockApp.showAlert(error.message);
    } finally {
      StockApp.setBusy(button, false);
    }
  }

  async function loadWatchlist() {
    $("watchlistLoading").classList.add("show");
    StockApp.setPageLoading(true);
    try {
      const data = await StockApp.api("/api/watchlist");
      render(data);
    } finally {
      $("watchlistLoading").classList.remove("show");
      StockApp.setPageLoading(false);
    }
  }

  function render(data) {
    const items = data.items || [];
    $("watchlistCount").textContent = StockApp.formatNumber(items.length);
    const withData = items.filter((item) => item.close_price !== null && item.close_price !== undefined).length;
    $("watchlistWithData").textContent = StockApp.formatNumber(withData);

    const latestDates = items.map((item) => item.trade_date).filter(Boolean).sort();
    $("watchlistLastDate").textContent = latestDates.length
      ? StockApp.formatDate(latestDates[latestDates.length - 1]) : "No prices yet";

    const tbody = $("watchlistTableBody");
    tbody.replaceChildren();
    const isEmpty = items.length === 0;
    $("watchlistTableWrap").classList.toggle("d-none", isEmpty);
    StockApp.setEmptyState($("watchlistEmpty"), isEmpty, "Your watchlist is empty",
      "Choose a stock above and add it. Latest stored prices will appear here automatically.");

    items.forEach((item) => {
      const row = document.createElement("tr");

      const stockCell = document.createElement("td");
      const symbol = document.createElement("div");
      symbol.className = "table-symbol";
      symbol.textContent = item.symbol;
      const company = document.createElement("div");
      company.className = "table-company";
      company.textContent = `${item.company_name || ""}${item.exchange ? " · " + item.exchange : ""}`;
      stockCell.append(symbol, company);
      row.appendChild(stockCell);

      appendCell(row, item.trade_date ? StockApp.formatDate(item.trade_date) : "—", "text-muted");
      appendCell(row, StockApp.formatMoney(item.close_price, item.symbol), "text-end fw-semibold");

      const changeCell = document.createElement("td");
      changeCell.className = `text-end ${StockApp.trendClass(item.change_percent)}`;
      changeCell.textContent = StockApp.formatPercent(item.change_percent);
      changeCell.title = item.change === null || item.change === undefined
        ? "Not enough stored prices" : `${StockApp.formatSignedMoney(item.change, item.symbol)} vs previous close`;
      row.appendChild(changeCell);

      const sourceCell = document.createElement("td");
      const source = item.data_source;
      const badge = document.createElement("span");
      badge.className = `source-badge ${source === "sample" ? "source-sample" : source === "yfinance" ? "source-yfinance" : "source-unknown"}`;
      badge.textContent = source === "sample" ? "Sample" : source === "yfinance" ? "Retrieved" : "No data";
      sourceCell.appendChild(badge);
      row.appendChild(sourceCell);

      appendCell(row, StockApp.formatDateTime(item.added_at), "text-muted small");

      const actionCell = document.createElement("td");
      actionCell.className = "text-end text-nowrap";
      const analysisLink = document.createElement("a");
      analysisLink.className = "btn btn-ghost btn-sm";
      analysisLink.href = `/analysis?symbol=${encodeURIComponent(item.symbol)}`;
      analysisLink.title = "Open full analysis";
      analysisLink.innerHTML = '<i class="bi bi-graph-up"></i>';
      const removeButton = document.createElement("button");
      removeButton.type = "button";
      removeButton.className = "btn btn-ghost btn-sm text-danger";
      removeButton.title = "Remove from watchlist";
      removeButton.innerHTML = '<i class="bi bi-trash3"></i>';
      removeButton.addEventListener("click", () => removeStock(item));
      actionCell.append(analysisLink, removeButton);
      row.appendChild(actionCell);

      tbody.appendChild(row);
    });
  }

  function appendCell(row, text, className = "") {
    const cell = document.createElement("td");
    if (className) cell.className = className;
    cell.textContent = text;
    row.appendChild(cell);
  }

  async function addStock(event) {
    event.preventDefault();
    const stockId = $("watchlistSelect").value;
    if (!stockId) {
      StockApp.showAlert("Choose a stock to add.");
      return;
    }
    const button = $("addWatchlistBtn");
    StockApp.setBusy(button, true, "Adding…");
    try {
      const result = await StockApp.api("/api/watchlist", {
        method: "POST",
        body: { symbol: stockId },
      });
      await loadWatchlist();
      StockApp.showAlert(result.message, "success");
    } catch (error) {
      StockApp.showAlert(error.message, error.status === 409 ? "info" : "danger");
    } finally {
      StockApp.setBusy(button, false);
    }
  }

  async function removeStock(item) {
    if (!window.confirm(`Remove ${item.symbol} from your watchlist?`)) return;
    try {
      const result = await StockApp.api(`/api/watchlist/${item.stock_id}`, { method: "DELETE" });
      await loadWatchlist();
      StockApp.showAlert(result.message, "success");
    } catch (error) {
      StockApp.showAlert(error.message);
    }
  }
})();
