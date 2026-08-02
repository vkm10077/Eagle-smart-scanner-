(() => {
    "use strict";

    const config = window.EAGLE_CONFIG || {};

    const state = {
        timeframe: config.initialTimeframe || "3_month",
        results: [],
        filters: {
            sector: "",
            signal: "",
            minimumProbability: ""
        },
        drawerOpen: false
    };

    const elements = {
        tableBody: document.getElementById("signalTableBody"),
        resultCount: document.getElementById("resultCount"),
        signalsUpdatedAt: document.getElementById("signalsUpdatedAt"),
        sectorFilter: document.getElementById("sectorFilter"),
        signalFilter: document.getElementById("signalFilter"),
        probabilityFilter: document.getElementById("probabilityFilter"),
        resetFiltersButton: document.getElementById("resetFiltersButton"),
        timeframeTabs: document.getElementById("timeframeTabs"),
        manualRefreshButton: document.getElementById("manualRefreshButton"),
        drawer: document.getElementById("detailDrawer"),
        drawerTitle: document.getElementById("detailDrawerTitle"),
        drawerContent: document.getElementById("detailDrawerContent"),
        closeDrawerButton: document.getElementById("closeDetailDrawer")
    };

    function escapeHtml(value) {
        return String(value ?? "")
            .replaceAll("&", "&amp;")
            .replaceAll("<", "&lt;")
            .replaceAll(">", "&gt;")
            .replaceAll('"', "&quot;")
            .replaceAll("'", "&#039;");
    }

    function formatPrice(value) {
        const number = Number(value);

        if (!Number.isFinite(number)) {
            return "-";
        }

        return new Intl.NumberFormat(
            "en-IN",
            {
                style: "currency",
                currency: "INR",
                maximumFractionDigits: 2
            }
        ).format(number);
    }

    function formatPercent(value) {
        const number = Number(value);

        if (!Number.isFinite(number)) {
            return "-";
        }

        return `${number.toFixed(2)}%`;
    }

    function formatDate(value) {
        if (!value) {
            return "Waiting for scan";
        }

        const date = new Date(value);

        if (Number.isNaN(date.getTime())) {
            return String(value);
        }

        return new Intl.DateTimeFormat(
            "en-IN",
            {
                dateStyle: "medium",
                timeStyle: "medium",
                timeZone: "Asia/Kolkata"
            }
        ).format(date);
    }

    function signalClass(signal) {
        if (signal === "STRONG BUY") {
            return "strong-buy";
        }

        if (signal === "BUY") {
            return "buy";
        }

        return "no-trade";
    }

    function getFilteredResults() {
        return state.results.filter((item) => {
            if (
                state.filters.sector
                && String(item.sector || "").toLowerCase()
                !== state.filters.sector.toLowerCase()
            ) {
                return false;
            }

            if (
                state.filters.signal
                && String(item.signal || "").toUpperCase()
                !== state.filters.signal
            ) {
                return false;
            }

            if (state.filters.minimumProbability) {
                const minimum = Number(
                    state.filters.minimumProbability
                );

                const probability = Number(
                    item.move_up_probability || 0
                );

                if (
                    Number.isFinite(minimum)
                    && probability < minimum
                ) {
                    return false;
                }
            }

            return true;
        });
    }

    function renderEmptyState(message) {
        elements.tableBody.innerHTML = `
            <tr>
                <td
                    colspan="10"
                    class="empty-state-cell"
                >
                    ${escapeHtml(message)}
                </td>
            </tr>
        `;

        elements.resultCount.textContent = "0 stocks";
    }

    function renderTable() {
        if (!elements.tableBody) {
            return;
        }

        const results = getFilteredResults();

        if (!results.length) {
            renderEmptyState(
                "No verified BUY or STRONG BUY stock matches the selected filters."
            );
            return;
        }

        elements.tableBody.innerHTML = results.map((item) => `
            <tr>
                <td>
                    <strong>
                        ${escapeHtml(item.stock_name || "-")}
                    </strong>
                </td>

                <td>
                    ${escapeHtml(item.sector || "-")}
                </td>

                <td>
                    ${formatPrice(item.current_price)}
                </td>

                <td>
                    ${formatPrice(item.entry_price)}
                </td>

                <td>
                    ${formatPrice(item.stop_loss)}
                </td>

                <td>
                    ${formatPrice(item.target_price)}
                </td>

                <td>
                    ${formatPercent(item.move_up_probability)}
                </td>

                <td>
                    ${escapeHtml(item.holding_period || "-")}
                </td>

                <td>
                    <span class="signal-badge ${signalClass(item.signal)}">
                        ${escapeHtml(item.signal || "NO TRADE")}
                    </span>
                </td>

                <td>
                    <button
                        type="button"
                        class="detail-button"
                        data-symbol="${escapeHtml(item.symbol || "")}"
                    >
                        View Detail
                    </button>
                </td>
            </tr>
        `).join("");

        elements.resultCount.textContent = (
            `${results.length} ${results.length === 1 ? "stock" : "stocks"}`
        );

        bindDetailButtons();
    }

    function renderFilterList(items) {
        if (!Array.isArray(items) || items.length === 0) {
            return `
                <div class="detail-empty">
                    Verified filter data is unavailable.
                </div>
            `;
        }

        return items.map((item) => `
            <article class="detail-filter-row">
                <div>
                    <strong>
                        ${escapeHtml(item.label || item.name || "Filter")}
                    </strong>

                    <p>
                        ${escapeHtml(item.reason || "")}
                    </p>
                </div>

                <div class="detail-filter-meta">
                    <span class="${
                        item.available === false
                            ? "status-unavailable"
                            : item.passed
                                ? "status-pass"
                                : "status-fail"
                    }">
                        ${
                            item.available === false
                                ? "Unavailable"
                                : item.passed
                                    ? "Pass"
                                    : "Fail"
                        }
                    </span>

                    <strong>
                        ${Number(item.score || 0).toFixed(2)}
                    </strong>
                </div>
            </article>
        `).join("");
    }

    function renderPatternList(patternData) {
        const patterns = patternData?.patterns;

        if (!Array.isArray(patterns) || patterns.length === 0) {
            return `
                <div class="detail-empty">
                    Verified pattern data is unavailable.
                </div>
            `;
        }

        return patterns.map((pattern) => `
            <article class="pattern-card ${
                pattern.confirmed
                    ? "confirmed"
                    : pattern.detected
                        ? "detected"
                        : ""
            }">
                <div>
                    <strong>
                        ${escapeHtml(pattern.label || pattern.name)}
                    </strong>

                    <p>
                        ${escapeHtml(pattern.reason || "")}
                    </p>
                </div>

                <div class="pattern-card-meta">
                    <span>
                        ${
                            pattern.confirmed
                                ? "Confirmed"
                                : pattern.detected
                                    ? "Detected"
                                    : "Not Detected"
                        }
                    </span>

                    <strong>
                        ${Number(pattern.score || 0).toFixed(2)}
                    </strong>
                </div>
            </article>
        `).join("");
    }

    function renderRejectionReasons(reasons) {
        if (!Array.isArray(reasons) || reasons.length === 0) {
            return "";
        }

        return `
            <section class="detail-section danger-section">
                <div class="detail-section-heading">
                    <h3>
                        Rejection Reasons
                    </h3>
                </div>

                <ul class="reason-list">
                    ${reasons.map((reason) => `
                        <li>
                            ${escapeHtml(reason)}
                        </li>
                    `).join("")}
                </ul>
            </section>
        `;
    }

    function renderDetail(data) {
        if (!data || typeof data !== "object") {
            elements.drawerContent.innerHTML = `
                <div class="detail-error">
                    Verified stock research is unavailable.
                </div>
            `;
            return;
        }

        const technical = data.technical || {};
        const fundamental = data.fundamental || {};
        const pattern = data.pattern || {};
        const sector = data.sector_analysis || {};
        const probability = data.probability || {};

        elements.drawerTitle.textContent = (
            data.stock_name || data.symbol || "Stock Detail"
        );

        elements.drawerContent.innerHTML = `
            <section class="detail-summary-grid">
                <article class="detail-summary-card">
                    <span>
                        Signal
                    </span>

                    <strong class="signal-badge ${signalClass(data.signal)}">
                        ${escapeHtml(data.signal || "NO TRADE")}
                    </strong>
                </article>

                <article class="detail-summary-card">
                    <span>
                        Probability
                    </span>

                    <strong>
                        ${formatPercent(data.move_up_probability)}
                    </strong>
                </article>

                <article class="detail-summary-card">
                    <span>
                        Current Price
                    </span>

                    <strong>
                        ${formatPrice(data.current_price)}
                    </strong>
                </article>

                <article class="detail-summary-card">
                    <span>
                        Entry Price
                    </span>

                    <strong>
                        ${formatPrice(data.entry_price)}
                    </strong>
                </article>

                <article class="detail-summary-card">
                    <span>
                        Stop Loss
                    </span>

                    <strong>
                        ${formatPrice(data.stop_loss)}
                    </strong>
                </article>

                <article class="detail-summary-card">
                    <span>
                        Target Price
                    </span>

                    <strong>
                        ${formatPrice(data.target_price)}
                    </strong>
                </article>

                <article class="detail-summary-card">
                    <span>
                        Risk:Reward
                    </span>

                    <strong>
                        ${
                            Number.isFinite(Number(data.risk_reward))
                                ? `1:${Number(data.risk_reward).toFixed(2)}`
                                : "-"
                        }
                    </strong>
                </article>

                <article class="detail-summary-card">
                    <span>
                        Holding Period
                    </span>

                    <strong>
                        ${escapeHtml(data.holding_period || "-")}
                    </strong>
                </article>
            </section>

            ${renderRejectionReasons(data.rejection_reasons)}

            <section class="detail-section">
                <div class="detail-section-heading">
                    <div>
                        <p class="eyebrow">
                            TECHNICAL
                        </p>

                        <h3>
                            Top 10 Technical Filters
                        </h3>
                    </div>

                    <strong>
                        Score ${Number(technical.score || 0).toFixed(2)}
                    </strong>
                </div>

                <div class="detail-filter-list">
                    ${renderFilterList(technical.filters)}
                </div>
            </section>

            <section class="detail-section">
                <div class="detail-section-heading">
                    <div>
                        <p class="eyebrow">
                            FUNDAMENTAL
                        </p>

                        <h3>
                            Top 10 Fundamental Filters
                        </h3>
                    </div>

                    <strong>
                        Score ${Number(fundamental.score || 0).toFixed(2)}
                    </strong>
                </div>

                <div class="detail-filter-list">
                    ${renderFilterList(fundamental.filters)}
                </div>
            </section>

            <section class="detail-section">
                <div class="detail-section-heading">
                    <div>
                        <p class="eyebrow">
                            CHART PATTERNS
                        </p>

                        <h3>
                            Top 10 Pattern Analysis
                        </h3>
                    </div>

                    <strong>
                        Score ${Number(pattern.score || 0).toFixed(2)}
                    </strong>
                </div>

                <div class="pattern-grid">
                    ${renderPatternList(pattern)}
                </div>
            </section>

            <section class="detail-section">
                <div class="detail-section-heading">
                    <div>
                        <p class="eyebrow">
                            SECTOR
                        </p>

                        <h3>
                            Sector Strength
                        </h3>
                    </div>

                    <strong>
                        Score ${Number(sector.score || 0).toFixed(2)}
                    </strong>
                </div>

                <div class="detail-stat-grid">
                    <article>
                        <span>
                            Sector
                        </span>

                        <strong>
                            ${escapeHtml(data.sector || "-")}
                        </strong>
                    </article>

                    <article>
                        <span>
                            Stock Return
                        </span>

                        <strong>
                            ${formatPercent(sector.stock_return)}
                        </strong>
                    </article>

                    <article>
                        <span>
                            Sector Return
                        </span>

                        <strong>
                            ${formatPercent(sector.sector_return)}
                        </strong>
                    </article>

                    <article>
                        <span>
                            Nifty Return
                        </span>

                        <strong>
                            ${formatPercent(sector.nifty_return)}
                        </strong>
                    </article>
                </div>

                <p class="detail-reason">
                    ${escapeHtml(
                        sector.reason
                        || "Verified sector analysis is unavailable."
                    )}
                </p>
            </section>

            <section class="detail-section">
                <div class="detail-section-heading">
                    <div>
                        <p class="eyebrow">
                            PROBABILITY
                        </p>

                        <h3>
                            Final Research Score
                        </h3>
                    </div>

                    <strong>
                        ${formatPercent(probability.move_up_probability)}
                    </strong>
                </div>

                <div class="detail-stat-grid">
                    <article>
                        <span>
                            Overall Score
                        </span>

                        <strong>
                            ${Number(probability.overall_score || 0).toFixed(2)}
                        </strong>
                    </article>

                    <article>
                        <span>
                            Confidence
                        </span>

                        <strong>
                            ${Number(probability.confidence_score || 0).toFixed(2)}
                        </strong>
                    </article>

                    <article>
                        <span>
                            Data Completeness
                        </span>

                        <strong>
                            ${formatPercent(probability.data_completeness)}
                        </strong>
                    </article>

                    <article>
                        <span>
                            Verified
                        </span>

                        <strong>
                            ${data.verified ? "Yes" : "No"}
                        </strong>
                    </article>
                </div>
            </section>
        `;
    }

    function openDrawer() {
        state.drawerOpen = true;

        elements.drawer.classList.add("open");
        elements.drawer.setAttribute(
            "aria-hidden",
            "false"
        );

        document.body.style.overflow = "hidden";
    }

    function closeDrawer() {
        state.drawerOpen = false;

        elements.drawer.classList.remove("open");
        elements.drawer.setAttribute(
            "aria-hidden",
            "true"
        );

        document.body.style.overflow = "";
    }

    async function loadStockDetail(symbol) {
        if (!symbol) {
            return;
        }

        openDrawer();

        elements.drawerTitle.textContent = symbol;

        elements.drawerContent.innerHTML = `
            <div class="detail-loading">
                Loading verified research...
            </div>
        `;

        try {
            const endpoint = (
                `${config.api.stockDetailBase}${encodeURIComponent(symbol)}`
            );

            const url = new URL(
                endpoint,
                window.location.origin
            );

            url.searchParams.set(
                "timeframe",
                state.timeframe
            );

            const response = await fetch(
                url.toString(),
                {
                    credentials: "same-origin",
                    headers: {
                        "Accept": "application/json"
                    }
                }
            );

            const payload = await response.json();

            if (!response.ok || !payload.success) {
                throw new Error(
                    payload.error
                    || "Stock research could not be loaded."
                );
            }

            renderDetail(payload.stock);

        } catch (error) {
            elements.drawerContent.innerHTML = `
                <div class="detail-error">
                    ${escapeHtml(error.message)}
                </div>
            `;
        }
    }

    function bindDetailButtons() {
        document.querySelectorAll(
            ".detail-button"
        ).forEach((button) => {
            button.addEventListener(
                "click",
                () => loadStockDetail(
                    button.dataset.symbol
                )
            );
        });
    }

    async function fetchSignals() {
        const url = new URL(
            config.api.signals,
            window.location.origin
        );

        url.searchParams.set(
            "timeframe",
            state.timeframe
        );

        try {
            const response = await fetch(
                url.toString(),
                {
                    credentials: "same-origin",
                    headers: {
                        "Accept": "application/json"
                    }
                }
            );

            const payload = await response.json();

            if (!response.ok || !payload.success) {
                throw new Error(
                    payload.error
                    || "Signals could not be loaded."
                );
            }

            state.results = Array.isArray(payload.results)
                ? payload.results
                : [];

            elements.signalsUpdatedAt.textContent = (
                formatDate(payload.generated_at)
            );

            renderTable();

            window.dispatchEvent(
                new CustomEvent(
                    "eagle:scanner-status",
                    {
                        detail: payload.scanner_status || {}
                    }
                )
            );

            return payload;

        } catch (error) {
            renderEmptyState(error.message);
            throw error;
        }
    }

    async function triggerManualRefresh() {
        if (!elements.manualRefreshButton) {
            return;
        }

        elements.manualRefreshButton.disabled = true;
        elements.manualRefreshButton.textContent = "Starting...";

        try {
            const response = await fetch(
                config.api.scanRefresh,
                {
                    method: "POST",
                    credentials: "same-origin",
                    headers: {
                        "Accept": "application/json",
                        "Content-Type": "application/json"
                    },
                    body: JSON.stringify({
                        timeframe: state.timeframe
                    })
                }
            );

            const payload = await response.json();

            if (!response.ok || !payload.success) {
                throw new Error(
                    payload.error
                    || "Scanner could not be started."
                );
            }

            window.dispatchEvent(
                new CustomEvent(
                    "eagle:scanner-status",
                    {
                        detail: payload.scanner || {}
                    }
                )
            );

        } catch (error) {
            window.alert(error.message);

        } finally {
            elements.manualRefreshButton.disabled = false;
            elements.manualRefreshButton.textContent = "Refresh Scan";
        }
    }

    function setActiveTimeframe(timeframe) {
        state.timeframe = timeframe;

        document.querySelectorAll(
            ".timeframe-tab"
        ).forEach((button) => {
            button.classList.toggle(
                "active",
                button.dataset.timeframe === timeframe
            );
        });

        const url = new URL(
            window.location.href
        );

        url.searchParams.set(
            "timeframe",
            timeframe
        );

        window.history.replaceState(
            {},
            "",
            url.toString()
        );

        fetchSignals().catch(() => {});
    }

    function bindFilters() {
        elements.sectorFilter?.addEventListener(
            "change",
            (event) => {
                state.filters.sector = event.target.value;
                renderTable();
            }
        );

        elements.signalFilter?.addEventListener(
            "change",
            (event) => {
                state.filters.signal = event.target.value;
                renderTable();
            }
        );

        elements.probabilityFilter?.addEventListener(
            "change",
            (event) => {
                state.filters.minimumProbability = event.target.value;
                renderTable();
            }
        );

        elements.resetFiltersButton?.addEventListener(
            "click",
            () => {
                state.filters = {
                    sector: "",
                    signal: "",
                    minimumProbability: ""
                };

                elements.sectorFilter.value = "";
                elements.signalFilter.value = "";
                elements.probabilityFilter.value = "";

                renderTable();
            }
        );
    }

    function bindTimeframes() {
        elements.timeframeTabs?.addEventListener(
            "click",
            (event) => {
                const button = event.target.closest(
                    ".timeframe-tab"
                );

                if (!button) {
                    return;
                }

                setActiveTimeframe(
                    button.dataset.timeframe
                );
            }
        );
    }

    function bindDrawer() {
        elements.closeDrawerButton?.addEventListener(
            "click",
            closeDrawer
        );

        elements.drawer?.querySelector(
            ".detail-drawer-backdrop"
        )?.addEventListener(
            "click",
            closeDrawer
        );

        document.addEventListener(
            "keydown",
            (event) => {
                if (
                    event.key === "Escape"
                    && state.drawerOpen
                ) {
                    closeDrawer();
                }
            }
        );
    }

    function initialize() {
        bindFilters();
        bindTimeframes();
        bindDrawer();
        bindDetailButtons();

        elements.manualRefreshButton?.addEventListener(
            "click",
            triggerManualRefresh
        );

        fetchSignals().catch(() => {});
    }

    window.EagleDashboard = {
        state,
        fetchSignals,
        loadStockDetail,
        renderTable
    };

    document.addEventListener(
        "DOMContentLoaded",
        initialize
    );
})();
