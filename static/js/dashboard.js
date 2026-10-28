/* Dashboard page - Stock Catalogue, Search, Metrics, and Analysis Charts */
(function () {
  "use strict";

  const $ = (id) => document.getElementById(id);

  let allStocks = [];
  let activeSymbol = null;
  
  
  let loadSequence = 0;

  function escapeHtml(text) {
    if (text === null || text === undefined) return "";
    const div = document.createElement("div");
    div.textContent = String(text);
    return div.innerHTML;
  }

  document.addEventListener("DOMContentLoaded", init);

  async function init() {
    const searchInput = $("stockSearchInput");
    if (searchInput) {
      searchInput.addEventListener("input", () => {
        renderStockList();
      });
    }

    const refreshBtn = $("refreshStockBtn");
    if (refreshBtn) {
      refreshBtn.addEventListener("click", () => {
        if (activeSymbol) {
          loadStockDashboard(activeSymbol, true);
        }
      });
    }

    const demoBtn = $("loadDemoBtn");
    if (demoBtn) {
      demoBtn.addEventListener("click", async () => {
        try {
          StockApp.setBusy(demoBtn, true, "Loading demo…");
          const result = await StockApp.api("/api/demo/load", { method: "POST" });
          StockApp.invalidateStocks();
          StockApp.showAlert(result.message || "Sample demo data loaded successfully.", "success");
          await loadCatalogue();
          if (activeSymbol) {
            await loadStockDashboard(activeSymbol);
          }
        } catch (err) {
          StockApp.showAlert(err.message);
        } finally {
          StockApp.setBusy(demoBtn, false);
        }
      });
    }

    await loadCatalogue();
  }

  async function loadCatalogue() {
    const loadingEl = $("stockListLoading");
    const emptyEl = $("stockListEmpty");
    const listEl = $("stockList");

    try {
      if (loadingEl) loadingEl.classList.remove("d-none");
      if (listEl) listEl.innerHTML = "";
      if (emptyEl) emptyEl.classList.add("d-none");

      const result = await StockApp.getStocks();
      allStocks = result.stocks || [];

      if (loadingEl) loadingEl.classList.add("d-none");

      if (allStocks.length === 0) {
        if (emptyEl) emptyEl.classList.remove("d-none");
        $("stockListSubtitle").textContent = "0 stocks available";
        return;
      }

      // Check URL param or pick first stock with data
      const urlParams = new URLSearchParams(window.location.search);
      const requested = (urlParams.get("symbol") || "").toUpperCase();
      const match = allStocks.find((s) => s.symbol === requested);
      const preferred = match || allStocks.find((s) => s.has_data) || allStocks[0];

      activeSymbol = preferred.symbol;
      renderStockList();
      await loadStockDashboard(activeSymbol);
    } catch (error) {
      if (loadingEl) loadingEl.classList.add("d-none");
      StockApp.showAlert(error.message);
    }
  }

  function renderStockList() {
    const searchInput = $("stockSearchInput");
    const query = searchInput ? searchInput.value.trim().toLowerCase() : "";
    const listEl = $("stockList");
    const emptyEl = $("stockListEmpty");
    const subtitleEl = $("stockListSubtitle");

    if (!listEl) return;

    listEl.innerHTML = "";

    let filteredStocks = allStocks;
    if (query) {
      filteredStocks = allStocks.filter((stock) => {
        const symbol = (stock.symbol || "").toLowerCase();
        const name = (stock.company_name || "").toLowerCase();
        return symbol.includes(query) || name.includes(query);
      });
    }

    if (subtitleEl) {
      subtitleEl.textContent = query
        ? `Showing ${filteredStocks.length} of ${allStocks.length} stocks`
        : `Total ${allStocks.length} stocks available`;
    }

    if (filteredStocks.length === 0) {
      if (emptyEl) emptyEl.classList.remove("d-none");
      return;
    }

    if (emptyEl) emptyEl.classList.add("d-none");

    filteredStocks.forEach((stock) => {
      const item = document.createElement("button");
      item.type = "button";
      const isActive = stock.symbol === activeSymbol;
      item.className = `list-group-item list-group-item-action d-flex align-items-center gap-3 py-3 ${isActive ? "active" : ""}`;
      item.dataset.symbol = stock.symbol;

      item.innerHTML = `
        <div class="flex-shrink-0">
          <div class="rounded-circle ${isActive ? "bg-white bg-opacity-25" : "bg-primary bg-opacity-10"} d-flex align-items-center justify-content-center" style="width: 40px; height: 40px;">
            <i class="bi bi-bar-chart-line ${isActive ? "text-white" : "text-primary"}"></i>
          </div>
        </div>
        <div class="flex-grow-1 text-start">
          <div class="d-flex align-items-center gap-2">
            <strong>${escapeHtml(stock.symbol)}</strong>
            ${stock.exchange ? `<span class="badge ${isActive ? "bg-light text-dark" : "bg-secondary bg-opacity-50"}">${escapeHtml(stock.exchange)}</span>` : ""}
          </div>
          <div class="${isActive ? "text-light" : "text-muted"} small text-truncate" style="max-width: 220px;">${escapeHtml(stock.company_name || "")}</div>
        </div>
        <div class="flex-shrink-0">
          <i class="bi bi-chevron-right ${isActive ? "text-white" : "text-muted"}"></i>
        </div>
      `;

      item.addEventListener("click", () => {
        if (activeSymbol !== stock.symbol) {
          activeSymbol = stock.symbol;
          renderStockList();
          loadStockDashboard(stock.symbol);
        }
      });

      listEl.appendChild(item);
    });
  }

  async function loadStockDashboard(symbol, forceRefresh = false) {
    if (!symbol) return;
    const sequence = ++loadSequence;

    StockApp.hideAlert();
    const loadingOverlay = $("dashboardLoading");
    if (loadingOverlay) loadingOverlay.classList.remove("d-none");
    StockApp.setPageLoading(true);

    try {
      const url = `/api/dashboard?symbol=${encodeURIComponent(symbol)}${forceRefresh ? "&refresh=1" : ""}`;
      const data = await StockApp.api(url);

      if (sequence !== loadSequence) return;

      renderStockDetails(data);
      renderMetrics(data);
      

      const warningEl = $("dashboardWarning");
      if (warningEl) {
        if (data.warning) {
          warningEl.textContent = data.warning;
          warningEl.classList.remove("d-none");
        } else {
          warningEl.classList.add("d-none");
        }
      }
    } catch (error) {
      if (sequence !== loadSequence) return;
      StockApp.showAlert(error.message);
      renderEmptyDashboard(symbol, error.message);
    } finally {
      if (sequence === loadSequence) {
        if (loadingOverlay) loadingOverlay.classList.add("d-none");
        StockApp.setPageLoading(false);
      }
    }
  }

  function renderStockDetails(data) {
    const stock = data.stock || {};
    const symbol = stock.symbol || activeSymbol || "—";
    const company = stock.company_name || "—";
    const exchange = stock.exchange || "—";

    if ($("activeSymbol")) $("activeSymbol").textContent = symbol;
    if ($("activeCompanyName")) $("activeCompanyName").textContent = company;
    if ($("activeExchange")) $("activeExchange").textContent = exchange;

    const analysisLink = $("fullAnalysisLink");
    if (analysisLink) {
      analysisLink.href = `/analysis?symbol=${encodeURIComponent(symbol)}`;
    }

    const sourceBadge = $("dashboardSource");
    if (sourceBadge) {
      StockApp.setSourceBadge(sourceBadge, data);
    }
  }

  function renderMetrics(data) {
    const symbol = (data.stock && data.stock.symbol) || activeSymbol;
    const moving = data.moving_averages || {};
    const returns = data.daily_returns || {};
    const stats = data.stats || {};

    // 1. 20-Day SMA
    const sma20El = $("mStatSma20");
    if (sma20El) {
      sma20El.textContent = moving.sma20 !== null && moving.sma20 !== undefined
        ? StockApp.formatMoney(moving.sma20, symbol)
        : "—";
    }

    // 2. 50-Day SMA
    const sma50El = $("mStatSma50");
    if (sma50El) {
      sma50El.textContent = moving.sma50 !== null && moving.sma50 !== undefined
        ? StockApp.formatMoney(moving.sma50, symbol)
        : "—";
    }

    // 3. Volatility
    const volEl = $("mStatVolatility");
    if (volEl) {
      volEl.textContent = returns.volatility_percent !== null && returns.volatility_percent !== undefined
        ? StockApp.formatPercent(returns.volatility_percent, 2, false)
        : "—";
    }

    // 4. Period Return
    const returnEl = $("mStatReturn");
    const returnMeta = $("mStatReturnMeta");
    if (returnEl) {
      const val = data.total_return_percent;
      returnEl.textContent = val !== null && val !== undefined
        ? StockApp.formatPercent(val, 2, true)
        : "—";
      returnEl.className = `stat-value small ${StockApp.trendClass(val)}`;
    }
    if (returnMeta && data.start && data.end) {
      returnMeta.textContent = `${StockApp.formatDate(data.start, "short")} → ${StockApp.formatDate(data.end, "short")}`;
    }

    // 5. Avg. Daily Return
    const avgReturnEl = $("mStatAvgReturn");
    if (avgReturnEl) {
      const avg = returns.average_percent;
      avgReturnEl.textContent = avg !== null && avg !== undefined
        ? StockApp.formatPercent(avg, 2, true)
        : "—";
      avgReturnEl.className = `stat-value small ${StockApp.trendClass(avg)}`;
    }

    // 6. Period Range (High / Low)
    const rangeEl = $("mStatRange");
    const rangeMeta = $("mStatRangeMeta");
    if (rangeEl) {
      if (stats.highest_high !== null && stats.lowest_low !== null) {
        rangeEl.textContent = `${StockApp.formatMoney(stats.highest_high, symbol, 1)} / ${StockApp.formatMoney(stats.lowest_low, symbol, 1)}`;
      } else {
        rangeEl.textContent = "—";
      }
    }
    if (rangeMeta) {
      rangeMeta.textContent = stats.observations ? `${stats.observations} trading sessions` : "Period extremes";
    }
  }

  function renderEmptyDashboard(symbol, message) {
    if ($("activeSymbol")) $("activeSymbol").textContent = symbol || "—";
    if ($("activeCompanyName")) $("activeCompanyName").textContent = message || "No data available";

    ["mStatSma20", "mStatSma50", "mStatVolatility", "mStatReturn", "mStatAvgReturn", "mStatRange"].forEach((id) => {
      const el = $(id);
      if (el) el.textContent = "—";
    });
  }
})();

