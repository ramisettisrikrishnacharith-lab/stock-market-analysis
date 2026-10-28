/* Shared frontend helpers: API access, formatting, alerts, navigation. */
(function () {
  "use strict";

  const currencyFor = (symbol) => (/\.(NS|BO)$/i.test(symbol || "") ? "INR" : "USD");

  function formatMoney(value, symbol, digits = 2) {
    if (value === null || value === undefined || Number.isNaN(Number(value))) return "—";
    const currency = currencyFor(symbol);
    return new Intl.NumberFormat(currency === "INR" ? "en-IN" : "en-US", {
      style: "currency",
      currency,
      minimumFractionDigits: digits,
      maximumFractionDigits: digits,
    }).format(Number(value));
  }

  function formatSignedMoney(value, symbol, digits = 2) {
    if (value === null || value === undefined || Number.isNaN(Number(value))) return "—";
    const formatted = formatMoney(Math.abs(value), symbol, digits);
    const sign = Number(value) > 0 ? "+" : Number(value) < 0 ? "−" : "";
    return sign + formatted;
  }

  function formatNumber(value, digits = 0) {
    if (value === null || value === undefined || Number.isNaN(Number(value))) return "—";
    return new Intl.NumberFormat("en-US", {
      minimumFractionDigits: digits,
      maximumFractionDigits: digits,
    }).format(Number(value));
  }

  function formatCompact(value) {
    if (value === null || value === undefined || Number.isNaN(Number(value))) return "—";
    return new Intl.NumberFormat("en-US", { notation: "compact", maximumFractionDigits: 2 }).format(Number(value));
  }

  function formatPercent(value, digits = 2, signed = true) {
    if (value === null || value === undefined || Number.isNaN(Number(value))) return "—";
    const number = Number(value);
    const sign = signed && number > 0 ? "+" : "";
    return `${sign}${number.toFixed(digits)}%`;
  }

  function formatDate(iso, style = "medium") {
    if (!iso) return "—";
    const date = new Date(String(iso).slice(0, 10) + "T00:00:00");
    if (Number.isNaN(date.getTime())) return String(iso);
    const options = style === "short"
      ? { day: "2-digit", month: "short" }
      : { day: "2-digit", month: "short", year: "numeric" };
    return new Intl.DateTimeFormat("en-GB", options).format(date);
  }

  function formatDateTime(value) {
    if (!value) return "—";
    const date = new Date(String(value).replace(" ", "T"));
    if (Number.isNaN(date.getTime())) return String(value);
    return new Intl.DateTimeFormat("en-GB", {
      day: "2-digit", month: "short", year: "numeric",
      hour: "2-digit", minute: "2-digit",
    }).format(date);
  }

  function trendClass(value) {
    if (value === null || value === undefined || Number.isNaN(Number(value))) return "trend-flat";
    if (Number(value) > 0) return "trend-up";
    if (Number(value) < 0) return "trend-down";
    return "trend-flat";
  }

  function trendIcon(value) {
    if (value === null || value === undefined || Number.isNaN(Number(value))) return "";
    if (Number(value) > 0) return '<i class="bi bi-arrow-up-right"></i>';
    if (Number(value) < 0) return '<i class="bi bi-arrow-down-right"></i>';
    return "";
  }

  function todayISO() {
    const now = new Date();
    const offset = now.getTimezoneOffset();
    return new Date(now.getTime() - offset * 60000).toISOString().slice(0, 10);
  }

  function isoDaysAgo(days, fromISO) {
    const base = fromISO ? new Date(fromISO + "T00:00:00") : new Date();
    base.setDate(base.getDate() - Number(days));
    const offset = base.getTimezoneOffset();
    return new Date(base.getTime() - offset * 60000).toISOString().slice(0, 10);
  }

  function setDefaultRange(startEl, endEl, days = 365) {
    if (endEl && !endEl.value) endEl.value = todayISO();
    if (startEl && !startEl.value) startEl.value = isoDaysAgo(days, endEl && endEl.value);
  }

  async function api(url, options = {}) {
    const opts = Object.assign({}, options);
    opts.headers = Object.assign({ Accept: "application/json" }, options.headers || {});
    if (opts.body && typeof opts.body !== "string") {
      opts.body = JSON.stringify(opts.body);
      opts.headers["Content-Type"] = "application/json";
    }
    let response;
    try {
      response = await fetch(url, opts);
    } catch (error) {
      throw new Error("Could not reach the Flask server. Check that app.py is running and try again.");
    }

    const contentType = response.headers.get("content-type") || "";
    let data = null;
    if (contentType.includes("application/json")) {
      data = await response.json();
    } else {
      const text = await response.text();
      data = { error: { message: text || `Request failed with status ${response.status}.` } };
    }

    if (!response.ok) {
      const message = (data && data.error && data.error.message) ||
        `Request failed with status ${response.status}.`;
      const error = new Error(message);
      error.status = response.status;
      error.code = data && data.error ? data.error.code : "http_error";
      error.details = data && data.error ? data.error.details : null;
      throw error;
    }
    return data;
  }

  let stocksCache = null;

  async function getStocks(force = false) {
    if (!stocksCache || force) {
      stocksCache = await api("/api/stocks");
    }
    return stocksCache;
  }

  function invalidateStocks() { stocksCache = null; }

  function populateStockSelect(select, stocks, selectedSymbol) {
    if (!select) return;
    select.replaceChildren();
    if (!stocks.length) {
      const option = document.createElement("option");
      option.value = "";
      option.textContent = "No stocks configured";
      select.appendChild(option);
      return;
    }
    stocks.forEach((stock) => {
      const option = document.createElement("option");
      option.value = stock.symbol;
      option.textContent = `${stock.symbol} — ${stock.company_name}`;
      option.dataset.company = stock.company_name || "";
      option.dataset.exchange = stock.exchange || "";
      if (stock.symbol === selectedSymbol) option.selected = true;
      select.appendChild(option);
    });
    if (!selectedSymbol || !stocks.some((stock) => stock.symbol === selectedSymbol)) {
      const preferred = stocks.find((stock) => stock.has_data) || stocks[0];
      if (preferred) select.value = preferred.symbol;
    }
  }

  function showAlert(message, type = "danger", options = {}) {
    if (!message) return;
    const el = document.getElementById(options.elementId || "globalAlert");
    if (!el) return;
    el.className = `alert alert-${type} alert-dismissible fade show`;
    el.replaceChildren();

    const icon = document.createElement("i");
    icon.className = type === "success" ? "bi bi-check-circle-fill me-2" :
      type === "warning" ? "bi bi-exclamation-triangle-fill me-2" :
      type === "info" ? "bi bi-info-circle-fill me-2" : "bi bi-exclamation-octagon-fill me-2";

    const text = document.createElement("span");
    text.textContent = message;

    const close = document.createElement("button");
    close.type = "button";
    close.className = "btn-close";
    close.setAttribute("data-bs-dismiss", "alert");
    close.setAttribute("aria-label", "Close");

    el.append(icon, text, close);
    el.classList.remove("d-none");
    el.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }

  function hideAlert(elementId = "globalAlert") {
    const el = document.getElementById(elementId);
    if (el) el.classList.add("d-none");
  }

  function setPageLoading(active) {
    const bar = document.getElementById("pageLoading");
    if (!bar) return;
    if (active) {
      bar.classList.remove("done");
      bar.classList.add("active");
    } else {
      bar.classList.remove("active");
      bar.classList.add("done");
      setTimeout(() => bar.classList.remove("done"), 420);
    }
  }

  function setBusy(button, busy, busyLabel) {
    if (!button) return;
    if (busy) {
      if (!button.dataset.originalHtml) button.dataset.originalHtml = button.innerHTML;
      button.disabled = true;
      button.innerHTML = `<span class="spinner-border spinner-border-sm me-2" role="status" aria-hidden="true"></span>${busyLabel || "Loading…"}`;
    } else {
      button.disabled = false;
      if (button.dataset.originalHtml) {
        button.innerHTML = button.dataset.originalHtml;
        delete button.dataset.originalHtml;
      }
    }
  }

  function setSourceBadge(element, data) {
    if (!element) return;
    const source = data.source || "unknown";
    const label = data.is_sample ? "Sample data · offline demo" :
      source === "twelve_data" ? "Retrieved data · Twelve Data" :
      source === "yfinance" ? "Retrieved data · yfinance" :
      source === "mixed" ? "Mixed retrieved + sample data" :
      data.source_label || "Unknown source";
    element.textContent = label;
    element.className = `source-badge source-${source === "unknown" ? "unknown" : source}`;
    element.title = data.is_sample
      ? "Bundled sample snapshot. Not live or current market prices."
      : source === "twelve_data" ? "Live market data retrieved from Twelve Data." :
        source === "yfinance" ? "Historical data retrieved from yfinance." : "";
  }

  function setEmptyState(element, show, title, message) {
    if (!element) return;
    element.classList.toggle("d-none", !show);
    if (show) {
      element.replaceChildren();
      const icon = document.createElement("i");
      icon.className = "bi bi-bar-chart";
      const heading = document.createElement("strong");
      heading.textContent = title || "No data available";
      const paragraph = document.createElement("p");
      paragraph.textContent = message || "Adjust the filters and try again.";
      element.append(icon, heading, paragraph);
    }
  }

  function chartDefaults() {
    if (typeof Chart === "undefined") return;
    Chart.defaults.color = "#8fa2bd";
    Chart.defaults.font.family = '"Segoe UI", Inter, system-ui, sans-serif';
    Chart.defaults.font.size = 11;
    Chart.defaults.borderColor = "rgba(148,163,184,0.10)";
    Chart.defaults.animation.duration = 450;
    Chart.defaults.plugins.legend.labels.usePointStyle = true;
    Chart.defaults.plugins.legend.labels.boxWidth = 7;
    Chart.defaults.plugins.legend.labels.padding = 16;
    Chart.defaults.plugins.tooltip.backgroundColor = "rgba(8,16,30,0.94)";
    Chart.defaults.plugins.tooltip.borderColor = "rgba(148,163,184,0.22)";
    Chart.defaults.plugins.tooltip.borderWidth = 1;
    Chart.defaults.plugins.tooltip.titleColor = "#e9effa";
    Chart.defaults.plugins.tooltip.bodyColor = "#c3d0e4";
    Chart.defaults.plugins.tooltip.padding = 10;
    Chart.defaults.plugins.tooltip.cornerRadius = 8;
  }

  const moneyTick = (symbol) => (value) =>
    formatMoney(value, symbol, 0);

  const grid = { color: "rgba(148,163,184,0.07)", drawTicks: false };
  const ticks = { color: "#7f94b1", maxTicksLimit: 7, padding: 6 };

  function destroyChart(chart) {
    if (chart && typeof chart.destroy === "function") chart.destroy();
    return null;
  }

  function initSidebar() {
    const sidebar = document.getElementById("appSidebar");
    const backdrop = document.getElementById("sidebarBackdrop");
    const toggle = document.getElementById("sidebarToggle");
    if (!sidebar || !toggle) return;
    const close = () => {
      sidebar.classList.remove("open");
      if (backdrop) backdrop.classList.remove("show");
      document.body.style.overflow = "";
    };
    toggle.addEventListener("click", () => {
      const open = sidebar.classList.toggle("open");
      if (backdrop) backdrop.classList.toggle("show", open);
      document.body.style.overflow = open ? "hidden" : "";
    });
    if (backdrop) backdrop.addEventListener("click", close);
    sidebar.querySelectorAll("a.nav-link").forEach((link) => link.addEventListener("click", close));
    window.addEventListener("resize", () => {
      if (window.innerWidth >= 992) close();
    });
  }

  document.addEventListener("DOMContentLoaded", () => {
    initSidebar();
    chartDefaults();
    const label = document.getElementById("todayLabel");
    if (label) {
      label.textContent = new Intl.DateTimeFormat("en-GB", {
        day: "2-digit", month: "short", year: "numeric",
      }).format(new Date());
    }
  });

  window.StockApp = {
    api, getStocks, invalidateStocks, populateStockSelect,
    formatMoney, formatSignedMoney, formatNumber, formatCompact, formatPercent,
    formatDate, formatDateTime, trendClass, trendIcon,
    todayISO, isoDaysAgo, setDefaultRange,
    showAlert, hideAlert, setPageLoading, setBusy, setSourceBadge, setEmptyState,
    chartDefaults, destroyChart, moneyTick, grid, ticks,
    currencyFor,
  };
})();
