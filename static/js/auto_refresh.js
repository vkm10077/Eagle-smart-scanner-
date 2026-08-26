(() => {
    "use strict";

    // =========================================================
    // CONFIG
    // =========================================================

    const config = window.EAGLE_CONFIG || {};
    const api = config.api || {};

    // Keep polling light enough for Render/free hosting.
    const intervals = {
        indices: 10000,        // 10 sec
        signals: 30000,        // 30 sec
        scannerStatus: 5000    // 5 sec
    };


    // =========================================================
    // STATE
    // =========================================================

    const timers = {
        indices: null,
        signals: null,
        scannerStatus: null
    };

    const requests = {
        indices: false,
        signals: false,
        scannerStatus: false
    };

    let pageVisible =
        document.visibilityState === "visible";

    let consecutiveErrors = 0;

    let lastCompletion = null;

    let initialized = false;


    // =========================================================
    // ELEMENTS
    // =========================================================

    const elements = {
        indexGrid:
            document.getElementById("indexGrid"),

        indexUpdatedAt:
            document.getElementById("indexUpdatedAt"),

        connectionDot:
            document.getElementById("connectionDot"),

        connectionText:
            document.getElementById("connectionText"),

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
            document.getElementById("strongBuyCount")
    };


    // =========================================================
    // HELPERS
    // =========================================================

    function escapeHtml(value) {
        return String(value ?? "")
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


    function formatNumber(value) {
        const number = Number(value);

        if (!Number.isFinite(number)) {
            return "—";
        }

        return new Intl.NumberFormat(
            "en-IN",
            {
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


    function getCurrentMode() {
        const dashboardMode =
            window.EagleDashboard
            ?.state
            ?.mode;

        const mode = String(
            dashboardMode
            || config.initialMode
            || config.initialTimeframe
            || "swing"
        )
            .trim()
            .toLowerCase();

        if (
            mode === "intraday"
            || mode === "btst"
            || mode === "swing"
        ) {
            return mode;
        }

        return "swing";
    }


    async function parseResponse(response) {
        let payload = {};

        try {
            payload = await response.json();
        } catch {
            payload = {};
        }

        if (response.status === 401) {
            window.location.href =
                "/login?force=1";

            throw new Error(
                "FYERS session expired."
            );
        }

        if (
            !response.ok
            || payload.success === false
        ) {
            throw new Error(
                payload.message
                || payload.error
                || `Request failed (${response.status})`
            );
        }

        return payload;
    }


    // =========================================================
    // CONNECTION STATUS
    // =========================================================

    function updateConnection(
        status,
        message
    ) {
        if (
            !elements.connectionDot
            || !elements.connectionText
        ) {
            return;
        }

        elements.connectionDot
            .classList.remove(
                "status-online",
                "status-warning",
                "status-offline"
            );

        if (status === "online") {
            elements.connectionDot
                .classList.add(
                    "status-online"
                );

        } else if (
            status === "warning"
        ) {
            elements.connectionDot
                .classList.add(
                    "status-warning"
                );

        } else {
            elements.connectionDot
                .classList.add(
                    "status-offline"
                );
        }

        elements.connectionText
            .textContent =
            message;
    }


    // =========================================================
    // INDEX RENDERING
    // =========================================================

    function renderIndices(indices) {
        if (!elements.indexGrid) {
            return;
        }

        if (
            !Array.isArray(indices)
            || indices.length === 0
        ) {
            elements.indexGrid.innerHTML = `
                <div class="detail-empty">
                    Verified live index data is unavailable.
                </div>
            `;

            return;
        }

        elements.indexGrid.innerHTML =
            indices.map(item => {

                const change =
                    safeNumber(
                        item.change,
                        0
                    );

                const changePercent =
                    safeNumber(
                        item.change_percent,
                        0
                    );

                let directionClass =
                    "index-neutral";

                if (changePercent > 0) {
                    directionClass =
                        "index-positive";

                } else if (
                    changePercent < 0
                ) {
                    directionClass =
                        "index-negative";
                }

                return `
                    <article class="index-card">

                        <div class="index-card-header">

                            <span class="index-card-name">
                                ${escapeHtml(
                                    item.short_name
                                    || item.name
                                    || "—"
                                )}
                            </span>

                            <span class="index-exchange">
                                ${escapeHtml(
                                    item.exchange
                                    || "NSE"
                                )}
                            </span>

                        </div>


                        <div class="index-price">
                            ${formatNumber(
                                item.current_price
                            )}
                        </div>


                        <div class="index-card-footer">

                            <span
                                class="
                                    index-change
                                    ${directionClass}
                                "
                            >
                                ${
                                    change >= 0
                                        ? "+"
                                        : ""
                                }

                                ${formatNumber(change)}

                                (

                                ${
                                    changePercent >= 0
                                        ? "+"
                                        : ""
                                }

                                ${formatNumber(
                                    changePercent
                                )}%

                                )
                            </span>


                            ${
                                item.stale
                                    ? `
                                        <span
                                            class="index-stale-label"
                                        >
                                            STALE
                                        </span>
                                    `
                                    : ""
                            }

                        </div>

                    </article>
                `;
            }).join("");
    }


    // =========================================================
    // SCANNER STATUS RENDERING
    // =========================================================

    function updateScannerStatus(status) {
        if (
            !status
            || typeof status !== "object"
        ) {
            return;
        }

        const running =
            Boolean(status.running);

        const stage =
            String(
                status.stage
                || (
                    running
                        ? "scanning"
                        : "idle"
                )
            );

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


        if (elements.scannerStatusText) {

            if (running) {
                elements.scannerStatusText
                    .textContent =
                    "Running";

            } else if (
                status.last_error
                || stage === "failed"
            ) {
                elements.scannerStatusText
                    .textContent =
                    "Scan Error";

            } else {
                elements.scannerStatusText
                    .textContent =
                    "Ready";
            }
        }


        if (elements.scannerProgressBar) {
            elements.scannerProgressBar
                .style.width =
                `${progress}%`;
        }


        if (elements.scannerStage) {
            elements.scannerStage
                .textContent =
                stage;
        }


        if (elements.sectorCount) {
            elements.sectorCount
                .textContent =
                safeNumber(
                    status.sector_count,
                    0
                );
        }


        if (elements.candidateCount) {
            elements.candidateCount
                .textContent =
                safeNumber(
                    status.candidate_count,
                    0
                );
        }


        if (elements.commonCount) {
            elements.commonCount
                .textContent =
                safeNumber(
                    status.common_count,
                    0
                );
        }


        if (elements.strongBuyCount) {
            elements.strongBuyCount
                .textContent =
                safeNumber(
                    status.strong_buy_count,
                    0
                );
        }


        // =====================================================
        // SCAN COMPLETED
        // =====================================================

        const completionKey =
            status.completed_at
            || status.finished_at
            || status.last_completed_at
            || null;

        if (
            !running
            && completionKey
            && completionKey !== lastCompletion
        ) {
            lastCompletion =
                completionKey;

            refreshAfterScanCompletion();
        }
    }


    async function refreshAfterScanCompletion() {

        const dashboard =
            window.EagleDashboard;

        if (!dashboard) {
            return;
        }

        // Refresh Strong Buy signals once.
        if (
            typeof dashboard.fetchSignals
            === "function"
        ) {
            try {
                await dashboard.fetchSignals();
            } catch (error) {
                console.warn(
                    "Post-scan signal refresh failed:",
                    error
                );
            }
        }


        // If user has a sector open,
        // refresh its Top 10 stocks too.
        const selectedSector =
            dashboard.state
            ?.selectedSector;

        if (
            selectedSector
            && typeof dashboard.fetchSectorStocks
                === "function"
        ) {
            try {
                await dashboard.fetchSectorStocks(
                    selectedSector
                );
            } catch (error) {
                console.warn(
                    "Post-scan sector refresh failed:",
                    error
                );
            }
        }
    }


    // =========================================================
    // LIVE INDICES
    // =========================================================

    async function refreshIndices() {
        if (
            !pageVisible
            || requests.indices
            || !api.indices
        ) {
            return;
        }

        requests.indices = true;

        try {
            const response = await fetch(
                api.indices,
                {
                    credentials:
                        "same-origin",

                    headers: {
                        Accept:
                            "application/json"
                    },

                    cache:
                        "no-store"
                }
            );

            const payload =
                await parseResponse(response);

            const indices =
                Array.isArray(
                    payload.indices
                )
                    ? payload.indices
                    : [];

            renderIndices(indices);


            if (elements.indexUpdatedAt) {
                elements.indexUpdatedAt
                    .textContent =
                    formatDate(
                        payload.updated_at
                        || payload.timestamp
                    );
            }


            const stale =
                indices.some(
                    item =>
                        Boolean(item.stale)
                );


            updateConnection(
                stale
                    ? "warning"
                    : "online",

                stale
                    ? "Connected · Some stale data"
                    : "Live Connected"
            );


            consecutiveErrors = 0;

        } catch (error) {

            consecutiveErrors += 1;

            updateConnection(
                consecutiveErrors >= 3
                    ? "offline"
                    : "warning",

                consecutiveErrors >= 3
                    ? "Connection Error"
                    : "Retrying"
            );

            console.warn(
                "Index refresh failed:",
                error
            );

        } finally {
            requests.indices = false;
        }
    }


    // =========================================================
    // SCANNER STATUS
    // =========================================================

    async function refreshScannerStatus() {
        if (
            !pageVisible
            || requests.scannerStatus
            || !api.scanStatus
        ) {
            return;
        }

        requests.scannerStatus = true;

        try {
            const url = new URL(
                api.scanStatus,
                window.location.origin
            );

            // Important:
            // status must match current trading mode.
            url.searchParams.set(
                "mode",
                getCurrentMode()
            );


            const response = await fetch(
                url.toString(),
                {
                    credentials:
                        "same-origin",

                    headers: {
                        Accept:
                            "application/json"
                    },

                    cache:
                        "no-store"
                }
            );


            const payload =
                await parseResponse(response);


            const status =
                payload.scanner
                || payload.scanner_status
                || payload;


            updateScannerStatus(status);


        } catch (error) {

            console.warn(
                "Scanner status refresh failed:",
                error
            );

        } finally {
            requests.scannerStatus = false;
        }
    }


    // =========================================================
    // SIGNAL REFRESH
    // =========================================================

    async function refreshSignals() {
        if (
            !pageVisible
            || requests.signals
        ) {
            return;
        }

        const dashboard =
            window.EagleDashboard;

        if (
            !dashboard
            || typeof dashboard.fetchSignals
                !== "function"
        ) {
            return;
        }

        requests.signals = true;

        try {
            await dashboard.fetchSignals();

        } catch (error) {
            console.warn(
                "Signal refresh failed:",
                error
            );

        } finally {
            requests.signals = false;
        }
    }


    // =========================================================
    // TIMER MANAGEMENT
    // =========================================================

    function clearTimers() {
        Object.keys(timers)
            .forEach(key => {

                if (timers[key]) {
                    window.clearInterval(
                        timers[key]
                    );

                    timers[key] = null;
                }
            });
    }


    function startTimers() {
        clearTimers();

        if (!pageVisible) {
            return;
        }

        timers.indices =
            window.setInterval(
                refreshIndices,
                intervals.indices
            );

        timers.signals =
            window.setInterval(
                refreshSignals,
                intervals.signals
            );

        timers.scannerStatus =
            window.setInterval(
                refreshScannerStatus,
                intervals.scannerStatus
            );
    }


    // =========================================================
    // PAGE VISIBILITY
    // =========================================================

    function handleVisibilityChange() {

        pageVisible =
            document.visibilityState
            === "visible";


        if (!pageVisible) {
            clearTimers();
            return;
        }


        // Immediately sync after returning
        // to the dashboard tab.

        refreshIndices();
        refreshScannerStatus();
        refreshSignals();

        startTimers();
    }


    // =========================================================
    // NETWORK EVENTS
    // =========================================================

    function handleOnline() {

        consecutiveErrors = 0;

        updateConnection(
            "warning",
            "Reconnecting"
        );

        if (!pageVisible) {
            return;
        }

        refreshIndices();
        refreshScannerStatus();
        refreshSignals();

        startTimers();
    }


    function handleOffline() {

        updateConnection(
            "offline",
            "Device Offline"
        );
    }


    // =========================================================
    // INITIALIZE
    // =========================================================

    function initialize() {

        // Prevent duplicate initialization.
        if (initialized) {
            return;
        }

        initialized = true;


        updateConnection(
            navigator.onLine
                ? "warning"
                : "offline",

            navigator.onLine
                ? "Connecting"
                : "Device Offline"
        );


        if (pageVisible) {

            /*
             * dashboard.js already performs
             * the initial fetchSignals().
             *
             * Therefore auto_refresh.js does
             * NOT immediately call signals
             * again here.
             *
             * This prevents duplicate API
             * requests on initial page load.
             */

            refreshIndices();

            refreshScannerStatus();

            startTimers();
        }
    }


    // =========================================================
    // EVENTS
    // =========================================================

    window.addEventListener(
        "online",
        handleOnline
    );


    window.addEventListener(
        "offline",
        handleOffline
    );


    window.addEventListener(
        "beforeunload",
        clearTimers
    );


    document.addEventListener(
        "visibilitychange",
        handleVisibilityChange
    );


    /*
     * dashboard.js can send status directly
     * after manual refresh.
     */

    window.addEventListener(
        "eagle:scanner-status",
        event => {
            updateScannerStatus(
                event.detail || {}
            );
        }
    );


    // =========================================================
    // PUBLIC API
    // =========================================================

    window.EagleAutoRefresh = {

        refreshIndices,

        refreshSignals,

        refreshScannerStatus,

        updateScannerStatus,

        startTimers,

        clearTimers,

        getCurrentMode,

        get lastCompletion() {
            return lastCompletion;
        },

        set lastCompletion(value) {
            lastCompletion = value;
        }
    };


    // =========================================================
    // START
    // =========================================================

    if (
        document.readyState === "loading"
    ) {
        document.addEventListener(
            "DOMContentLoaded",
            initialize,
            {
                once: true
            }
        );

    } else {
        initialize();
    }

})();
