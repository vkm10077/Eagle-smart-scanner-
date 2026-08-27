(() => {
    "use strict";

    const config = window.EAGLE_CONFIG || {};
    const api = config.api || {};

    const state = {
        mode: normalizeMode(
            config.initialMode ||
            config.initialTimeframe ||
            "intraday"
        ),

        results: [],
        topSectors: [],
        sectorStocks: [],
        selectedSector: "",

        loadingSignals: false,
        loadingSectorStocks: false,
        manualScanRunning: false,

        signalsInitialized: false,
        knownStrongBuySymbols: new Set(),

        drawerOpen: false
    };


    // =========================================================
    // ELEMENTS
    // =========================================================

    const el = {
        timeframeTabs:
            document.getElementById("timeframeTabs"),

        manualRefreshButton:
            document.getElementById("manualRefreshButton"),

        scannerStatusText:
            document.getElementById("scannerStatusText"),

        scannerProgressBar:
            document.getElementById("scannerProgressBar"),

        scannerStage:
            document.getElementById("scannerStage"),

        sectorCount:
            document.getElementById("sectorCount"),

        candidateCount:
            document.getElementById("candidateCount"),

        commonCount:
            document.getElementById("commonCount"),

        strongBuyCount:
            document.getElementById("strongBuyCount"),

        topSectorGrid:
            document.getElementById("topSectorGrid"),

        signalTableBody:
            document.getElementById("signalTableBody"),

        resultCount:
            document.getElementById("resultCount"),

        signalsUpdatedAt:
            document.getElementById("signalsUpdatedAt"),

        sectorStocksSection:
            document.getElementById("sectorStocksSection"),

        selectedSectorTitle:
            document.getElementById("selectedSectorTitle"),

        sectorStockCount:
            document.getElementById("sectorStockCount"),

        sectorStocksUpdatedAt:
            document.getElementById("sectorStocksUpdatedAt"),

        sectorStocksLoading:
            document.getElementById("sectorStocksLoading"),

        sectorStocksError:
            document.getElementById("sectorStocksError"),

        sectorStockTableBody:
            document.getElementById("sectorStockTableBody"),

        sectorFilter:
            document.getElementById("sectorFilter"),

        technicalScoreFilter:
            document.getElementById("technicalScoreFilter"),

        patternFilter:
            document.getElementById("patternFilter"),

        resetFiltersButton:
            document.getElementById("resetFiltersButton"),

        drawer:
            document.getElementById("detailDrawer"),

        drawerTitle:
            document.getElementById("detailDrawerTitle"),

        drawerContent:
            document.getElementById("detailDrawerContent"),

        closeDrawerButton:
            document.getElementById("closeDetailDrawer")
    };


    // =========================================================
    // HELPERS
    // =========================================================

    function normalizeMode(value) {
        const mode = String(value || "")
            .trim()
            .toLowerCase();

        if (
            mode === "intraday" ||
            mode === "btst" ||
            mode === "swing"
        ) {
            return mode;
        }

        return "intraday";
    }


    function normalizeText(value) {
        return String(value ?? "").trim();
    }


    function escapeHtml(value) {
        return String(value ?? "")
            .replaceAll("&", "&amp;")
            .replaceAll("<", "&lt;")
            .replaceAll(">", "&gt;")
            .replaceAll('"', "&quot;")
            .replaceAll("'", "&#039;");
    }


    function safeNumber(value, fallback = 0) {
        const number = Number(value);

        return Number.isFinite(number)
            ? number
            : fallback;
    }


    function formatNumber(value, digits = 2) {
        const number = Number(value);

        if (!Number.isFinite(number)) {
            return "—";
        }

        return number.toFixed(digits);
    }


    function formatPrice(value) {
        const number = Number(value);

        if (!Number.isFinite(number) || number <= 0) {
            return "—";
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


    function formatDate(value) {
        if (!value) {
            return "Waiting for data";
        }

        const date = new Date(value);

        if (Number.isNaN(date.getTime())) {
            return String(value);
        }

        try {
            return new Intl.DateTimeFormat(
                "en-IN",
                {
                    dateStyle: "medium",
                    timeStyle: "medium",
                    timeZone: "Asia/Kolkata"
                }
            ).format(date);
        } catch {
            return String(value);
        }
    }


    function getSignal(item) {
        return normalizeText(
            item?.signal
        ).toUpperCase();
    }


    function isStrongBuy(item) {
        return getSignal(item) === "STRONG BUY";
    }


    function getCompanyName(item) {
        return (
            item?.company_name ||
            item?.stock_name ||
            item?.name ||
            item?.symbol ||
            "Stock"
        );
    }


    function getSectorName(item) {
        return normalizeText(
            item?.sector ||
            item?.sector_name ||
            item?.name ||
            item?.sector_key
        );
    }


    function getSectorScore(item) {
        return safeNumber(
            item?.score ??
            item?.sector_score ??
            item?.technical_score,
            0
        );
    }


    function getStockScore(item) {
        return safeNumber(
            item?.stock_rank_score ??
            item?.rank_score ??
            item?.technical_score ??
            item?.score,
            0
        );
    }


    function getStopLoss(item) {
        return (
            item?.stop_loss ??
            item?.sl ??
            item?.stoploss
        );
    }


    function getTarget(item) {
        return (
            item?.target_price ??
            item?.target
        );
    }


    async function parseResponse(response) {
        let payload = {};

        try {
            payload = await response.json();
        } catch {
            payload = {};
        }

        if (response.status === 401) {
            window.location.href = "/login?force=1";

            throw new Error(
                "FYERS session expired."
            );
        }

        if (
            !response.ok ||
            payload.success === false
        ) {
            throw new Error(
                payload.message ||
                payload.error ||
                `Request failed (${response.status})`
            );
        }

        return payload;
    }


    // =========================================================
    // STRONG BUY VOICE ALERT
    // =========================================================

    function speakStrongBuy(item) {
        if (
            !("speechSynthesis" in window) ||
            !("SpeechSynthesisUtterance" in window)
        ) {
            return;
        }

        const company = getCompanyName(item);

        const text =
            `${company}. ${state.mode}. Strong Buy signal.`;

        try {
            const speech =
                new SpeechSynthesisUtterance(text);

            speech.lang = "en-IN";
            speech.rate = 0.9;

            window.speechSynthesis.speak(
                speech
            );
        } catch (error) {
            console.warn(error);
        }
    }


    function processStrongBuyAlerts(results) {
        const strong = results.filter(
            isStrongBuy
        );

        const currentSymbols =
            new Set(
                strong.map(
                    item =>
                        normalizeText(
                            item.symbol
                        ).toUpperCase()
                )
            );

        if (!state.signalsInitialized) {
            state.knownStrongBuySymbols =
                currentSymbols;

            state.signalsInitialized = true;

            return;
        }

        strong.forEach(item => {
            const symbol =
                normalizeText(
                    item.symbol
                ).toUpperCase();

            if (
                symbol &&
                !state.knownStrongBuySymbols.has(symbol)
            ) {
                speakStrongBuy(item);
            }
        });

        state.knownStrongBuySymbols =
            currentSymbols;
    }


    // =========================================================
    // FINAL STRONG BUY TABLE
    // =========================================================

    function getFilteredResults() {
        return state.results.filter(item => {

            if (!isStrongBuy(item)) {
                return false;
            }

            if (el.sectorFilter?.value) {
                if (
                    getSectorName(item).toLowerCase()
                    !==
                    el.sectorFilter.value.toLowerCase()
                ) {
                    return false;
                }
            }

            if (
                el.technicalScoreFilter?.value
            ) {
                const minimum =
                    Number(
                        el.technicalScoreFilter.value
                    );

                if (
                    safeNumber(
                        item.technical_score
                    ) < minimum
                ) {
                    return false;
                }
            }

            if (el.patternFilter?.value) {
                if (
                    normalizeText(
                        item.chart_pattern
                    ).toLowerCase()
                    !==
                    el.patternFilter.value.toLowerCase()
                ) {
                    return false;
                }
            }

            return true;
        });
    }


    function renderSignalTable() {
        if (!el.signalTableBody) {
            return;
        }

        const results =
            getFilteredResults();

        if (!results.length) {
            el.signalTableBody.innerHTML = `
                <tr>
                    <td
                        colspan="12"
                        class="empty-state-cell"
                    >
                        No confirmed Strong Buy setup
                        is available for ${escapeHtml(
                            state.mode.toUpperCase()
                        )}.
                    </td>
                </tr>
            `;

            if (el.resultCount) {
                el.resultCount.textContent =
                    "0 stocks";
            }

            return;
        }

        el.signalTableBody.innerHTML =
            results.map(item => `

                <tr>

                    <td>
                        <strong>
                            ${escapeHtml(
                                getCompanyName(item)
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
                            getSectorName(item) || "—"
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
                            getStopLoss(item)
                        )}
                    </td>

                    <td>
                        ${formatPrice(
                            getTarget(item)
                        )}
                    </td>

                    <td>
                        ${
                            Number.isFinite(
                                Number(item.risk_reward)
                            )
                                ? `1:${Number(
                                    item.risk_reward
                                ).toFixed(2)}`
                                : "—"
                        }
                    </td>

                    <td>
                        <strong>
                            ${formatNumber(
                                item.technical_score
                            )}
                        </strong>
                    </td>

                    <td>
                        ${escapeHtml(
                            item.chart_pattern || "—"
                        )}
                    </td>

                    <td>
                        ${escapeHtml(
                            item.candlestick_pattern ||
                            item.candle_pattern ||
                            "—"
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

            `).join("");

        if (el.resultCount) {
            el.resultCount.textContent =
                `${results.length} stocks`;
        }

        bindDetailButtons();
    }


    // =========================================================
    // TOP SECTORS
    // =========================================================

    function renderTopSectors() {
        if (!el.topSectorGrid) {
            return;
        }

        if (!state.topSectors.length) {
            el.topSectorGrid.innerHTML = `
                <div class="empty-sector-state">
                    Top sectors will appear after
                    the technical scan.
                </div>
            `;

            return;
        }

        el.topSectorGrid.innerHTML =
            state.topSectors
                .slice(0, 10)
                .map((item, index) => {

                    const sector =
                        getSectorName(item);

                    const active =
                        sector.toLowerCase()
                        ===
                        state.selectedSector.toLowerCase();

                    return `
                        <button
                            type="button"
                            class="
                                top-sector-card
                                sector-select-card
                                ${active ? "active" : ""}
                            "
                            data-sector="${escapeHtml(
                                sector
                            )}"
                        >

                            <div
                                class="top-sector-card-copy"
                            >
                                <strong>
                                    ${index + 1}.
                                    ${escapeHtml(sector)}
                                </strong>

                                <span>
                                    Tap to view Top 10 stocks
                                </span>
                            </div>

                            <div
                                class="sector-score-wrap"
                            >
                                <span>Score</span>

                                <strong
                                    class="sector-score"
                                >
                                    ${formatNumber(
                                        getSectorScore(item)
                                    )}
                                </strong>
                            </div>

                        </button>
                    `;
                })
                .join("");

        document
            .querySelectorAll(
                ".sector-select-card"
            )
            .forEach(button => {

                button.addEventListener(
                    "click",
                    () => {
                        selectSector(
                            button.dataset.sector
                        );
                    }
                );
            });
    }


    // =========================================================
    // SECTOR STOCKS
    // =========================================================

    async function fetchSectorStocks(sector) {
        if (
            !sector ||
            state.loadingSectorStocks
        ) {
            return;
        }

        state.loadingSectorStocks = true;

        if (el.sectorStocksLoading) {
            el.sectorStocksLoading.hidden =
                false;
        }

        if (el.sectorStocksError) {
            el.sectorStocksError.hidden =
                true;
        }

        try {
            const endpoint =
                api.sectorStocks ||
                "/api/sector-stocks";

            const url =
                new URL(
                    endpoint,
                    window.location.origin
                );

            url.searchParams.set(
                "sector",
                sector
            );

            url.searchParams.set(
                "mode",
                state.mode
            );

            url.searchParams.set(
                "limit",
                "10"
            );

            const response = await fetch(
                url.toString(),
                {
                    credentials: "same-origin",
                    cache: "no-store",
                    headers: {
                        Accept: "application/json"
                    }
                }
            );

            const payload =
                await parseResponse(response);

            state.sectorStocks =
                Array.isArray(payload.stocks)
                    ? payload.stocks
                    : [];

            renderSectorStocks();

            if (el.sectorStocksUpdatedAt) {
                el.sectorStocksUpdatedAt.textContent =
                    formatDate(
                        payload.updated_at ||
                        payload.timestamp
                    );
            }

        } catch (error) {

            if (el.sectorStocksError) {
                el.sectorStocksError.hidden =
                    false;

                el.sectorStocksError.textContent =
                    error.message;
            }

        } finally {

            state.loadingSectorStocks = false;

            if (el.sectorStocksLoading) {
                el.sectorStocksLoading.hidden =
                    true;
            }
        }
    }


    function renderSectorStocks() {
        if (!el.sectorStockTableBody) {
            return;
        }

        const stocks =
            state.sectorStocks.slice(0, 10);

        if (el.sectorStockCount) {
            el.sectorStockCount.textContent =
                `${stocks.length} stocks`;
        }

        if (!stocks.length) {
            el.sectorStockTableBody.innerHTML = `
                <tr>
                    <td
                        colspan="12"
                        class="empty-state-cell"
                    >
                        No ranked stocks available.
                    </td>
                </tr>
            `;

            return;
        }

        el.sectorStockTableBody.innerHTML =
            stocks.map((item, index) => `

                <tr>

                    <td>
                        ${index + 1}
                    </td>

                    <td>
                        <strong>
                            ${escapeHtml(
                                getCompanyName(item)
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
                            getSectorName(item)
                            || state.selectedSector
                        )}
                    </td>

                    <td>
                        ${formatPrice(
                            item.current_price
                        )}
                    </td>

                    <td>
                        ${formatNumber(
                            getStockScore(item)
                        )}
                    </td>

                    <td>
                        ${formatNumber(
                            item.trend_score
                        )}
                    </td>

                    <td>
                        ${formatNumber(
                            item.momentum_score
                        )}
                    </td>

                    <td>
                        ${formatNumber(
                            item.volume_score
                        )}
                    </td>

                    <td>
                        ${formatNumber(
                            item.rsi
                        )}
                    </td>

                    <td>
                        ${formatNumber(
                            item.relative_strength_pct ??
                            item.relative_strength_score
                        )}
                    </td>

                    <td>
                        ${
                            isStrongBuy(item)
                                ? `
                                    <span
                                        class="signal-badge strong-buy"
                                    >
                                        STRONG BUY
                                    </span>
                                `
                                : "RANKED"
                        }
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

            `).join("");

        bindDetailButtons();
    }


    function selectSector(sector) {
        const clean =
            normalizeText(sector);

        if (!clean) {
            return;
        }

        state.selectedSector =
            clean;

        if (el.selectedSectorTitle) {
            el.selectedSectorTitle.textContent =
                `${clean} — Top 10 Stocks`;
        }

        renderTopSectors();

        fetchSectorStocks(clean);

        el.sectorStocksSection
            ?.scrollIntoView({
                behavior: "smooth",
                block: "start"
            });
    }


    // =========================================================
    // SCANNER STATUS
    // =========================================================

    function renderScannerStatus(payload) {
        const scanner =
            payload?.scanner ||
            payload?.scanner_status ||
            payload ||
            {};

        const running =
            Boolean(scanner.running);

        if (el.scannerStatusText) {
            el.scannerStatusText.textContent =
                running
                    ? "Running"
                    : (
                        scanner.stage === "failed"
                            ? "Failed"
                            : "Ready"
                    );
        }

        if (el.scannerStage) {
            el.scannerStage.textContent =
                scanner.stage ||
                (
                    running
                        ? "scanning"
                        : "idle"
                );
        }

        if (el.scannerProgressBar) {
            const progress =
                Math.max(
                    0,
                    Math.min(
                        100,
                        safeNumber(
                            scanner.progress_percent,
                            0
                        )
                    )
                );

            el.scannerProgressBar.style.width =
                `${progress}%`;
        }

        if (el.sectorCount) {
            el.sectorCount.textContent =
                safeNumber(
                    scanner.sector_count,
                    state.topSectors.length
                );
        }

        if (el.candidateCount) {
            el.candidateCount.textContent =
                safeNumber(
                    scanner.candidate_count,
                    0
                );
        }

        if (el.commonCount) {
            el.commonCount.textContent =
                safeNumber(
                    scanner.common_count,
                    0
                );
        }

        if (el.strongBuyCount) {
            el.strongBuyCount.textContent =
                safeNumber(
                    scanner.strong_buy_count,
                    state.results.filter(
                        isStrongBuy
                    ).length
                );
        }

        if (
            el.manualRefreshButton &&
            !state.manualScanRunning
        ) {
            el.manualRefreshButton.disabled =
                running;
        }
    }


    async function fetchScannerStatus() {
        if (!api.scanStatus) {
            return;
        }

        try {
            const url =
                new URL(
                    api.scanStatus,
                    window.location.origin
                );

            url.searchParams.set(
                "mode",
                state.mode
            );

            const response =
                await fetch(
                    url.toString(),
                    {
                        credentials: "same-origin",
                        cache: "no-store",
                        headers: {
                            Accept: "application/json"
                        }
                    }
                );

            const payload =
                await parseResponse(response);

            renderScannerStatus(payload);

        } catch (error) {
            console.warn(
                "Scanner status failed:",
                error
            );
        }
    }


    // =========================================================
    // SIGNALS
    // =========================================================

    async function fetchSignals() {
        if (
            !api.signals ||
            state.loadingSignals
        ) {
            return;
        }

        state.loadingSignals = true;

        try {
            const url =
                new URL(
                    api.signals,
                    window.location.origin
                );

            url.searchParams.set(
                "mode",
                state.mode
            );

            const response =
                await fetch(
                    url.toString(),
                    {
                        credentials: "same-origin",
                        cache: "no-store",
                        headers: {
                            Accept: "application/json"
                        }
                    }
                );

            const payload =
                await parseResponse(response);

            const results =
                Array.isArray(payload.results)
                    ? payload.results
                    : [];

            const sectors =
                Array.isArray(payload.top_sectors)
                    ? payload.top_sectors
                    : [];

            processStrongBuyAlerts(
                results
            );

            state.results =
                results;

            state.topSectors =
                sectors.slice(0, 10);

            renderSignalTable();

            renderTopSectors();

            renderScannerStatus(payload);

            if (el.signalsUpdatedAt) {
                el.signalsUpdatedAt.textContent =
                    formatDate(
                        payload.generated_at ||
                        payload.timestamp
                    );
            }

        } catch (error) {
            console.error(
                "Signals failed:",
                error
            );

        } finally {
            state.loadingSignals = false;
        }
    }


    // =========================================================
    // MODE CHANGE — IMPORTANT FIX
    // =========================================================

    async function setActiveMode(value) {
        const newMode =
            normalizeMode(value);

        /*
         * Even current mode button should visibly
         * remain active.
         */

        document
            .querySelectorAll(
                ".timeframe-tab"
            )
            .forEach(button => {

                const buttonMode =
                    normalizeMode(
                        button.dataset.mode ||
                        button.dataset.timeframe
                    );

                button.classList.toggle(
                    "active",
                    buttonMode === newMode
                );
            });


        if (newMode === state.mode) {
            return;
        }

        state.mode = newMode;

        state.results = [];
        state.topSectors = [];
        state.sectorStocks = [];
        state.selectedSector = "";

        state.signalsInitialized = false;
        state.knownStrongBuySymbols =
            new Set();


        /*
         * URL also changes:
         * /dashboard?mode=btst
         */

        const currentUrl =
            new URL(
                window.location.href
            );

        currentUrl.searchParams.set(
            "mode",
            newMode
        );

        currentUrl.searchParams.delete(
            "timeframe"
        );

        window.history.replaceState(
            {},
            "",
            currentUrl.toString()
        );


        if (el.selectedSectorTitle) {
            el.selectedSectorTitle.textContent =
                "Select a Sector";
        }

        if (el.sectorStockCount) {
            el.sectorStockCount.textContent =
                "0 stocks";
        }

        if (el.sectorStockTableBody) {
            el.sectorStockTableBody.innerHTML = `
                <tr>
                    <td
                        colspan="12"
                        class="empty-state-cell"
                    >
                        Tap any Top 10 Sector above
                        to view its Top 10 ranked stocks.
                    </td>
                </tr>
            `;
        }


        /*
         * Immediately load data of selected mode.
         */

        await Promise.allSettled([
            fetchSignals(),
            fetchScannerStatus()
        ]);
    }


    // =========================================================
    // MANUAL SCAN
    // =========================================================

    async function triggerManualRefresh() {
        if (
            !api.scanRefresh ||
            state.manualScanRunning
        ) {
            return;
        }

        state.manualScanRunning = true;

        if (el.manualRefreshButton) {
            el.manualRefreshButton.disabled =
                true;

            el.manualRefreshButton.textContent =
                "Scanning...";
        }

        try {
            const response =
                await fetch(
                    api.scanRefresh,
                    {
                        method: "POST",
                        credentials: "same-origin",
                        cache: "no-store",

                        headers: {
                            Accept: "application/json",
                            "Content-Type":
                                "application/json"
                        },

                        body: JSON.stringify({
                            mode: state.mode
                        })
                    }
                );

            const payload =
                await parseResponse(response);

            renderScannerStatus(payload);

            await fetchSignals();

            if (state.selectedSector) {
                await fetchSectorStocks(
                    state.selectedSector
                );
            }

        } catch (error) {

            window.alert(
                error.message ||
                "Scanner refresh failed."
            );

        } finally {

            state.manualScanRunning = false;

            if (el.manualRefreshButton) {
                el.manualRefreshButton.disabled =
                    false;

                el.manualRefreshButton.textContent =
                    "Refresh Scan";
            }

            fetchScannerStatus();
        }
    }


    // =========================================================
    // STOCK DETAIL
    // =========================================================

    function loadStockDetail(symbol) {
        const clean =
            normalizeText(symbol)
                .toUpperCase();

        if (!clean) {
            return;
        }

        /*
         * Current stock_detail.html already exists.
         * Use full detail page — most reliable.
         */

        window.location.href =
            `/stock/${encodeURIComponent(clean)}`
            +
            `?mode=${encodeURIComponent(
                state.mode
            )}`;
    }


    function bindDetailButtons() {
        document
            .querySelectorAll(
                ".detail-button[data-symbol]"
            )
            .forEach(button => {

                if (
                    button.dataset.eagleBound
                    === "1"
                ) {
                    return;
                }

                button.dataset.eagleBound =
                    "1";

                button.addEventListener(
                    "click",
                    () => {
                        loadStockDetail(
                            button.dataset.symbol
                        );
                    }
                );
            });
    }


    // =========================================================
    // BINDINGS
    // =========================================================

    function bindModes() {
        el.timeframeTabs
            ?.addEventListener(
                "click",
                event => {

                    const button =
                        event.target.closest(
                            ".timeframe-tab"
                        );

                    if (!button) {
                        return;
                    }

                    event.preventDefault();

                    setActiveMode(
                        button.dataset.mode ||
                        button.dataset.timeframe
                    );
                }
            );
    }


    function bindFilters() {
        el.sectorFilter?.addEventListener(
            "change",
            renderSignalTable
        );

        el.technicalScoreFilter?.addEventListener(
            "change",
            renderSignalTable
        );

        el.patternFilter?.addEventListener(
            "change",
            renderSignalTable
        );

        el.resetFiltersButton
            ?.addEventListener(
                "click",
                () => {

                    if (el.sectorFilter) {
                        el.sectorFilter.value = "";
                    }

                    if (el.technicalScoreFilter) {
                        el.technicalScoreFilter.value = "";
                    }

                    if (el.patternFilter) {
                        el.patternFilter.value = "";
                    }

                    renderSignalTable();
                }
            );
    }


    // =========================================================
    // INITIALIZE
    // =========================================================

    async function initialize() {
        bindModes();
        bindFilters();
        bindDetailButtons();

        el.manualRefreshButton
            ?.addEventListener(
                "click",
                triggerManualRefresh
            );

        /*
         * Correct active button on first load.
         */

        document
            .querySelectorAll(
                ".timeframe-tab"
            )
            .forEach(button => {

                const buttonMode =
                    normalizeMode(
                        button.dataset.mode ||
                        button.dataset.timeframe
                    );

                button.classList.toggle(
                    "active",
                    buttonMode === state.mode
                );
            });


        await Promise.allSettled([
            fetchSignals(),
            fetchScannerStatus()
        ]);
    }


    // =========================================================
    // PUBLIC API
    // =========================================================

    window.EagleDashboard = {
        state,

        setActiveMode,
        fetchSignals,
        fetchScannerStatus,
        fetchSectorStocks,
        selectSector,
        triggerManualRefresh,
        loadStockDetail,

        renderSignalTable,
        renderTopSectors,
        renderSectorStocks,
        renderScannerStatus
    };


    if (
        document.readyState === "loading"
    ) {
        document.addEventListener(
            "DOMContentLoaded",
            initialize
        );
    } else {
        initialize();
    }

})();
