(() => {
    "use strict";

    const config = window.EAGLE_CONFIG || {};

    const state = {
        mode: (
            config.initialMode
            || config.initialTimeframe
            || "swing"
        ),

        results: [],

        topSectors: [],

        filters: {
            sector: "",
            minimumTechnicalScore: "",
            chartPattern: ""
        },

        drawerOpen: false
    };


    const elements = {
        tableBody: document.getElementById(
            "signalTableBody"
        ),

        resultCount: document.getElementById(
            "resultCount"
        ),

        signalsUpdatedAt: document.getElementById(
            "signalsUpdatedAt"
        ),

        sectorFilter: document.getElementById(
            "sectorFilter"
        ),

        technicalScoreFilter: document.getElementById(
            "technicalScoreFilter"
        ),

        patternFilter: document.getElementById(
            "patternFilter"
        ),

        resetFiltersButton: document.getElementById(
            "resetFiltersButton"
        ),

        timeframeTabs: document.getElementById(
            "timeframeTabs"
        ),

        manualRefreshButton: document.getElementById(
            "manualRefreshButton"
        ),

        drawer: document.getElementById(
            "detailDrawer"
        ),

        drawerTitle: document.getElementById(
            "detailDrawerTitle"
        ),

        drawerContent: document.getElementById(
            "detailDrawerContent"
        ),

        closeDrawerButton: document.getElementById(
            "closeDetailDrawer"
        ),

        topSectorGrid: document.getElementById(
            "topSectorGrid"
        ),

        scannerStatusText: document.getElementById(
            "scannerStatusText"
        ),

        scannerProgressBar: document.getElementById(
            "scannerProgressBar"
        ),

        scannerStage: document.getElementById(
            "scannerStage"
        ),

        sectorCount: document.getElementById(
            "sectorCount"
        ),

        candidateCount: document.getElementById(
            "candidateCount"
        ),

        commonCount: document.getElementById(
            "commonCount"
        ),

        strongBuyCount: document.getElementById(
            "strongBuyCount"
        )
    };


    // =========================================================
    // HELPERS
    // =========================================================

    function escapeHtml(value) {
        return String(
            value ?? ""
        )
            .replaceAll("&", "&amp;")
            .replaceAll("<", "&lt;")
            .replaceAll(">", "&gt;")
            .replaceAll('"', "&quot;")
            .replaceAll("'", "&#039;");
    }


    function safeNumber(
        value,
        defaultValue = 0
    ) {
        const number = Number(value);

        return Number.isFinite(number)
            ? number
            : defaultValue;
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


    function formatNumber(
        value,
        digits = 2
    ) {
        const number = Number(value);

        if (!Number.isFinite(number)) {
            return "-";
        }

        return number.toFixed(digits);
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

        if (Number.isNaN(
            date.getTime()
        )) {
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


    function normalizeMode(value) {
        const mode = String(
            value || ""
        )
            .trim()
            .toLowerCase();

        if (
            mode === "intraday"
            || mode === "swing"
        ) {
            return mode;
        }

        return "swing";
    }


    function signalClass(signal) {
        return (
            String(signal || "")
                .toUpperCase()
            === "STRONG BUY"
        )
            ? "strong-buy"
            : "no-trade";
    }


    // =========================================================
    // FILTERING
    // =========================================================

    function getFilteredResults() {
        return state.results.filter(
            (item) => {

                if (
                    String(
                        item.signal || ""
                    ).toUpperCase()
                    !== "STRONG BUY"
                ) {
                    return false;
                }

                if (
                    state.filters.sector
                    && String(
                        item.sector || ""
                    ).toLowerCase()
                    !== state.filters.sector
                        .toLowerCase()
                ) {
                    return false;
                }

                if (
                    state.filters
                        .minimumTechnicalScore
                ) {
                    const minimum = Number(
                        state.filters
                            .minimumTechnicalScore
                    );

                    const score = Number(
                        item.technical_score || 0
                    );

                    if (
                        Number.isFinite(
                            minimum
                        )
                        && score < minimum
                    ) {
                        return false;
                    }
                }

                if (
                    state.filters.chartPattern
                ) {
                    const selectedPattern = (
                        state.filters
                            .chartPattern
                            .toLowerCase()
                    );

                    const itemPattern = String(
                        item.chart_pattern || ""
                    ).toLowerCase();

                    if (
                        itemPattern
                        !== selectedPattern
                    ) {
                        return false;
                    }
                }

                return true;
            }
        );
    }


    // =========================================================
    // TABLE
    // =========================================================

    function renderEmptyState(
        message
    ) {
        if (!elements.tableBody) {
            return;
        }

        elements.tableBody.innerHTML = `
            <tr>
                <td
                    colspan="12"
                    class="empty-state-cell"
                >
                    ${escapeHtml(message)}
                </td>
            </tr>
        `;

        if (elements.resultCount) {
            elements.resultCount.textContent =
                "0 stocks";
        }
    }


    function renderTable() {
        if (!elements.tableBody) {
            return;
        }

        const results = (
            getFilteredResults()
        );

        if (!results.length) {
            renderEmptyState(
                "No confirmed Strong Buy setup matches the selected filters."
            );

            return;
        }

        elements.tableBody.innerHTML = (
            results.map(
                (item) => `
                    <tr>

                        <td>
                            <strong>
                                ${escapeHtml(
                                    item.company_name
                                    || item.stock_name
                                    || item.symbol
                                    || "-"
                                )}
                            </strong>

                            <small>
                                ${escapeHtml(
                                    item.symbol || ""
                                )}
                            </small>
                        </td>


                        <td>
                            ${escapeHtml(
                                item.sector || "-"
                            )}
                        </td>


                        <td>
                            ${formatPrice(
                                item.current_price
                            )}
                        </td>


                        <td>
                            ${formatPrice(
                                item.entry_price
                            )}
                        </td>


                        <td>
                            ${formatPrice(
                                item.stop_loss
                            )}
                        </td>


                        <td>
                            ${formatPrice(
                                item.target_price
                            )}
                        </td>


                        <td>
                            ${
                                Number.isFinite(
                                    Number(
                                        item.risk_reward
                                    )
                                )
                                    ? `1:${Number(
                                        item.risk_reward
                                    ).toFixed(2)}`
                                    : "-"
                            }
                        </td>


                        <td>
                            <strong
                                class="technical-score"
                            >
                                ${formatNumber(
                                    item.technical_score
                                )}
                            </strong>
                        </td>


                        <td>
                            ${escapeHtml(
                                item.chart_pattern
                                || "—"
                            )}
                        </td>


                        <td>
                            ${escapeHtml(
                                item.candlestick_pattern
                                || "—"
                            )}
                        </td>


                        <td>
                            <span
                                class="signal-badge strong-buy"
                            >
                                STRONG BUY
                            </span>
                        </td>


                        <td>
                            <button
                                type="button"
                                class="detail-button"
                                data-symbol="${escapeHtml(
                                    item.symbol || ""
                                )}"
                            >
                                View
                            </button>
                        </td>

                    </tr>
                `
            ).join("")
        );

        if (elements.resultCount) {
            elements.resultCount.textContent = (
                `${results.length} ${
                    results.length === 1
                        ? "stock"
                        : "stocks"
                }`
            );
        }

        bindDetailButtons();
    }


    // =========================================================
    // TOP SECTORS
    // =========================================================

    function renderTopSectors(
        sectors
    ) {
        if (!elements.topSectorGrid) {
            return;
        }

        if (
            !Array.isArray(sectors)
            || sectors.length === 0
        ) {
            elements.topSectorGrid.innerHTML = `
                <div class="empty-sector-state">
                    Top sectors will appear after the technical scan.
                </div>
            `;

            return;
        }

        elements.topSectorGrid.innerHTML = (
            sectors.map(
                (
                    item,
                    index
                ) => `
                    <div class="top-sector-card">

                        <div>
                            <strong>
                                ${index + 1}.
                                ${escapeHtml(
                                    item.sector || "-"
                                )}
                            </strong>

                            <span>
                                Technical Strength
                            </span>
                        </div>

                        <div class="sector-score">
                            ${formatNumber(
                                item.score
                            )}
                        </div>

                    </div>
                `
            ).join("")
        );
    }


    // =========================================================
    // SCANNER STATUS
    // =========================================================

    function renderScannerStatus(
        scanner
    ) {
        const status = (
            scanner
            && typeof scanner
                === "object"
        )
            ? scanner
            : {};

        const running = Boolean(
            status.running
        );

        if (elements.scannerStatusText) {
            elements.scannerStatusText.textContent =
                running
                    ? "Running"
                    : (
                        status.stage === "failed"
                            ? "Failed"
                            : "Ready"
                    );
        }

        if (elements.scannerProgressBar) {
            const progress = Math.max(
                0,
                Math.min(
                    100,
                    safeNumber(
                        status.progress_percent,
                        0
                    )
                )
            );

            elements.scannerProgressBar.style.width =
                `${progress}%`;
        }

        if (elements.scannerStage) {
            elements.scannerStage.textContent = (
                status.stage || "idle"
            );
        }

        if (elements.sectorCount) {
            elements.sectorCount.textContent = (
                safeNumber(
                    status.sector_count,
                    0
                )
            );
        }

        if (elements.candidateCount) {
            elements.candidateCount.textContent = (
                safeNumber(
                    status.candidate_count,
                    0
                )
            );
        }

        if (elements.commonCount) {
            elements.commonCount.textContent = (
                safeNumber(
                    status.common_count,
                    0
                )
            );
        }

        if (elements.strongBuyCount) {
            elements.strongBuyCount.textContent = (
                safeNumber(
                    status.strong_buy_count,
                    0
                )
            );
        }
    }


    // =========================================================
    // DETAIL HELPERS
    // =========================================================

    function renderBooleanStatus(
        value
    ) {
        return value
            ? `
                <span class="status-pass">
                    Pass
                </span>
            `
            : `
                <span class="status-fail">
                    Fail
                </span>
            `;
    }


    function renderReasons(
        reasons
    ) {
        if (
            !Array.isArray(reasons)
            || reasons.length === 0
        ) {
            return `
                <div class="detail-empty">
                    No bullish confirmations recorded.
                </div>
            `;
        }

        return `
            <ul class="reason-list">
                ${reasons.map(
                    (reason) => `
                        <li>
                            ${escapeHtml(reason)}
                        </li>
                    `
                ).join("")}
            </ul>
        `;
    }


    function renderRejectedReasons(
        reasons
    ) {
        if (
            !Array.isArray(reasons)
            || reasons.length === 0
        ) {
            return "";
        }

        return `
            <section
                class="detail-section danger-section"
            >
                <div
                    class="detail-section-heading"
                >
                    <div>
                        <p class="eyebrow">
                            FAILED CONDITIONS
                        </p>

                        <h3>
                            Rejection Reasons
                        </h3>
                    </div>
                </div>

                <ul class="reason-list">
                    ${reasons.map(
                        (reason) => `
                            <li>
                                ${escapeHtml(
                                    reason
                                )}
                            </li>
                        `
                    ).join("")}
                </ul>
            </section>
        `;
    }


    // =========================================================
    // STOCK DETAIL
    // =========================================================

    function renderDetail(
        data
    ) {
        if (
            !data
            || typeof data !== "object"
        ) {
            elements.drawerContent.innerHTML = `
                <div class="detail-error">
                    Verified technical analysis is unavailable.
                </div>
            `;

            return;
        }

        const companyName = (
            data.company_name
            || data.stock_name
            || data.symbol
            || "Stock Detail"
        );

        elements.drawerTitle.textContent =
            companyName;

        elements.drawerContent.innerHTML = `

            <section class="detail-summary-grid">

                <article class="detail-summary-card">
                    <span>
                        Signal
                    </span>

                    <strong
                        class="signal-badge ${signalClass(
                            data.signal
                        )}"
                    >
                        ${escapeHtml(
                            data.signal
                            || "NO SIGNAL"
                        )}
                    </strong>
                </article>


                <article class="detail-summary-card">
                    <span>
                        Trading Mode
                    </span>

                    <strong>
                        ${escapeHtml(
                            data.mode
                            || state.mode
                        )}
                    </strong>
                </article>


                <article class="detail-summary-card">
                    <span>
                        Current Price
                    </span>

                    <strong>
                        ${formatPrice(
                            data.current_price
                        )}
                    </strong>
                </article>


                <article class="detail-summary-card">
                    <span>
                        Entry Price
                    </span>

                    <strong>
                        ${formatPrice(
                            data.entry_price
                        )}
                    </strong>
                </article>


                <article class="detail-summary-card">
                    <span>
                        Stop Loss
                    </span>

                    <strong>
                        ${formatPrice(
                            data.stop_loss
                        )}
                    </strong>
                </article>


                <article class="detail-summary-card">
                    <span>
                        Target
                    </span>

                    <strong>
                        ${formatPrice(
                            data.target_price
                        )}
                    </strong>
                </article>


                <article class="detail-summary-card">
                    <span>
                        Technical Score
                    </span>

                    <strong>
                        ${formatNumber(
                            data.technical_score
                        )}
                    </strong>
                </article>


                <article class="detail-summary-card">
                    <span>
                        Confirmations
                    </span>

                    <strong>
                        ${safeNumber(
                            data.confirmations,
                            0
                        )}
                    </strong>
                </article>


                <article class="detail-summary-card">
                    <span>
                        Risk:Reward
                    </span>

                    <strong>
                        ${
                            Number.isFinite(
                                Number(
                                    data.risk_reward
                                )
                            )
                                ? `1:${Number(
                                    data.risk_reward
                                ).toFixed(2)}`
                                : "-"
                        }
                    </strong>
                </article>


                <article class="detail-summary-card">
                    <span>
                        Eagle Qualified
                    </span>

                    <strong>
                        ${
                            data
                                .qualified_for_eagle_scanner
                            || String(
                                data.signal || ""
                            ).toUpperCase()
                                === "STRONG BUY"
                                ? "YES"
                                : "NO"
                        }
                    </strong>
                </article>

            </section>


            ${renderRejectedReasons(
                data.rejected_reasons
            )}


            <section class="detail-section">

                <div class="detail-section-heading">
                    <div>
                        <p class="eyebrow">
                            TREND & MOMENTUM
                        </p>

                        <h3>
                            Technical Conditions
                        </h3>
                    </div>
                </div>


                <div class="detail-stat-grid">

                    <article>
                        <span>
                            EMA Structure
                        </span>

                        <strong>
                            ${renderBooleanStatus(
                                data.ema_bullish
                            )}
                        </strong>
                    </article>


                    <article>
                        <span>
                            RSI
                        </span>

                        <strong>
                            ${formatNumber(
                                data.rsi
                            )}
                        </strong>
                    </article>


                    <article>
                        <span>
                            MACD
                        </span>

                        <strong>
                            ${renderBooleanStatus(
                                data.macd_bullish
                            )}
                        </strong>
                    </article>


                    <article>
                        <span>
                            Supertrend
                        </span>

                        <strong>
                            ${renderBooleanStatus(
                                data.supertrend_bullish
                            )}
                        </strong>
                    </article>


                    <article>
                        <span>
                            Above VWAP
                        </span>

                        <strong>
                            ${renderBooleanStatus(
                                data.above_vwap
                            )}
                        </strong>
                    </article>


                    <article>
                        <span>
                            Volume Ratio
                        </span>

                        <strong>
                            ${formatNumber(
                                data.volume_ratio
                            )}x
                        </strong>
                    </article>


                    <article>
                        <span>
                            Volume Confirmed
                        </span>

                        <strong>
                            ${renderBooleanStatus(
                                data.volume_confirmed
                            )}
                        </strong>
                    </article>


                    <article>
                        <span>
                            Breakout
                        </span>

                        <strong>
                            ${renderBooleanStatus(
                                data.breakout
                            )}
                        </strong>
                    </article>


                    <article>
                        <span>
                            Price Action
                        </span>

                        <strong>
                            ${renderBooleanStatus(
                                data.price_action_bullish
                            )}
                        </strong>
                    </article>


                    <article>
                        <span>
                            Relative Strength
                        </span>

                        <strong>
                            ${formatPercent(
                                data.relative_strength_pct
                            )}
                        </strong>
                    </article>

                </div>
            </section>


            <section class="detail-section">

                <div class="detail-section-heading">
                    <div>
                        <p class="eyebrow">
                            CHART PATTERN
                        </p>

                        <h3>
                            Pattern Analysis
                        </h3>
                    </div>

                    <strong>
                        Score
                        ${formatNumber(
                            data.chart_pattern_score
                        )}
                    </strong>
                </div>


                <div class="detail-stat-grid">

                    <article>
                        <span>
                            Strongest Pattern
                        </span>

                        <strong>
                            ${escapeHtml(
                                data.chart_pattern
                                || "Not detected"
                            )}
                        </strong>
                    </article>


                    <article>
                        <span>
                            Confirmed
                        </span>

                        <strong>
                            ${renderBooleanStatus(
                                data.chart_pattern_confirmed
                            )}
                        </strong>
                    </article>


                    <article>
                        <span>
                            Breakout Level
                        </span>

                        <strong>
                            ${formatPrice(
                                data.breakout_price
                            )}
                        </strong>
                    </article>

                </div>
            </section>


            <section class="detail-section">

                <div class="detail-section-heading">
                    <div>
                        <p class="eyebrow">
                            CANDLESTICK
                        </p>

                        <h3>
                            Bullish Candlestick Pattern
                        </h3>
                    </div>
                </div>


                <div class="detail-stat-grid">

                    <article>
                        <span>
                            Pattern
                        </span>

                        <strong>
                            ${escapeHtml(
                                data.candlestick_pattern
                                || "Not detected"
                            )}
                        </strong>
                    </article>


                    <article>
                        <span>
                            Confirmed
                        </span>

                        <strong>
                            ${renderBooleanStatus(
                                data.candlestick_confirmed
                            )}
                        </strong>
                    </article>

                </div>
            </section>


            <section class="detail-section">

                <div class="detail-section-heading">
                    <div>
                        <p class="eyebrow">
                            CONFIRMATIONS
                        </p>

                        <h3>
                            Why This Setup
                        </h3>
                    </div>
                </div>

                ${renderReasons(
                    data.reasons
                )}
            </section>


            <section class="detail-section">

                <div class="detail-section-heading">
                    <div>
                        <p class="eyebrow">
                            DATA
                        </p>

                        <h3>
                            Market Data Status
                        </h3>
                    </div>
                </div>


                <div class="detail-stat-grid">

                    <article>
                        <span>
                            Sector
                        </span>

                        <strong>
                            ${escapeHtml(
                                data.sector || "-"
                            )}
                        </strong>
                    </article>


                    <article>
                        <span>
                            Primary Timeframe
                        </span>

                        <strong>
                            ${escapeHtml(
                                data.primary_resolution
                                || "-"
                            )}
                        </strong>
                    </article>


                    <article>
                        <span>
                            Confirmation
                        </span>

                        <strong>
                            ${escapeHtml(
                                data.confirmation_resolution
                                || "-"
                            )}
                        </strong>
                    </article>


                    <article>
                        <span>
                            Verified
                        </span>

                        <strong>
                            ${
                                data.verified
                                    ? "YES"
                                    : "NO"
                            }
                        </strong>
                    </article>

                </div>
            </section>
        `;
    }


    // =========================================================
    // DRAWER
    // =========================================================

    function openDrawer() {
        state.drawerOpen = true;

        elements.drawer?.classList.add(
            "open"
        );

        elements.drawer?.setAttribute(
            "aria-hidden",
            "false"
        );

        document.body.style.overflow =
            "hidden";
    }


    function closeDrawer() {
        state.drawerOpen = false;

        elements.drawer?.classList.remove(
            "open"
        );

        elements.drawer?.setAttribute(
            "aria-hidden",
            "true"
        );

        document.body.style.overflow = "";
    }


    // =========================================================
    // STOCK DETAIL REQUEST
    // =========================================================

    async function loadStockDetail(
        symbol
    ) {
        if (!symbol) {
            return;
        }

        openDrawer();

        if (elements.drawerTitle) {
            elements.drawerTitle.textContent =
                symbol;
        }

        if (elements.drawerContent) {
            elements.drawerContent.innerHTML = `
                <div class="detail-loading">
                    Loading verified technical analysis...
                </div>
            `;
        }

        try {

            const endpoint = (
                `${config.api.stockDetailBase}${encodeURIComponent(
                    symbol
                )}`
            );

            const url = new URL(
                endpoint,
                window.location.origin
            );

            url.searchParams.set(
                "mode",
                state.mode
            );

            const response = await fetch(
                url.toString(),
                {
                    credentials: "same-origin",

                    headers: {
                        "Accept":
                            "application/json"
                    }
                }
            );

            const payload =
                await response.json();

            if (
                !response.ok
                || !payload.success
            ) {
                throw new Error(
                    payload.error
                    || (
                        "Technical analysis "
                        + "could not be loaded."
                    )
                );
            }

            renderDetail(
                payload.stock
            );

        } catch (error) {

            elements.drawerContent.innerHTML = `
                <div class="detail-error">
                    ${escapeHtml(
                        error.message
                    )}
                </div>
            `;
        }
    }


    function bindDetailButtons() {
        document.querySelectorAll(
            ".detail-button"
        ).forEach(
            (button) => {

                button.addEventListener(
                    "click",
                    () => (
                        loadStockDetail(
                            button.dataset.symbol
                        )
                    )
                );
            }
        );
    }


    // =========================================================
    // SIGNALS
    // =========================================================

    async function fetchSignals() {
        const url = new URL(
            config.api.signals,
            window.location.origin
        );

        url.searchParams.set(
            "mode",
            state.mode
        );

        try {

            const response = await fetch(
                url.toString(),
                {
                    credentials: "same-origin",

                    headers: {
                        "Accept":
                            "application/json"
                    }
                }
            );

            const payload =
                await response.json();

            if (
                !response.ok
                || !payload.success
            ) {
                throw new Error(
                    payload.error
                    || "Signals could not be loaded."
                );
            }

            state.results = (
                Array.isArray(
                    payload.results
                )
                    ? payload.results
                    : []
            );

            state.topSectors = (
                Array.isArray(
                    payload.top_sectors
                )
                    ? payload.top_sectors
                    : []
            );

            renderTable();

            renderTopSectors(
                state.topSectors
            );

            if (
                elements.signalsUpdatedAt
            ) {
                elements
                    .signalsUpdatedAt
                    .textContent = (
                        formatDate(
                            payload.generated_at
                        )
                    );
            }

            if (elements.sectorCount) {
                elements
                    .sectorCount
                    .textContent = (
                        state.topSectors.length
                    );
            }

            if (elements.candidateCount) {
                elements
                    .candidateCount
                    .textContent = (
                        safeNumber(
                            payload.candidate_count,
                            0
                        )
                    );
            }

            if (elements.commonCount) {
                elements
                    .commonCount
                    .textContent = (
                        safeNumber(
                            payload.common_count,
                            0
                        )
                    );
            }

            if (elements.strongBuyCount) {
                elements
                    .strongBuyCount
                    .textContent = (
                        safeNumber(
                            payload.strong_buy_count,
                            state.results.length
                        )
                    );
            }

            renderScannerStatus(
                payload.scanner_status
                || {}
            );

            window.dispatchEvent(
                new CustomEvent(
                    "eagle:scanner-status",
                    {
                        detail: (
                            payload
                                .scanner_status
                            || {}
                        )
                    }
                )
            );

            return payload;

        } catch (error) {

            renderEmptyState(
                error.message
            );

            throw error;
        }
    }


    // =========================================================
    // MANUAL REFRESH
    // =========================================================

    async function triggerManualRefresh() {
        if (
            !elements.manualRefreshButton
        ) {
            return;
        }

        elements.manualRefreshButton.disabled =
            true;

        elements.manualRefreshButton.textContent =
            "Starting...";

        try {

            const response = await fetch(
                config.api.scanRefresh,
                {
                    method: "POST",

                    credentials:
                        "same-origin",

                    headers: {
                        "Accept":
                            "application/json",

                        "Content-Type":
                            "application/json"
                    },

                    body: JSON.stringify(
                        {
                            mode: state.mode
                        }
                    )
                }
            );

            const payload =
                await response.json();

            if (
                !response.ok
                || !payload.success
            ) {
                throw new Error(
                    payload.error
                    || (
                        "Scanner could not "
                        + "be started."
                    )
                );
            }

            renderScannerStatus(
                payload.scanner
                || {}
            );

            window.dispatchEvent(
                new CustomEvent(
                    "eagle:scanner-status",
                    {
                        detail: (
                            payload.scanner
                            || {}
                        )
                    }
                )
            );

        } catch (error) {

            window.alert(
                error.message
            );

        } finally {

            elements
                .manualRefreshButton
                .disabled = false;

            elements
                .manualRefreshButton
                .textContent =
                    "Refresh Scan";
        }
    }


    // =========================================================
    // MODE CHANGE
    // =========================================================

    function setActiveMode(
        mode
    ) {
        const normalizedMode =
            normalizeMode(mode);

        state.mode = normalizedMode;

        document.querySelectorAll(
            ".timeframe-tab"
        ).forEach(
            (button) => {

                const buttonMode = (
                    button.dataset.mode
                    || button.dataset.timeframe
                );

                button.classList.toggle(
                    "active",
                    buttonMode
                        === normalizedMode
                );
            }
        );

        const url = new URL(
            window.location.href
        );

        url.searchParams.set(
            "mode",
            normalizedMode
        );

        url.searchParams.delete(
            "timeframe"
        );

        window.history.replaceState(
            {},
            "",
            url.toString()
        );

        fetchSignals().catch(
            () => {}
        );
    }


    // =========================================================
    // FILTER BINDINGS
    // =========================================================

    function bindFilters() {

        elements.sectorFilter
            ?.addEventListener(
                "change",
                (event) => {

                    state.filters.sector =
                        event.target.value;

                    renderTable();
                }
            );


        elements.technicalScoreFilter
            ?.addEventListener(
                "change",
                (event) => {

                    state.filters
                        .minimumTechnicalScore =
                        event.target.value;

                    renderTable();
                }
            );


        elements.patternFilter
            ?.addEventListener(
                "change",
                (event) => {

                    state.filters
                        .chartPattern =
                        event.target.value;

                    renderTable();
                }
            );


        elements.resetFiltersButton
            ?.addEventListener(
                "click",
                () => {

                    state.filters = {
                        sector: "",
                        minimumTechnicalScore:
                            "",
                        chartPattern: ""
                    };

                    if (
                        elements.sectorFilter
                    ) {
                        elements
                            .sectorFilter
                            .value = "";
                    }

                    if (
                        elements
                            .technicalScoreFilter
                    ) {
                        elements
                            .technicalScoreFilter
                            .value = "";
                    }

                    if (
                        elements.patternFilter
                    ) {
                        elements
                            .patternFilter
                            .value = "";
                    }

                    renderTable();
                }
            );
    }


    // =========================================================
    // MODE BINDINGS
    // =========================================================

    function bindModes() {

        elements.timeframeTabs
            ?.addEventListener(
                "click",
                (event) => {

                    const button =
                        event.target.closest(
                            ".timeframe-tab"
                        );

                    if (!button) {
                        return;
                    }

                    setActiveMode(
                        button.dataset.mode
                        || button.dataset.timeframe
                    );
                }
            );
    }


    // =========================================================
    // DRAWER BINDINGS
    // =========================================================

    function bindDrawer() {

        elements.closeDrawerButton
            ?.addEventListener(
                "click",
                closeDrawer
            );


        elements.drawer
            ?.querySelector(
                ".detail-drawer-backdrop"
            )
            ?.addEventListener(
                "click",
                closeDrawer
            );


        document.addEventListener(
            "keydown",
            (event) => {

                if (
                    event.key
                        === "Escape"
                    && state.drawerOpen
                ) {
                    closeDrawer();
                }
            }
        );
    }


    // =========================================================
    // CUSTOM STATUS EVENT
    // =========================================================

    function bindScannerStatusEvent() {

        window.addEventListener(
            "eagle:scanner-status",
            (event) => {

                renderScannerStatus(
                    event.detail
                    || {}
                );
            }
        );
    }


    // =========================================================
    // INITIALIZE
    // =========================================================

    function initialize() {

        state.mode = normalizeMode(
            state.mode
        );

        bindFilters();

        bindModes();

        bindDrawer();

        bindDetailButtons();

        bindScannerStatusEvent();

        elements.manualRefreshButton
            ?.addEventListener(
                "click",
                triggerManualRefresh
            );

        fetchSignals().catch(
            () => {}
        );
    }


    // =========================================================
    // PUBLIC API
    // =========================================================

    window.EagleDashboard = {
        state,

        fetchSignals,

        loadStockDetail,

        renderTable,

        renderTopSectors,

        renderScannerStatus,

        setActiveMode
    };


    document.addEventListener(
        "DOMContentLoaded",
        initialize
    );
})();
