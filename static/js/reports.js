/* Reports and CSV export page */
(function () {
  "use strict";

  const $ = (id) => document.getElementById(id);
  let loadSequence = 0;

  document.addEventListener("DOMContentLoaded", init);

  async function init() {
    StockApp.setDefaultRange($("reportStart"), $("reportEnd"), 365);
    const params = new URLSearchParams(window.location.search);
    if (params.get("start")) $("reportStart").value = params.get("start");
    if (params.get("end")) $("reportEnd").value = params.get("end");

    $("reportFilter").addEventListener("submit", (event) => {
      event.preventDefault();
      if (!validate()) return;
      loadPreview(1);
    });
    $("reportStock").addEventListener("change", invalidateExports);
    $("reportStart").addEventListener("change", invalidateExports);
    $("reportEnd").addEventListener("change", invalidateExports);
    $("reportPerPage").addEventListener("change", () => {
      if (validate()) loadPreview(1);
    });
    $("exportPrices").addEventListener("click", () => exportCsv("prices"));
    $("exportAnalysis").addEventListener("click", () => exportCsv("analysis"));

    try {
      const stocks = await StockApp.getStocks();
      if (!stocks.stocks.length) {
        StockApp.showAlert("No stocks are configured. Run init_db.py first.");
        return;
      }
      StockApp.populateStockSelect($("reportStock"), stocks.stocks, params.get("symbol"));
      await loadPreview(1);
    } catch (error) {
      StockApp.showAlert(error.message);
    }
  }

  function filters() {
    return {
      symbol: $("reportStock").value,
      start: $("reportStart").value,
      end: $("reportEnd").value,
      per_page: $("reportPerPage").value,
    };
  }

  function validate() {
    const options = filters();
    if (!options.symbol) {
      StockApp.showAlert("Choose a stock.");
      return false;
    }
    if (!options.start || !options.end) {
      StockApp.showAlert("Choose both a start date and an end date.");
      return false;
    }
    if (options.start > options.end) {
      StockApp.showAlert("The start date must be on or before the end date.");
      return false;
    }
    return true;
  }

  function invalidateExports() {
    $("exportPrices").disabled = true;
    $("exportAnalysis").disabled = true;
    $("reportSummary").textContent = "Run a preview to enable exports for these filters.";
  }

  async function loadPreview(page = 1) {
    const options = filters();
    const sequence = ++loadSequence;
    StockApp.hideAlert();
    $("reportLoading").classList.add("show");
    StockApp.setPageLoading(true);
    $("previewButton").disabled = true;

    try {
      const query = new URLSearchParams({
        symbol: options.symbol, start: options.start, end: options.end,
        page: String(page), per_page: options.per_page,
      });
      const data = await StockApp.api(`/api/reports?${query.toString()}`);
      if (sequence !== loadSequence) return;
      render(data);
      window.history.replaceState({}, "", `${window.location.pathname}?${query.toString()}`);
    } catch (error) {
      if (sequence !== loadSequence) return;
      StockApp.showAlert(error.message);
      $("reportTableWrap").classList.add("d-none");
      StockApp.setEmptyState($("reportEmpty"), true, "Could not load the report", error.message);
      $("reportTableInfo").textContent = "No records loaded.";
      $("reportPagination").replaceChildren();
      $("reportSummary").textContent = "Export unavailable.";
      $("reportSource").textContent = "Report unavailable";
      $("reportSource").className = "source-badge source-unknown";
      $("reportWarning").classList.add("d-none");
      invalidateExports();
    } finally {
      if (sequence === loadSequence) {
        $("reportLoading").classList.remove("show");
        StockApp.setPageLoading(false);
        $("previewButton").disabled = false;
      }
    }
  }

  function render(data) {
    StockApp.setSourceBadge($("reportSource"), data);
    const warning = data.warning || (data.is_sample
      ? "This report includes sample snapshot rows. They are not live market data." : null);
    $("reportWarning").classList.toggle("d-none", !warning);
    $("reportWarning").textContent = warning || "";

    $("reportTableSubtitle").textContent =
      `${data.company_name || data.symbol} · ${StockApp.formatDate(data.start)} to ${StockApp.formatDate(data.end)}`;
    $("reportSummary").textContent =
      `${StockApp.formatNumber(data.total)} records · ${data.source_label}`;

    $("exportPrices").disabled = data.total === 0;
    $("exportAnalysis").disabled = data.total === 0;

    renderTable(data);
  }

  function renderTable(data) {
    const tbody = $("reportTableBody");
    tbody.replaceChildren();
    const empty = !data.rows.length;
    $("reportTableWrap").classList.toggle("d-none", empty);
    StockApp.setEmptyState($("reportEmpty"), empty, "No records to preview",
      "Adjust the stock or date range. Exports are only available when records exist.");

    if (!empty) {
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
        const isSample = item.data_source === "sample";
        const badge = document.createElement("span");
        badge.className = `source-badge ${isSample ? "source-sample" : "source-yfinance"}`;
        badge.textContent = isSample ? "Sample" : "Retrieved";
        sourceCell.appendChild(badge);
        row.appendChild(sourceCell);
        tbody.appendChild(row);
      });
    }

    const startIndex = data.total ? (data.page - 1) * data.per_page + 1 : 0;
    const endIndex = Math.min(data.page * data.per_page, data.total);
    $("reportTableInfo").textContent = data.total
      ? `${data.symbol}: showing ${startIndex}–${endIndex} of ${StockApp.formatNumber(data.total)} records`
      : "No records in this range.";

    const pagination = $("reportPagination");
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
    button.addEventListener("click", () => {
      loadPreview(page);
      $("reportTableBody").closest(".card").scrollIntoView({ behavior: "smooth", block: "start" });
    });
    li.appendChild(button);
    return li;
  }

  async function exportCsv(type) {
    if (!validate()) return;
    const button = type === "prices" ? $("exportPrices") : $("exportAnalysis");
    const originalLabel = button.innerHTML;
    StockApp.setBusy(button, true, "Preparing…");
    StockApp.hideAlert();

    try {
      const options = filters();
      const query = new URLSearchParams({
        symbol: options.symbol, start: options.start, end: options.end, type,
      });
      const response = await fetch(`/api/reports/export?${query.toString()}`, {
        headers: { Accept: "text/csv, application/json" },
      });
      if (!response.ok) {
        let message = `Export failed with status ${response.status}.`;
        try {
          const data = await response.json();
          if (data.error && data.error.message) message = data.error.message;
        } catch (ignored) { /* response was not JSON */ }
        throw new Error(message);
      }
      const blob = await response.blob();
      const disposition = response.headers.get("Content-Disposition") || "";
      const match = /filename="([^"]+)"/i.exec(disposition);
      const filename = match ? match[1] : `${type}_${options.symbol}.csv`;
      const objectUrl = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = objectUrl;
      link.download = filename;
      document.body.appendChild(link);
      link.click();
      link.remove();
      setTimeout(() => URL.revokeObjectURL(objectUrl), 1500);
      StockApp.showAlert(`Downloaded ${filename}.`, "success");
    } catch (error) {
      StockApp.showAlert(error.message);
    } finally {
      button.innerHTML = originalLabel;
      button.disabled = false;
      if (button.dataset.originalHtml) delete button.dataset.originalHtml;
    }
  }
})();
