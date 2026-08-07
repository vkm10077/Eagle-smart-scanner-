(() => {
    "use strict";

    const config = window.EAGLE_CONFIG || {};

    const elements = {
        indexGrid: document.getElementById(
            "indexGrid"
        ),

        indexUpdatedAt: document.getElementById(
            "indexUpdatedAt"
        ),

        connectionDot: document.getElementById(
            "connectionDot"
        ),

        connectionText: document.getElementById(
            "connectionText"
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
    // REFRESH INTERVALS
    // =========================================================

    const intervals = {
        indices: 10000,
        signals: 30000,
        scannerStatus: 5000
    };


    const timers = {
        indices: null,
        signals: null,
        scannerStatus: null
    };


    let pageVisible = true;

    let consecutiveErrors = 0;

    let lastCompletion = null;


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
        const number = Number(
            value
        );

        return Number.isFinite(
            number
        )
            ? number
            : defaultValue;
    }


    function formatNumber(value) {
        const number = Number(
            value
        );

        if (!Number.isFinite(number)) {
            return "-";
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

        const date = new Date(
            value
        );

        if (
            Number.isNaN(
                date.getTime()
            )
        ) {
            return String(
                value
            );
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


    // =========================================================
    // CONNECTION
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

        if (
            status === "online"
        ) {
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

        elements.connectionText.textContent =
            message;
    }


    // =========================================================
    // LIVE INDICES
    // =========================================================

    function renderIndices(
        indices
    ) {
        if (
            !elements.indexGrid
        ) {
            return;
        }

        if (
            !Array.isArray(
                indices
            )
            || indices.length === 0
        ) {
            elements.indexGrid.innerHTML = `
                <div class="detail-empty">
                    Verified live index data is unavailable.
                </div>
            `;

            return;
        }

        elements.indexGrid.innerHTML = (
            indices.map(
                (item) => {

                    const change = Number(
                        item.change || 0
                    );

                    const changePercent = Number(
                        item.change_percent || 0
                    );

                    let directionClass =
                        "index-neutral";

                    if (
                        changePercent > 0
                    ) {
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
                                        || "-"
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
                                    class="index-change ${directionClass}"
                                >
                                    ${
                                        change >= 0
                                            ? "+"
                                            : ""
                                    }

                                    ${formatNumber(
                                        change
                                    )}

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
                }
            ).join("")
        );
    }


    // =========================================================
    // NEW SCANNER STATUS
    // =========================================================

    function updateScannerStatus(
        status
    ) {
        if (
            !status
            || typeof status
                !== "object"
        ) {
            return;
        }

        const running = Boolean(
            status.running
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


        if (
            elements.scannerStatusText
        ) {
            if (running) {
                elements
                    .scannerStatusText
                    .textContent =
                        "Running";

            } else if (
                status.last_error
                || status.stage === "failed"
            ) {
                elements
                    .scannerStatusText
                    .textContent =
                        "Scan Error";

            } else {
                elements
                    .scannerStatusText
                    .textContent =
                        "Ready";
            }
        }


        if (
            elements.scannerProgressBar
        ) {
            elements
                .scannerProgressBar
                .style.width =
                    `${progress}%`;
        }


        if (
            elements.scannerStage
        ) {
            elements
                .scannerStage
                .textContent = (
                    status.stage
                    || "idle"
                );
        }


        if (
            elements.sectorCount
        ) {
            elements
                .sectorCount
                .textContent = (
                    safeNumber(
                        status.sector_count,
                        0
                    )
                );
        }


        if (
            elements.candidateCount
        ) {
            elements
                .candidateCount
                .textContent = (
                    safeNumber(
                        status.candidate_count,
                        0
                    )
                );
        }


        if (
            elements.commonCount
        ) {
            elements
                .commonCount
                .textContent = (
                    safeNumber(
                        status.common_count,
                        0
                    )
                );
        }


        if (
            elements.strongBuyCount
        ) {
            elements
                .strongBuyCount
                .textContent = (
                    safeNumber(
                        status.strong_buy_count,
                        0
                    )
                );
        }


        // -----------------------------------------------------
        // When scan finishes, immediately reload results once.
        // -----------------------------------------------------

        if (
            !running
            && status.completed_at
            && window.EagleDashboard
            && typeof (
                window
                    .EagleDashboard
                    .fetchSignals
            ) === "function"
        ) {

            if (
                lastCompletion
                !== status.completed_at
            ) {
                lastCompletion = (
                    status.completed_at
                );

                window
                    .EagleDashboard
                    .fetchSignals()
                    .catch(
                        () => {}
                    );
            }
        }
    }


    // =========================================================
    // REFRESH INDICES
    // =========================================================

    async function refreshIndices() {
        if (!pageVisible) {
            return;
        }

        if (
            !config.api
            || !config.api.indices
        ) {
            return;
        }

        try {

            const response = await fetch(
                config.api.indices,
                {
                    credentials:
                        "same-origin",

                    headers: {
                        "Accept":
                            "application/json"
                    },

                    cache:
                        "no-store"
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
                        "Index data could "
                        + "not be loaded."
                    )
                );
            }

            renderIndices(
                payload.indices
            );


            if (
                elements.indexUpdatedAt
            ) {
                elements
                    .indexUpdatedAt
                    .textContent = (
                        formatDate(
                            payload.updated_at
                        )
                    );
            }


            const indexRows = (
                Array.isArray(
                    payload.indices
                )
                    ? payload.indices
                    : []
            );


            const hasStaleData = (
                indexRows.some(
                    (item) => (
                        Boolean(
                            item.stale
                        )
                    )
                )
            );


            updateConnection(
                hasStaleData
                    ? "warning"
                    : "online",

                hasStaleData
                    ? (
                        "Connected · "
                        + "Some stale data"
                    )
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
        }
    }


    // =========================================================
    // REFRESH SCANNER STATUS
    // =========================================================

    async function refreshScannerStatus() {
        if (!pageVisible) {
            return;
        }

        if (
            !config.api
            || !config.api.scanStatus
        ) {
            return;
        }

        try {

            const response = await fetch(
                config.api.scanStatus,
                {
                    credentials:
                        "same-origin",

                    headers: {
                        "Accept":
                            "application/json"
                    },

                    cache:
                        "no-store"
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
                        "Scanner status "
                        + "unavailable."
                    )
                );
            }


            updateScannerStatus(
                payload.scanner
            );


        } catch (error) {

            console.warn(
                (
                    "Scanner status "
                    + "refresh failed:"
                ),
                error
            );
        }
    }


    // =========================================================
    // REFRESH SIGNALS
    // =========================================================

    async function refreshSignals() {
        if (
            !pageVisible
            || !window.EagleDashboard
            || typeof (
                window
                    .EagleDashboard
                    .fetchSignals
            ) !== "function"
        ) {
            return;
        }

        try {

            await (
                window
                    .EagleDashboard
                    .fetchSignals()
            );

        } catch (error) {

            console.warn(
                (
                    "Signal refresh "
                    + "failed:"
                ),
                error
            );
        }
    }


    // =========================================================
    // TIMER MANAGEMENT
    // =========================================================

    function clearTimers() {

        Object.keys(
            timers
        ).forEach(
            (key) => {

                if (
                    timers[key]
                ) {
                    window.clearInterval(
                        timers[key]
                    );

                    timers[key] = null;
                }
            }
        );
    }


    function startTimers() {

        clearTimers();


        timers.indices = (
            window.setInterval(
                refreshIndices,
                intervals.indices
            )
        );


        timers.signals = (
            window.setInterval(
                refreshSignals,
                intervals.signals
            )
        );


        timers.scannerStatus = (
            window.setInterval(
                refreshScannerStatus,
                intervals.scannerStatus
            )
        );
    }


    // =========================================================
    // VISIBILITY
    // =========================================================

    function handleVisibilityChange() {

        pageVisible = (
            document.visibilityState
            === "visible"
        );


        if (pageVisible) {

            refreshIndices();

            refreshScannerStatus();

            refreshSignals();

            startTimers();

        } else {

            clearTimers();
        }
    }


    // =========================================================
    // INITIALIZE
    // =========================================================

    function initialize() {

        updateConnection(
            "warning",
            "Connecting"
        );


        refreshIndices();

        refreshScannerStatus();

        refreshSignals();


        startTimers();
    }


    // =========================================================
    // NETWORK EVENTS
    // =========================================================

    window.addEventListener(
        "online",
        () => {

            consecutiveErrors = 0;


            updateConnection(
                "warning",
                "Reconnecting"
            );


            refreshIndices();

            refreshScannerStatus();

            refreshSignals();
        }
    );


    window.addEventListener(
        "offline",
        () => {

            updateConnection(
                "offline",
                "Device Offline"
            );
        }
    );


    // =========================================================
    // PAGE EVENTS
    // =========================================================

    window.addEventListener(
        "beforeunload",
        clearTimers
    );


    document.addEventListener(
        "visibilitychange",
        handleVisibilityChange
    );


    window.addEventListener(
        "eagle:scanner-status",
        (event) => {

            updateScannerStatus(
                event.detail
                || {}
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

        get lastCompletion() {
            return lastCompletion;
        },

        set lastCompletion(
            value
        ) {
            lastCompletion = value;
        }
    };


    document.addEventListener(
        "DOMContentLoaded",
        initialize
    );

})();
