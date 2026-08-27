(() => {
    "use strict";

    // =========================================================
    // EAGLE SMART SCANNER - DASHBOARD.JS
    // Intraday + BTST + Swing
    // Top 10 Sectors + Top 10 Stocks
    // BUY + STRONG BUY
    // =========================================================

    const config = window.EAGLE_CONFIG || {};

    const state = {
        mode: normalizeMode(
            config.initialMode ||
            window.EAGLE_MODE ||
            "swing"
        ),

        results: [],
        topSectors: [],
        selectedSector: "",
        sectorStocks: [],

        signalsLoading: false,
        sectorsLoading: false,
        sectorStocksLoading: false,
        scannerRunning: false,

        sectorAbortController: null,

        initializedStrongBuys: false,
        knownStrongBuySymbols: new Set(),

        lastCompletedAt: null
    };


    // =========================================================
    // DOM
    // =========================================================

    const el = {
        signalTableBody:
            document.getElementById(
                "signalTableBody"
            ),

        totalResultCount:
            document.getElementById(
                "totalResultCount"
            ),

        strongBuyCount:
            document.getElementById(
                "strongBuyCount"
            ),

        buyCount:
            document.getElementById(
                "buyCount"
            ),

        signalsUpdatedAt:
            document.getElementById(
                "signalsUpdatedAt"
            ),

        scannerStatusText:
            document.getElementById(
                "scannerStatusText"
            ),

        refreshScanButton:
            document.getElementById(
                "refreshScanButton"
            ),

        sectorGrid:
            document.getElementById(
                "sectorGrid"
            ),

        sectorUpdatedAt:
            document.getElementById(
                "sectorUpdatedAt"
            )
    };


    // =========================================================
    // HELPERS
    // =========================================================

    function normalizeMode(value) {

        const mode = String(
            value || ""
        )
            .trim()
            .toLowerCase();

        if (
            mode === "intraday" ||
            mode === "btst" ||
            mode === "swing"
        ) {
            return mode;
        }

        return "swing";
    }


    function normalizeText(value) {
        return String(
            value ?? ""
        ).trim();
    }


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
        fallback = 0
    ) {

        const number = Number(value);

        return Number.isFinite(number)
            ? number
            : fallback;
    }


    function formatNumber(
        value,
        digits = 2
    ) {

        const number = Number(value);

        if (!Number.isFinite(number)) {
            return "—";
        }

        return new Intl.NumberFormat(
            "en-IN",
            {
                minimumFractionDigits: 0,
                maximumFractionDigits: digits
            }
        ).format(number);
    }


    function formatPrice(value) {

        const number = Number(value);

        if (
            !Number.isFinite(number) ||
            number <= 0
        ) {
            return "—";
        }

        return `₹${new Intl.NumberFormat(
            "en-IN",
            {
                maximumFractionDigits: 2
            }
        ).format(number)}`;
    }


    function formatDate(value) {

        if (!value) {
            return "Waiting for data";
        }

        const date = new Date(value);

        if (
            Number.isNaN(
                date.getTime()
            )
        ) {
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


    function isBuySignal(item) {

        const signal =
            getSignal(item);

        return (
            signal === "BUY" ||
            signal === "STRONG BUY"
        );
    }


    function isStrongBuy(item) {

        return (
            getSignal(item)
            === "STRONG BUY"
        );
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
            item?.sector_name ||
            item?.sector ||
            item?.name ||
            item?.sector_key
        );
    }


    function getCurrentPrice(item) {

        return (
            item?.current_price ??
            item?.ltp ??
            item?.price ??
            item?.last_price
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
            item?.target ??
            item?.target1
        );
    }


    function getTechnicalScore(item) {

        return (
            item?.technical_score ??
            item?.score ??
            item?.stock_rank_score ??
            item?.rank_score
        );
    }


    function getConfidence(item) {

        return (
            item?.final_confidence ??
            item?.confidence ??
            item?.probability
        );
    }


    function getChartPattern(item) {

        return (
            item?.chart_pattern ||
            item?.pattern ||
            "—"
        );
    }


    function getCandlePattern(item) {

        return (
            item?.candle_pattern ||
            item?.candlestick_pattern ||
            "—"
        );
    }


    function getRiskReward(item) {

        const existing =
            Number(
                item?.risk_reward
            );

        if (
            Number.isFinite(existing) &&
            existing > 0
        ) {
            return existing;
        }


        const entry =
            Number(
                item?.entry_price
            );

        const stopLoss =
            Number(
                getStopLoss(item)
            );

        const target =
            Number(
                getTarget(item)
            );


        if (
            !Number.isFinite(entry) ||
            !Number.isFinite(stopLoss) ||
            !Number.isFinite(target)
        ) {
            return null;
        }


        const risk =
            entry - stopLoss;

        const reward =
            target - entry;


        if (
            risk <= 0 ||
            reward <= 0
        ) {
            return null;
        }


        return reward / risk;
    }


    // =========================================================
    // API
    // =========================================================

    async function parseResponse(response) {

        let payload = {};

        try {
            payload =
                await response.json();
        } catch {
            payload = {};
        }


        if (
            response.status === 401
        ) {

            window.location.href =
                "/login?force=1";

            throw new Error(
                "FYERS login required."
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


    async function requestJson(
        url,
        options = {}
    ) {

        const response =
            await fetch(
                url,
                {
                    credentials:
                        "same-origin",

                    cache:
                        "no-store",

                    headers: {
                        Accept:
                            "application/json",

                        ...(options.headers || {})
                    },

                    ...options
                }
            );


        return parseResponse(
            response
        );
    }


    // =========================================================
    // VOICE ALERT
    // =========================================================

    function speechAvailable() {

        return (
            "speechSynthesis"
                in window &&
            "SpeechSynthesisUtterance"
                in window
        );
    }


    function speakStrongBuy(item) {

        if (
            !speechAvailable() ||
            !item
        ) {
            return;
        }


        const company =
            getCompanyName(item);

        const sector =
            getSectorName(item);

        const price =
            safeNumber(
                getCurrentPrice(item)
            );

        const entry =
            safeNumber(
                item.entry_price
            );

        const stopLoss =
            safeNumber(
                getStopLoss(item)
            );

        const target =
            safeNumber(
                getTarget(item)
            );


        let message =
            `${company}. `;


        if (sector) {

            message +=
                `${sector} sector. `;
        }


        message +=
            `${state.mode} Strong Buy signal. `;


        if (price > 0) {

            message +=
                `Current price ${price.toFixed(2)}. `;
        }


        if (entry > 0) {

            message +=
                `Entry price ${entry.toFixed(2)}. `;
        }


        if (stopLoss > 0) {

            message +=
                `Stop loss ${stopLoss.toFixed(2)}. `;
        }


        if (target > 0) {

            message +=
                `Target ${target.toFixed(2)}.`;
        }


        try {

            const speech =
                new SpeechSynthesisUtterance(
                    message
                );

            speech.lang =
                "en-IN";

            speech.rate =
                0.9;

            speech.volume =
                1;


            window.speechSynthesis.speak(
                speech
            );

        } catch (error) {

            console.warn(
                "Voice alert error:",
                error
            );
        }
    }


    function processStrongBuyAlerts(
        results
    ) {

        const strongBuys =
            results.filter(
                isStrongBuy
            );


        const currentSymbols =
            new Set(
                strongBuys
                    .map(
                        item =>
                            normalizeText(
                                item.symbol
                            ).toUpperCase()
                    )
                    .filter(Boolean)
            );


        /*
         * Initial page load पर पुराने signals
         * announce नहीं होंगे।
         */

        if (
            !state.initializedStrongBuys
        ) {

            state.knownStrongBuySymbols =
                currentSymbols;

            state.initializedStrongBuys =
                true;

            return;
        }


        strongBuys.forEach(
            item => {

                const symbol =
                    normalizeText(
                        item.symbol
                    ).toUpperCase();


                if (
                    symbol &&
                    !state
                        .knownStrongBuySymbols
                        .has(symbol)
                ) {

                    speakStrongBuy(
                        item
                    );
                }
            }
        );


        state.knownStrongBuySymbols =
            currentSymbols;
    }


    // =========================================================
    // SIGNAL TABLE
    // =========================================================

    function renderSignals() {

        if (
            !el.signalTableBody
        ) {
            return;
        }


        const results =
            state.results.filter(
                isBuySignal
            );


        const strongBuyCount =
            results.filter(
                isStrongBuy
            ).length;


        const buyCount =
            results.filter(
                item =>
                    getSignal(item)
                    === "BUY"
            ).length;


        if (
            el.totalResultCount
        ) {

            el.totalResultCount
                .textContent =
                String(
                    results.length
                );
        }


        if (
            el.strongBuyCount
        ) {

            el.strongBuyCount
                .textContent =
                String(
                    strongBuyCount
                );
        }


        if (
            el.buyCount
        ) {

            el.buyCount
                .textContent =
                String(
                    buyCount
                );
        }


        if (
            !results.length
        ) {

            el.signalTableBody.innerHTML = `
                <tr>
                    <td
                        colspan="13"
                        class="empty-state"
                    >
                        अभी कोई confirmed
                        BUY / STRONG BUY
                        technical signal नहीं है।
                    </td>
                </tr>
            `;

            return;
        }


        /*
         * STRONG BUY first,
         * then technical score.
         */

        results.sort(
            (a, b) => {

                const aRank =
                    isStrongBuy(a)
                        ? 2
                        : 1;

                const bRank =
                    isStrongBuy(b)
                        ? 2
                        : 1;


                if (
                    bRank !== aRank
                ) {
                    return (
                        bRank - aRank
                    );
                }


                return (
                    safeNumber(
                        getTechnicalScore(b)
                    )
                    -
                    safeNumber(
                        getTechnicalScore(a)
                    )
                );
            }
        );


        el.signalTableBody.innerHTML =
            results.map(
                item => {

                    const signal =
                        getSignal(item);

                    const riskReward =
                        getRiskReward(item);


                    return `
                        <tr>

                            <td
                                class="symbol-cell"
                            >

                                <strong>
                                    ${escapeHtml(
                                        getCompanyName(
                                            item
                                        )
                                    )}
                                </strong>

                                <small>
                                    ${escapeHtml(
                                        item.symbol
                                        || ""
                                    )}
                                </small>

                            </td>


                            <td>
                                ${escapeHtml(
                                    getSectorName(
                                        item
                                    )
                                    || "—"
                                )}
                            </td>


                            <td>
                                ${formatPrice(
                                    getCurrentPrice(
                                        item
                                    )
                                )}
                            </td>


                            <td>
                                ${formatPrice(
                                    item.entry_price
                                )}
                            </td>


                            <td>
                                ${formatPrice(
                                    getStopLoss(
                                        item
                                    )
                                )}
                            </td>


                            <td>
                                ${formatPrice(
                                    getTarget(
                                        item
                                    )
                                )}
                            </td>


                            <td>
                                ${
                                    riskReward
                                        ? `1:${formatNumber(
                                            riskReward
                                        )}`
                                        : "—"
                                }
                            </td>


                            <td>
                                <strong>
                                    ${formatNumber(
                                        getTechnicalScore(
                                            item
                                        )
                                    )}
                                </strong>
                            </td>


                            <td>
                                ${formatNumber(
                                    getConfidence(
                                        item
                                    )
                                )}
                            </td>


                            <td>
                                ${escapeHtml(
                                    getChartPattern(
                                        item
                                    )
                                )}
                            </td>


                            <td>
                                ${escapeHtml(
                                    getCandlePattern(
                                        item
                                    )
                                )}
                            </td>


                            <td>

                                ${
                                    signal
                                    === "STRONG BUY"

                                        ? `
                                            <span
                                                class="
                                                    signal-badge
                                                    strong-buy
                                                "
                                            >
                                                STRONG BUY
                                            </span>
                                        `

                                        : `
                                            <span
                                                class="
                                                    signal-badge
                                                    buy
                                                "
                                            >
                                                BUY
                                            </span>
                                        `
                                }

                            </td>


                            <td>

                                <button
                                    type="button"
                                    class="
                                        detail-button
                                        eagle-detail-button
                                    "
                                    data-symbol="${escapeHtml(
                                        item.symbol
                                        || ""
                                    )}"
                                >
                                    View
                                </button>

                            </td>

                        </tr>
                    `;
                }
            ).join("");


        bindDetailButtons();
    }


    // =========================================================
    // LOAD SIGNALS
    // =========================================================

    async function fetchSignals() {

        if (
            state.signalsLoading
        ) {
            return;
        }


        state.signalsLoading =
            true;


        try {

            const endpoint =
                config.api?.signals ||
                "/api/signals";


            const url =
                new URL(
                    endpoint,
                    window.location.origin
                );


            url.searchParams.set(
                "mode",
                state.mode
            );


            const payload =
                await requestJson(
                    url.toString()
                );


            let results = [];


            if (
                Array.isArray(
                    payload.results
                )
            ) {

                results =
                    payload.results;

            } else if (
                Array.isArray(
                    payload.stocks
                )
            ) {

                results =
                    payload.stocks;

            } else if (
                Array.isArray(
                    payload.signals
                )
            ) {

                results =
                    payload.signals;
            }


            processStrongBuyAlerts(
                results
            );


            state.results =
                results;


            renderSignals();


            if (
                el.signalsUpdatedAt
            ) {

                el.signalsUpdatedAt
                    .textContent =
                    formatDate(
                        payload.generated_at ||
                        payload.updated_at ||
                        payload.timestamp ||
                        payload.completed_at
                    );
            }


        } catch (error) {

            console.error(
                "Signal API error:",
                error
            );


            if (
                el.signalTableBody
            ) {

                el.signalTableBody
                    .innerHTML = `
                    <tr>
                        <td
                            colspan="13"
                            class="empty-state"
                        >
                            ${escapeHtml(
                                error.message
                                || "Signals could not be loaded."
                            )}
                        </td>
                    </tr>
                `;
            }

        } finally {

            state.signalsLoading =
                false;
        }
    }


    // =========================================================
    // TOP 10 SECTORS
    // =========================================================

    function getSectorScore(item) {

        return safeNumber(
            item?.technical_score ??
            item?.sector_score ??
            item?.score
        );
    }


    function renderTopSectors() {

        if (!el.sectorGrid) {
            return;
        }


        const sectors =
            state.topSectors
                .slice(0, 10);


        if (
            !sectors.length
        ) {

            el.sectorGrid.innerHTML = `
                <div class="empty-state">
                    Technical sector ranking
                    अभी उपलब्ध नहीं है।
                </div>
            `;

            return;
        }


        el.sectorGrid.innerHTML =
            sectors.map(
                (sector, index) => {

                    const name =
                        getSectorName(
                            sector
                        );


                    return `
                        <button
                            type="button"
                            class="sector-card"
                            data-sector="${escapeHtml(
                                name
                            )}"
                        >

                            <strong>
                                ${index + 1}.
                                ${escapeHtml(
                                    name
                                )}
                            </strong>

                            <span>
                                Technical Score
                            </span>

                            <div
                                class="sector-score"
                            >
                                ${formatNumber(
                                    getSectorScore(
                                        sector
                                    )
                                )}
                            </div>

                        </button>
                    `;
                }
            ).join("");


        bindSectorButtons();
    }


    async function loadTopSectors() {

        if (
            state.sectorsLoading
        ) {
            return;
        }


        state.sectorsLoading =
            true;


        try {

            const endpoint =
                config.api?.sectors ||
                "/api/sectors";


            const url =
                new URL(
                    endpoint,
                    window.location.origin
                );


            url.searchParams.set(
                "mode",
                state.mode
            );


            const payload =
                await requestJson(
                    url.toString()
                );


            let sectors = [];


            if (
                Array.isArray(
                    payload.sectors
                )
            ) {

                sectors =
                    payload.sectors;

            } else if (
                Array.isArray(
                    payload.top_sectors
                )
            ) {

                sectors =
                    payload.top_sectors;

            } else if (
                Array.isArray(
                    payload.results
                )
            ) {

                sectors =
                    payload.results;
            }


            state.topSectors =
                sectors
                    .sort(
                        (a, b) =>
                            getSectorScore(b)
                            -
                            getSectorScore(a)
                    )
                    .slice(0, 10);


            renderTopSectors();


            if (
                el.sectorUpdatedAt
            ) {

                el.sectorUpdatedAt
                    .textContent =
                    formatDate(
                        payload.generated_at ||
                        payload.updated_at ||
                        payload.timestamp
                    );
            }


        } catch (error) {

            console.error(
                "Sector API error:",
                error
            );


            if (
                el.sectorGrid
            ) {

                el.sectorGrid.innerHTML = `
                    <div class="empty-state">
                        ${escapeHtml(
                            error.message
                            || "Sector ranking unavailable."
                        )}
                    </div>
                `;
            }

        } finally {

            state.sectorsLoading =
                false;
        }
    }


    // =========================================================
    // SECTOR CLICK
    // =========================================================

    function bindSectorButtons() {

        document
            .querySelectorAll(
                ".sector-card[data-sector]"
            )
            .forEach(
                button => {

                    button.addEventListener(
                        "click",
                        () => {

                            const sector =
                                normalizeText(
                                    button.dataset
                                        .sector
                                );


                            if (sector) {

                                openSectorStocks(
                                    sector
                                );
                            }
                        }
                    );
                }
            );
    }


    async function openSectorStocks(
        sector
    ) {

        state.selectedSector =
            sector;


        /*
         * Previous request cancel.
         */

        if (
            state.sectorAbortController
        ) {

            state
                .sectorAbortController
                .abort();
        }


        state.sectorAbortController =
            new AbortController();


        try {

            const endpoint =
                config.api?.sectorStocks ||
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


            const response =
                await fetch(
                    url.toString(),
                    {
                        credentials:
                            "same-origin",

                        cache:
                            "no-store",

                        headers: {
                            Accept:
                                "application/json"
                        },

                        signal:
                            state
                                .sectorAbortController
                                .signal
                    }
                );


            const payload =
                await parseResponse(
                    response
                );


            const stocks =
                Array.isArray(
                    payload.stocks
                )
                    ? payload.stocks
                    : (
                        Array.isArray(
                            payload.results
                        )
                            ? payload.results
                            : []
                    );


            state.sectorStocks =
                stocks.slice(0, 10);


            /*
             * Current dashboard.html में separate
             * sector-stock table नहीं है।
             * इसलिए selected sector के Top 10
             * stocks console + event के through
             * expose किए जा रहे हैं।
             */

            window.dispatchEvent(
                new CustomEvent(
                    "eagle:sector-stocks",
                    {
                        detail: {
                            sector,
                            stocks:
                                state.sectorStocks
                        }
                    }
                )
            );


            console.log(
                `${sector} Top 10 Stocks:`,
                state.sectorStocks
            );


        } catch (error) {

            if (
                error.name
                === "AbortError"
            ) {
                return;
            }


            console.error(
                "Sector stocks error:",
                error
            );
        }
    }


    // =========================================================
    // SCANNER STATUS
    // =========================================================

    async function fetchScannerStatus() {

        const endpoint =
            config.api?.scanStatus ||
            "/api/scanner/status";


        try {

            const url =
                new URL(
                    endpoint,
                    window.location.origin
                );


            url.searchParams.set(
                "mode",
                state.mode
            );


            const payload =
                await requestJson(
                    url.toString()
                );


            const scanner =
                payload.scanner ||
                payload.scanner_status ||
                payload;


            const running =
                Boolean(
                    scanner.running
                );


            state.scannerRunning =
                running;


            if (
                el.scannerStatusText
            ) {

                if (running) {

                    el.scannerStatusText
                        .textContent =
                        "Running";

                } else if (
                    scanner.last_error ||
                    scanner.stage
                    === "failed"
                ) {

                    el.scannerStatusText
                        .textContent =
                        "Error";

                } else {

                    el.scannerStatusText
                        .textContent =
                        "Ready";
                }
            }


            if (
                el.refreshScanButton
            ) {

                el.refreshScanButton
                    .disabled =
                    running;

                el.refreshScanButton
                    .textContent =
                    running
                        ? "Scanning..."
                        : "Run / Refresh Scan";
            }


            /*
             * Scan completed:
             * refresh all output immediately.
             */

            const completedAt =
                scanner.completed_at ||
                payload.completed_at;


            if (
                !running &&
                completedAt &&
                completedAt
                    !== state.lastCompletedAt
            ) {

                const alreadyHadCompletion =
                    Boolean(
                        state.lastCompletedAt
                    );


                state.lastCompletedAt =
                    completedAt;


                if (
                    alreadyHadCompletion
                ) {

                    await Promise.allSettled([
                        fetchSignals(),
                        loadTopSectors()
                    ]);
                }
            }


        } catch (error) {

            console.warn(
                "Scanner status error:",
                error
            );
        }
    }


    // =========================================================
    // MANUAL SCAN
    // =========================================================

    async function runScanner() {

        if (
            state.scannerRunning
        ) {
            return;
        }


        state.scannerRunning =
            true;


        if (
            el.refreshScanButton
        ) {

            el.refreshScanButton
                .disabled =
                true;

            el.refreshScanButton
                .textContent =
                "Scanning...";
        }


        if (
            el.scannerStatusText
        ) {

            el.scannerStatusText
                .textContent =
                "Running";
        }


        try {

            const endpoint =
                config.api?.scanRefresh ||
                "/api/scanner/refresh";


            const payload =
                await requestJson(
                    endpoint,
                    {
                        method:
                            "POST",

                        headers: {
                            "Content-Type":
                                "application/json"
                        },

                        body:
                            JSON.stringify({
                                mode:
                                    state.mode
                            })
                    }
                );


            /*
             * API synchronous scan complete
             */

            if (
                payload.completed_at
            ) {

                state.lastCompletedAt =
                    payload.completed_at;


                await Promise.allSettled([
                    fetchSignals(),
                    loadTopSectors()
                ]);
            }


        } catch (error) {

            console.error(
                "Scanner refresh error:",
                error
            );


            window.alert(
                "Scanner Error:\n"
                + (
                    error.message ||
                    "Scan failed."
                )
            );

        } finally {

            state.scannerRunning =
                false;


            if (
                el.refreshScanButton
            ) {

                el.refreshScanButton
                    .disabled =
                    false;

                el.refreshScanButton
                    .textContent =
                    "Run / Refresh Scan";
            }


            fetchScannerStatus();
        }
    }


    // =========================================================
    // STOCK DETAIL
    // =========================================================

    function openStockDetail(
        symbol
    ) {

        const cleanSymbol =
            normalizeText(
                symbol
            )
                .toUpperCase()
                .replace("NSE:", "")
                .replace("-EQ", "")
                .replace(".NS", "");


        if (!cleanSymbol) {
            return;
        }


        window.location.href =
            `/stock/${encodeURIComponent(
                cleanSymbol
            )}`
            +
            `?mode=${encodeURIComponent(
                state.mode
            )}`;
    }


    function bindDetailButtons() {

        document
            .querySelectorAll(
                ".eagle-detail-button[data-symbol]"
            )
            .forEach(
                button => {

                    if (
                        button.dataset
                            .eagleBound
                        === "1"
                    ) {
                        return;
                    }


                    button.dataset
                        .eagleBound =
                        "1";


                    button.addEventListener(
                        "click",
                        () => {

                            openStockDetail(
                                button.dataset
                                    .symbol
                            );
                        }
                    );
                }
            );
    }


    // =========================================================
    // SEARCH
    // =========================================================

    function openSearchStock() {

        const input =
            document.getElementById(
                "stockSearchInput"
            );


        if (!input) {
            return;
        }


        const symbol =
            normalizeText(
                input.value
            )
                .toUpperCase()
                .replace("NSE:", "")
                .replace("-EQ", "")
                .replace(".NS", "");


        if (!symbol) {
            return;
        }


        openStockDetail(
            symbol
        );
    }


    // =========================================================
    // INITIALIZE
    // =========================================================

    async function initialize() {

        /*
         * Prevent duplicate binding.
         */

        if (
            window
                .__EAGLE_DASHBOARD_INITIALIZED__
        ) {
            return;
        }


        window
            .__EAGLE_DASHBOARD_INITIALIZED__ =
            true;


        el.refreshScanButton
            ?.addEventListener(
                "click",
                runScanner
            );


        document
            .getElementById(
                "stockSearchButton"
            )
            ?.addEventListener(
                "click",
                openSearchStock
            );


        document
            .getElementById(
                "stockSearchInput"
            )
            ?.addEventListener(
                "keydown",
                event => {

                    if (
                        event.key
                        === "Enter"
                    ) {

                        event.preventDefault();

                        openSearchStock();
                    }
                }
            );


        /*
         * Initial dashboard data.
         */

        await Promise.allSettled([
            fetchSignals(),
            loadTopSectors(),
            fetchScannerStatus()
        ]);


        /*
         * Scanner status polling.
         * Scanner itself DOES NOT run every 5 sec.
         */

        window.setInterval(
            fetchScannerStatus,
            5000
        );


        /*
         * Signal results refresh.
         */

        window.setInterval(
            fetchSignals,
            30000
        );


        /*
         * Sector ranking refresh.
         */

        window.setInterval(
            loadTopSectors,
            60000
        );
    }


    // =========================================================
    // PUBLIC API
    // =========================================================

    window.EagleDashboard = {

        state,

        fetchSignals,

        loadTopSectors,

        fetchScannerStatus,

        runScanner,

        openSectorStocks,

        openStockDetail,

        speakStrongBuy,

        renderSignals,

        renderTopSectors
    };


    // =========================================================
    // START
    // =========================================================

    if (
        document.readyState
        === "loading"
    ) {

        document.addEventListener(
            "DOMContentLoaded",
            initialize
        );

    } else {

        initialize();
    }

})();
