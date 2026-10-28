/* Stock analysis page */
(function () {
  "use strict";

  const $ = (id) => document.getElementById(id);
  let priceChart = null;
  let returnsChart = null;
  let currentPage = 1;
  let currentSymbol = null;
  let loadSequence = 0;

  document.addEventListener("DOMContentLoaded", init);

  async function init() {
    StockApp.setDefaultRange($("analysisStart"), $("analysisEnd"), 365);
    const params = new URLSearchParams(window.location.search);
    if (params.get("start")) $("analysisStart").value = params.get("start");
    if (params.get("end")) $("analysisEnd").value = params.get("end");

    $("analysisFilter").addEventListener("submit", (event) => {
      event.preventDefault();
      if (!validateDates()) return;
      loadAll();
    });
    $("analysisStock").addEventListener("change", () => {
      if (!validateDates()) return;
      loadAll();
    });
    $("refreshAnalysis").addEventListener("click", refreshStock);
    $("tablePerPage").addEventListener("change", () => loadTable(1, true));

    try {
      const result = await StockApp.getStocks();
      if (!result.stocks.length) {
        StockApp.showAlert("No stocks are configured. Run init_db.py first.");
        return;
      }
      StockApp.populateStockSelect($("analysisStock"), result.stocks, params.get("symbol"));
      currentSymbol = $("analysisStock").value;
      const requestedPage = Number(params.get("page") || 1);
      currentPage = Number.isFinite(requestedPage) && requestedPage > 0 ? requestedPage : 1;
      await loadAll(currentPage);
    } catch (error) {
      StockApp.showAlert(error.message);
    }
  }

  function validateDates() {
    const start = $("analysisStart").value;
    const end = $("analysisEnd").value;
    if (!start || !end) {
      StockApp.showAlert("Choose both a start date and an end date.");
      return false;
    }
    if (start > end) {
      StockApp.showAlert("The start date must be on or before the end date.");
      return false;
    }
    return true;
  }

  function filters() {
    return {
      symbol: $("analysisStock").value,
      start: $("analysisStart").value,
      end: $("analysisEnd").value,
    };
  }

  async function loadAll(page = 1) {
    const options = filters();
    if (!options.symbol) return;
    currentSymbol = options.symbol;
    const sequence = ++loadSequence;
    StockApp.hideAlert();
    $("analysisLoading").classList.add("show");
    StockApp.setPageLoading(true);

    try {
      const query = new URLSearchParams({ start: options.start, end: options.end });
      const analysis = await StockApp.api(`/api/stocks/${encodeURIComponent(options.symbol)}/analysis?${query}`);
      if (sequence !== loadSequence) return;
      renderAnalysis(analysis);
      currentPage = page;
      await loadTable(page, false, sequence);
      updateUrl(page);
    } catch (error) {
      if (sequence !== loadSequence) return;
      StockApp.showAlert(error.message);
      $("analysisWarning").classList.add("d-none");
      renderEmpty(error.message);
    } finally {
      if (sequence === loadSequence) {
        $("analysisLoading").classList.remove("show");
        StockApp.setPageLoading(false);
      }
    }
  }

  function updateUrl(page) {
    const options = filters();
    const params = new URLSearchParams({
      symbol: options.symbol, start: options.start, end: options.end,
    });
    if (page > 1) params.set("page", page);
    window.history.replaceState({}, "", `${window.location.pathname}?${params.toString()}`);
  }

  function renderAnalysis(data) {
    StockApp.setSourceBadge($("analysisSource"), data);
    const warning = data.warning || (data.is_sample
      ? "This analysis uses the bundled sample snapshot. It is not live or current market data."
      : null);
    $("analysisWarning").classList.toggle("d-none", !warning);
    $("analysisWarning").textContent = warning || "";

    const symbol = data.symbol;
    const latest = data.latest || {};
    const stats = data.stats || {};
    $("analysisChartSubtitle").textContent =
      `${data.company_name || symbol} · ${data.exchange || "Exchange n/a"} · ${StockApp.formatDate(data.start)} to ${StockApp.formatDate(data.end)}`;

    // Tracked stocks
    if ($("aStatTracked")) {
      StockApp.getStocks().then(res => {
        $("aStatTracked").textContent = StockApp.formatNumber((res.stocks || []).length);
      }).catch(() => {
        $("aStatTracked").textContent = "—";
      });
    }

    $("aStatLatest").textContent = StockApp.formatMoney(latest.close, symbol);
    $("aStatLatestMeta").textContent = latest.trade_date
      ? `Close on ${StockApp.formatDate(latest.trade_date)}` : "No stored prices";

    $("aStatChange").className = `stat-value small ${StockApp.trendClass(latest.change_percent)}`;
    $("aStatChange").innerHTML = latest.change_percent === null || latest.change_percent === undefined
      ? "—" : `${StockApp.trendIcon(latest.change_percent)} ${StockApp.formatPercent(latest.change_percent)}`;
    $("aStatChangeMeta").textContent = latest.change === null || latest.change === undefined
      ? "Needs at least two closes"
      : `${StockApp.formatSignedMoney(latest.change, symbol)} vs previous close`;

    if ($("aStatHigh")) {
      $("aStatHigh").textContent = StockApp.formatMoney(stats.highest_close, symbol);
    }
    if ($("aStatLow")) {
      $("aStatLow").textContent = StockApp.formatMoney(stats.lowest_close, symbol);
    }
    if ($("aStatVolume")) {
      $("aStatVolume").textContent = StockApp.formatCompact(stats.average_volume);
      $("aStatVolume").title = stats.average_volume === null ? "" : StockApp.formatNumber(stats.average_volume);
    }

    $("aStatReturn").textContent = StockApp.formatPercent(data.total_return_percent);
    $("aStatReturn").className = `stat-value small ${StockApp.trendClass(data.total_return_percent)}`;
    $("aStatVolatility").textContent = StockApp.formatPercent(data.daily_returns.volatility_percent, 2, false);
    $("aStatVolatility").title = data.daily_returns.method || "";

    $("aAvgClose").textContent = StockApp.formatMoney(stats.average_close, symbol);
    $("aHighClose").textContent = StockApp.formatMoney(stats.highest_close, symbol);
    $("aLowClose").textContent = StockApp.formatMoney(stats.lowest_close, symbol);
    $("aHigh").textContent = StockApp.formatMoney(stats.highest_high, symbol);
    $("aLow").textContent = StockApp.formatMoney(stats.lowest_low, symbol);
    $("aAvgVolume").textContent = StockApp.formatCompact(stats.average_volume);
    $("aAvgVolume").title = stats.average_volume === null ? "" : StockApp.formatNumber(stats.average_volume);
    $("aObservations").textContent = StockApp.formatNumber(stats.observations || 0);
    $("aSma20").textContent = StockApp.formatMoney(data.moving_averages.sma20, symbol);
    $("aSma50").textContent = StockApp.formatMoney(data.moving_averages.sma50, symbol);
    $("aAvgReturn").textContent = StockApp.formatPercent(data.daily_returns.average_percent);
    $("aAvgReturn").className = StockApp.trendClass(data.daily_returns.average_percent);

    renderPriceChart(data);
    renderReturnsChart(data);
  }

  function renderPriceChart(data) {
    const series = data.series || {};
    const dates = series.dates || [];
    const symbol = data.symbol;
    const empty = dates.length === 0;
    $("analysisPriceChart").classList.toggle("d-none", empty);
    StockApp.setEmptyState($("analysisPriceEmpty"), empty,
      "No price data", "No records match this stock and date range. Try another range or load the sample data.");
    if (empty) {
      priceChart = StockApp.destroyChart(priceChart);
      return;
    }

    const context = $("analysisPriceChart").getContext("2d");
    const gradient = context.createLinearGradient(0, 0, 0, 380);
    gradient.addColorStop(0, "rgba(79,140,255,0.24)");
    gradient.addColorStop(1, "rgba(79,140,255,0.01)");
    priceChart = StockApp.destroyChart(priceChart);
    priceChart = new Chart(context, {
      type: "line",
      data: {
        labels: dates,
        datasets: [
          {
            label: "Close", data: series.close, borderColor: "#4f8cff",
            backgroundColor: gradient, borderWidth: 2.2, pointRadius: 0,
            pointHoverRadius: 4, fill: true, tension: 0.25, spanGaps: true,
          },
          {
            label: "SMA 20", data: series.sma20, borderColor: "#fbbf24",
            borderWidth: 1.5, pointRadius: 0, fill: false, tension: 0.2, spanGaps: true,
          },
          {
            label: "SMA 50", data: series.sma50, borderColor: "#22d3ee",
            borderWidth: 1.5, borderDash: [5, 4], pointRadius: 0, fill: false,
            tension: 0.2, spanGaps: true,
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        interaction: { mode: "index", intersect: false },
        plugins: {
          legend: { display: false },
          tooltip: {
            callbacks: {
              title: (items) => items.length ? StockApp.formatDate(items[0].label) : "",
              label: (item) => `${item.dataset.label}: ${StockApp.formatMoney(item.parsed.y, symbol)}`,
            },
          },
        },
        scales: {
          x: {
            grid: { display: false },
            ticks: {
              color: "#7f94b1", maxTicksLimit: 8, maxRotation: 0,
              callback(value) { return StockApp.formatDate(this.getLabelForValue(value), "short"); },
            },
          },
          y: {
            position: "right", grid: StockApp.grid,
            ticks: { color: "#7f94b1", callback: (value) => StockApp.formatMoney(value, symbol, 0) },
          },
        },
      },
    });
  }

  function renderReturnsChart(data) {
    const series = data.series || {};
    const dates = series.dates || [];
    const values = series.daily_returns || [];
    const empty = dates.length < 2;
    $("returnsChart").classList.toggle("d-none", empty);
    StockApp.setEmptyState($("returnsEmpty"), empty,
      "Returns not available", "At least two closing prices are needed to calculate a daily return.");
    if (empty) {
      returnsChart = StockApp.destroyChart(returnsChart);
      return;
    }
    const colors = values.map((value) =>
      value === null || value === undefined ? "rgba(148,163,184,0.3)" :
      value >= 0 ? "rgba(34,197,94,0.7)" : "rgba(251,84,116,0.7)");

    returnsChart = StockApp.destroyChart(returnsChart);
    returnsChart = new Chart($("returnsChart").getContext("2d"), {
      type: "bar",
      data: {
        labels: dates,
        datasets: [{
          label: "Daily return", data: values, backgroundColor: colors,
          hoverBackgroundColor: colors, borderRadius: 1, maxBarThickness: 10,
        }],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: { display: false },
          tooltip: {
            callbacks: {
              title: (items) => items.length ? StockApp.formatDate(items[0].label) : "",
              label: (item) => `Return: ${StockApp.formatPercent(item.parsed.y)}`,
            },
          },
        },
        scales: {
          x: {
            grid: { display: false },
            ticks: {
              color: "#7f94b1", maxTicksLimit: 9, maxRotation: 0,
              callback(value) { return StockApp.formatDate(this.getLabelForValue(value), "short"); },
            },
          },
          y: {
            position: "right", grid: StockApp.grid,
            ticks: { color: "#7f94b1", callback: (value) => `${Number(value).toFixed(1)}%` },
          },
        },
      },
    });
  }

  async function loadTable(page = 1, scroll = true, sequence = loadSequence) {
    const options = filters();
    const perPage = Number($("tablePerPage").value || 25);
    const tbody = $("priceTableBody");
    tbody.innerHTML = '<tr><td colspan="7" class="text-center text-muted py-4"><span class="spinner-border spinner-border-sm me-2"></span>Loading records…</td></tr>';

    try {
      const query = new URLSearchParams({
        start: options.start, end: options.end, page: String(page), per_page: String(perPage),
      });
      const data = await StockApp.api(`/api/stocks/${encodeURIComponent(options.symbol)}/history?${query}`);
      if (sequence !== loadSequence) return;
      currentPage = data.page;
      $("tableSubtitle").textContent =
        `${data.company_name || data.symbol} · ${StockApp.formatDate(data.start)} to ${StockApp.formatDate(data.end)}`;
      renderTable(data);
      updateUrl(data.page);
      if (scroll) $("priceTableBody").closest(".card").scrollIntoView({ behavior: "smooth", block: "start" });
    } catch (error) {
      if (sequence !== loadSequence) return;
      tbody.innerHTML = "";
      const row = document.createElement("tr");
      const cell = document.createElement("td");
      cell.colSpan = 7;
      cell.className = "text-center text-danger py-4";
      cell.textContent = error.message;
      row.appendChild(cell);
      tbody.appendChild(row);
      $("tableInfo").textContent = "Could not load records.";
      $("tablePagination").replaceChildren();
    }
  }

  function renderTable(data) {
    const tbody = $("priceTableBody");
    tbody.replaceChildren();
    if (!data.rows.length) {
      const row = document.createElement("tr");
      const cell = document.createElement("td");
      cell.colSpan = 7;
      cell.className = "text-center text-muted py-4";
      cell.textContent = "No records match this date range.";
      row.appendChild(cell);
      tbody.appendChild(row);
    } else {
      data.rows.forEach((item) => {
        const row = document.createElement("tr");
        const values = [
          StockApp.formatDate(item.trade_date),
          StockApp.formatMoney(item.open_price, data.symbol),
          StockApp.formatMoney(item.high_price, data.symbol),
          StockApp.formatMoney(item.low_price, data.symbol),
          StockApp.formatMoney(item.close_price, data.symbol),
          StockApp.formatNumber(item.volume),
        ];
        values.forEach((value, index) => {
          const cell = document.createElement("td");
          cell.textContent = value;
          if (index > 0 && index < 6) cell.classList.add("text-end");
          if (index === 4) cell.classList.add("fw-semibold", "text-soft");
          row.appendChild(cell);
        });
        const sourceCell = document.createElement("td");
        const badge = document.createElement("span");
        const isSample = item.data_source === "sample";
        badge.className = `source-badge ${isSample ? "source-sample" : "source-yfinance"}`;
        badge.textContent = isSample ? "Sample" : "Retrieved";
        sourceCell.appendChild(badge);
        row.appendChild(sourceCell);
        tbody.appendChild(row);
      });
    }

    const startIndex = data.total ? (data.page - 1) * data.per_page + 1 : 0;
    const endIndex = Math.min(data.page * data.per_page, data.total);
    $("tableInfo").textContent =
      `${data.symbol}: showing ${startIndex}–${endIndex} of ${StockApp.formatNumber(data.total)} records`;

    const pagination = $("tablePagination");
    pagination.replaceChildren();
    if (data.total_pages > 1) {
      pagination.appendChild(pageItem("Previous", data.page - 1, data.page === 1));
      const first = Math.max(1, data.page - 2);
      const last = Math.min(data.total_pages, first + 4);
      for (let page = first; page <= last; page += 1) {
        pagination.appendChild(pageItem(String(page), page, false, page === data.page));
      }
      pagination.appendChild(pageItem("Next", data.page + 1, data.page === data.total_pages));
    }
  }

  function pageItem(label, page, disabled, active = false) {
    const li = document.createElement("li");
    li.className = `page-item ${disabled ? "disabled" : ""} ${active ? "active" : ""}`.trim();
    const button = document.createElement("button");
    button.type = "button";
    button.className = "page-link";
    button.textContent = label;
    button.disabled = disabled;
    if (active) button.setAttribute("aria-current", "page");
    button.addEventListener("click", () => loadTable(page));
    li.appendChild(button);
    return li;
  }

  function renderEmpty(message) {
    ["analysisPriceChart", "returnsChart"].forEach((id) => $(id).classList.add("d-none"));
    StockApp.setEmptyState($("analysisPriceEmpty"), true, "Analysis unavailable", message);
    StockApp.setEmptyState($("returnsEmpty"), true, "Returns unavailable", message);
    priceChart = StockApp.destroyChart(priceChart);
    returnsChart = StockApp.destroyChart(returnsChart);
  }

  async function refreshStock() {
    if (!validateDates()) return;
    const button = $("refreshAnalysis");
    StockApp.setBusy(button, true, "Refreshing…");
    try {
      const options = filters();
      const result = await StockApp.api("/api/stocks/refresh", { method: "POST", body: options });
      StockApp.invalidateStocks();
      const stocks = await StockApp.getStocks(true);
      StockApp.populateStockSelect($("analysisStock"), stocks.stocks, options.symbol);
      await loadAll(1);
      StockApp.showAlert(
        `${result.symbol}: ${result.rows} rows available from ${result.source_label}.`,
        result.is_sample ? "warning" : "success"
      );
    } catch (error) {
      StockApp.showAlert(error.message);
    } finally {
      StockApp.setBusy(button, false);
    }
  }
})();
