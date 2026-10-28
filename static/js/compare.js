/* Stock comparison page */
(function () {
  "use strict";

  const $ = (id) => document.getElementById(id);
  const COLORS = ["#4f8cff", "#22c55e", "#fbbf24", "#f472b6", "#a78bfa", "#22d3ee"];
  let allStocks = [];
  let lastResult = null;
  let chartMode = "normalized";
  let compareChart = null;
  let volumeChart = null;
  let loadSequence = 0;

  document.addEventListener("DOMContentLoaded", init);

  async function init() {
    StockApp.setDefaultRange($("compareStart"), $("compareEnd"), 180);
    const params = new URLSearchParams(window.location.search);
    if (params.get("start")) $("compareStart").value = params.get("start");
    if (params.get("end")) $("compareEnd").value = params.get("end");
    const requested = (params.get("symbols") || "").split(",").map((item) => item.trim()).filter(Boolean);

    $("compareFilter").addEventListener("submit", (event) => {
      event.preventDefault();
      loadComparison();
    });
    $("stockSearch").addEventListener("input", renderStockPicker);
    $("clearSelection").addEventListener("click", clearSelection);
    $("normalizedBtn").addEventListener("click", () => setChartMode("normalized"));
    $("rawBtn").addEventListener("click", () => setChartMode("raw"));

    try {
      const result = await StockApp.getStocks();
      allStocks = result.stocks;
      if (!allStocks.length) {
        $("stockPicker").innerHTML = '<div class="text-muted small p-3">No stocks configured. Run init_db.py first.</div>';
        return;
      }
      renderStockPicker(requested);
      if (requested.length >= 2) {
        await loadComparison();
      }
    } catch (error) {
      $("stockPicker").innerHTML = '<div class="text-danger small p-3"></div>';
      $("stockPicker").firstElementChild.textContent = error.message;
      StockApp.showAlert(error.message);
    }
  }

  function renderStockPicker(requested = null) {
    const picker = $("stockPicker");
    const selectedBefore = new Set(getSelected());
    if (requested) requested.forEach((symbol) => selectedBefore.add(symbol));
    const term = ($("stockSearch").value || "").trim().toLowerCase();
    const filtered = allStocks.filter((stock) =>
      !term || stock.symbol.toLowerCase().includes(term) ||
      (stock.company_name || "").toLowerCase().includes(term));

    picker.replaceChildren();
    if (!filtered.length) {
      const empty = document.createElement("div");
      empty.className = "text-muted small p-3";
      empty.textContent = "No stocks match that search.";
      picker.appendChild(empty);
      return;
    }

    filtered.forEach((stock) => {
      const label = document.createElement("label");
      label.className = "stock-option";

      const checkbox = document.createElement("input");
      checkbox.type = "checkbox";
      checkbox.className = "form-check-input mt-0";
      checkbox.value = stock.symbol;
      checkbox.checked = selectedBefore.has(stock.symbol);
      checkbox.addEventListener("change", updateSelectionState);

      const text = document.createElement("span");
      text.className = "flex-grow-1";
      const symbol = document.createElement("span");
      symbol.className = "symbol d-block";
      symbol.textContent = stock.symbol;
      const company = document.createElement("span");
      company.className = "company d-block";
      company.textContent = `${stock.company_name || ""}${stock.exchange ? " · " + stock.exchange : ""}`;
      text.append(symbol, company);

      const dataChip = document.createElement("span");
      dataChip.className = "chip";
      dataChip.textContent = stock.has_data ? `${stock.price_count} rows` : "No data";

      label.append(checkbox, text, dataChip);
      picker.appendChild(label);
    });
    updateSelectionState();
  }

  function getSelected() {
    return Array.from(document.querySelectorAll("#stockPicker input[type=checkbox]:checked"))
      .map((input) => input.value);
  }

  function updateSelectionState() {
    const selected = getSelected();
    $("selectedCount").textContent = `${selected.length} selected`;
    document.querySelectorAll("#stockPicker .stock-option").forEach((label) => {
      const input = label.querySelector("input");
      label.classList.toggle("selected", input.checked);
      input.disabled = !input.checked && selected.length >= 6;
    });
  }

  function clearSelection() {
    document.querySelectorAll("#stockPicker input[type=checkbox]").forEach((input) => {
      input.checked = false;
    });
    updateSelectionState();
    lastResult = null;
    $("compareResults").classList.add("d-none");
    $("compareIntro").classList.remove("d-none");
    $("compareSource").textContent = "No comparison yet";
    $("compareSource").className = "source-badge source-unknown";
    $("compareWarning").classList.add("d-none");
    compareChart = StockApp.destroyChart(compareChart);
    volumeChart = StockApp.destroyChart(volumeChart);
    window.history.replaceState({}, "", window.location.pathname);
  }

  function validate() {
    const symbols = getSelected();
    if (symbols.length < 2) {
      StockApp.showAlert("Select at least two stocks to compare.");
      return null;
    }
    if (symbols.length > 6) {
      StockApp.showAlert("Compare at most six stocks at once.");
      return null;
    }
    const start = $("compareStart").value;
    const end = $("compareEnd").value;
    if (!start || !end) {
      StockApp.showAlert("Choose both a start date and an end date.");
      return null;
    }
    if (start > end) {
      StockApp.showAlert("The start date must be on or before the end date.");
      return null;
    }
    return { symbols, start, end };
  }

  async function loadComparison() {
    const filters = validate();
    if (!filters) return;
    const sequence = ++loadSequence;
    const button = $("compareButton");
    StockApp.hideAlert();
    StockApp.setBusy(button, true, "Comparing…");
    StockApp.setPageLoading(true);
    $("compareLoading").classList.add("show");

    try {
      const query = new URLSearchParams({
        symbols: filters.symbols.join(","),
        start: filters.start,
        end: filters.end,
      });
      const data = await StockApp.api(`/api/compare?${query.toString()}`);
      if (sequence !== loadSequence) return;
      lastResult = data;
      render(data);
      $("compareIntro").classList.add("d-none");
      $("compareResults").classList.remove("d-none");
      window.history.replaceState({}, "", `${window.location.pathname}?${query.toString()}`);
    } catch (error) {
      if (sequence !== loadSequence) return;
      StockApp.showAlert(error.message);
      $("compareResults").classList.add("d-none");
      $("compareIntro").classList.remove("d-none");
    } finally {
      if (sequence === loadSequence) {
        $("compareLoading").classList.remove("show");
        StockApp.setBusy(button, false);
        StockApp.setPageLoading(false);
      }
    }
  }

  function render(data) {
    const sources = data.data_sources || [];
    const source = sources.includes("sample") && sources.includes("yfinance")
      ? "mixed" : sources[0] || "unknown";
    StockApp.setSourceBadge($("compareSource"), {
      source,
      is_sample: data.is_sample,
      source_label: data.is_sample ? "Sample snapshot" : "Retrieved market data",
    });

    const messages = [];
    (data.warnings || []).forEach((message) => messages.push(message));
    if (data.is_sample) {
      messages.push("One or more stocks use the bundled sample snapshot, not live market data.");
    }
    const failureSymbols = Object.keys(data.failures || {});
    if (failureSymbols.length) {
      messages.push(`Skipped: ${failureSymbols.join(", ")}.`);
    }
    const warning = $("compareWarning");
    warning.classList.toggle("d-none", messages.length === 0);
    warning.textContent = messages.join(" ");

    const entries = Object.entries(data.stats || {}).filter(([, item]) => item.total_return_percent !== null);
    entries.sort((a, b) => b[1].total_return_percent - a[1].total_return_percent);
    if (entries.length) {
      const [bestSymbol, best] = entries[0];
      const [worstSymbol, worst] = entries[entries.length - 1];
      $("cBest").textContent = bestSymbol;
      $("cBest").className = `stat-value small ${StockApp.trendClass(best.total_return_percent)}`;
      $("cBestMeta").textContent = `${StockApp.formatPercent(best.total_return_percent)} period return`;
      $("cWorst").textContent = worstSymbol;
      $("cWorst").className = `stat-value small ${StockApp.trendClass(worst.total_return_percent)}`;
      $("cWorstMeta").textContent = `${StockApp.formatPercent(worst.total_return_percent)} period return`;
    } else {
      $("cBest").textContent = "—";
      $("cBestMeta").textContent = "Insufficient common dates";
      $("cWorst").textContent = "—";
      $("cWorstMeta").textContent = "Insufficient common dates";
    }

    $("cCommon").textContent = StockApp.formatNumber(data.methodology.common_dates || 0);

    const volatilityEntries = Object.entries(data.stats || {})
      .filter(([, item]) => item.volatility_percent !== null)
      .sort((a, b) => b[1].volatility_percent - a[1].volatility_percent);
    if (volatilityEntries.length) {
      const [symbol, item] = volatilityEntries[0];
      $("cVolatile").textContent = symbol;
      $("cVolatileMeta").textContent = `${StockApp.formatPercent(item.volatility_percent, 2, false)} daily std. dev.`;
    } else {
      $("cVolatile").textContent = "—";
      $("cVolatileMeta").textContent = "Not enough common dates";
    }

    $("compareChartSubtitle").textContent =
      `${data.symbols.length} stocks · ${StockApp.formatDate(data.start)} to ${StockApp.formatDate(data.end)}`;
    $("compareTableSubtitle").textContent =
      `${data.symbols.join(", ")} · ${StockApp.formatDate(data.start)} to ${StockApp.formatDate(data.end)}`;
    $("compareMethodMeta").textContent =
      `Common trading dates used for statistics: ${StockApp.formatNumber(data.methodology.common_dates)}. ` +
      `Volatility: ${data.methodology.volatility} ` +
      (failureSymbols.length ? `Unavailable stocks: ${failureSymbols.join(", ")}.` : "");

    renderChart();
    renderVolumeChart();
    renderTable();
  }

  function setChartMode(mode) {
    chartMode = mode;
    $("normalizedBtn").classList.toggle("active", mode === "normalized");
    $("rawBtn").classList.toggle("active", mode === "raw");
    if (lastResult) renderChart();
  }

  function renderChart() {
    if (!lastResult) return;
    const data = lastResult;
    const canvas = $("compareChart");
    const empty = !data.dates || data.dates.length === 0;
    canvas.classList.toggle("d-none", empty);
    StockApp.setEmptyState($("compareChartEmpty"), empty, "No comparison data",
      "These stocks do not share usable history in the selected range.");
    if (empty) {
      compareChart = StockApp.destroyChart(compareChart);
      return;
    }

    $("compareChartSubtitle").textContent = chartMode === "normalized"
      ? "Normalised to 100 at the first available close"
      : "Raw closing prices · currencies can differ between exchanges";

    const datasets = data.symbols.map((symbol, index) => ({
      label: symbol,
      data: (data.series[symbol] || {})[chartMode] || [],
      borderColor: COLORS[index % COLORS.length],
      backgroundColor: COLORS[index % COLORS.length],
      borderWidth: 2,
      pointRadius: 0,
      pointHoverRadius: 4,
      fill: false,
      tension: 0.2,
      spanGaps: true,
    }));

    compareChart = StockApp.destroyChart(compareChart);
    compareChart = new Chart(canvas.getContext("2d"), {
      type: "line",
      data: { labels: data.dates, datasets },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        interaction: { mode: "index", intersect: false },
        plugins: {
          legend: { position: "top", align: "start" },
          tooltip: {
            callbacks: {
              title: (items) => items.length ? StockApp.formatDate(items[0].label) : "",
              label: (item) => {
                const value = item.parsed.y;
                if (value === null || value === undefined) return `${item.dataset.label}: —`;
                return chartMode === "normalized"
                  ? `${item.dataset.label}: ${Number(value).toFixed(2)} (start = 100)`
                  : `${item.dataset.label}: ${StockApp.formatMoney(value, item.dataset.label)}`;
              },
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
            ticks: {
              color: "#7f94b1",
              callback: (value) => chartMode === "normalized"
                ? StockApp.formatNumber(value, 0)
                : StockApp.formatCompact(value),
            },
          },
        },
      },
    });
  }

  function renderVolumeChart() {
    if (!lastResult) return;
    const data = lastResult;
    const symbols = data.symbols;
    const volumes = symbols.map((symbol) => (data.stats[symbol] || {}).average_volume);
    const empty = volumes.every((value) => value === null || value === undefined);
    $("compareVolumeChart").classList.toggle("d-none", empty);
    StockApp.setEmptyState($("compareVolumeEmpty"), empty, "No volume data",
      "Volume was not available on common trading dates.");
    if (empty) {
      volumeChart = StockApp.destroyChart(volumeChart);
      return;
    }
    volumeChart = StockApp.destroyChart(volumeChart);
    volumeChart = new Chart($("compareVolumeChart").getContext("2d"), {
      type: "bar",
      data: {
        labels: symbols,
        datasets: [{
          label: "Average volume",
          data: volumes,
          backgroundColor: symbols.map((_, index) => COLORS[index % COLORS.length] + "99"),
          borderColor: symbols.map((_, index) => COLORS[index % COLORS.length]),
          borderWidth: 1,
          borderRadius: 4,
          maxBarThickness: 34,
        }],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: { display: false },
          tooltip: {
            callbacks: {
              label: (item) => `Average volume: ${StockApp.formatNumber(item.parsed.y)}`,
            },
          },
        },
        scales: {
          x: { grid: { display: false }, ticks: { color: "#9fb2ca", maxRotation: 0 } },
          y: {
            position: "right", grid: StockApp.grid,
            ticks: { color: "#7f94b1", maxTicksLimit: 6, callback: (value) => StockApp.formatCompact(value) },
          },
        },
      },
    });
  }

  function renderTable() {
    if (!lastResult) return;
    const data = lastResult;
    const tbody = $("compareTableBody");
    tbody.replaceChildren();

    data.symbols.forEach((symbol) => {
      const stats = data.stats[symbol] || {};
      const meta = (data.metadata || {})[symbol] || {};
      const row = document.createElement("tr");

      const stockCell = document.createElement("td");
      const symbolSpan = document.createElement("div");
      symbolSpan.className = "table-symbol";
      symbolSpan.textContent = symbol;
      const companySpan = document.createElement("div");
      companySpan.className = "table-company";
      companySpan.textContent = meta.company_name || "—";
      stockCell.append(symbolSpan, companySpan);
      row.appendChild(stockCell);

      const cells = [
        StockApp.formatMoney(stats.start_price, symbol),
        StockApp.formatMoney(stats.end_price, symbol),
      ];
      cells.forEach((value) => appendCell(row, value, "text-end"));

      const returnCell = document.createElement("td");
      returnCell.className = `text-end fw-semibold ${StockApp.trendClass(stats.total_return_percent)}`;
      returnCell.textContent = StockApp.formatPercent(stats.total_return_percent);
      row.appendChild(returnCell);

      appendCell(row, StockApp.formatPercent(stats.average_daily_return_percent), "text-end");
      appendCell(row, StockApp.formatPercent(stats.volatility_percent, 2, false), "text-end");

      const volumeCell = document.createElement("td");
      volumeCell.className = "text-end";
      volumeCell.textContent = StockApp.formatCompact(stats.average_volume);
      volumeCell.title = stats.average_volume === null ? "" : StockApp.formatNumber(stats.average_volume);
      row.appendChild(volumeCell);

      appendCell(row, StockApp.formatNumber(stats.observations), "text-end");
      tbody.appendChild(row);
    });
  }

  function appendCell(row, text, className = "") {
    const cell = document.createElement("td");
    if (className) cell.className = className;
    cell.textContent = text;
    row.appendChild(cell);
  }
})();
