(() => {
    "use strict";

    const config = window.EAGLE_CONFIG || {};

    const elements = {
        indexGrid: document.getElementById("indexGrid"),
        indexUpdatedAt: document.getElementById("indexUpdatedAt"),
        connectionDot: document.getElementById("connectionDot"),
        connectionText: document.getElementById("connectionText"),
        scannerStatusText: document.getElementById("scannerStatusText"),
        scannerProgressBar: document.getElementById("scannerProgressBar"),
        processedStocks: document.getElementById("processedStocks"),
        qualifiedStocks: document.getElementById("qualifiedStocks"),
        rejectedStocks: document.getElementById("rejectedStocks"),
        failedStocks: document.getElementById("failedStocks")
    };

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

    function escapeHtml(value) {
        return String(value ?? "")
            .replaceAll("&", "&amp;")
            .replaceAll("<", "&lt;")
            .replaceAll(">", "&gt;")
            .replaceAll('"', "&quot;")
            .replaceAll("'", "&#039;");
    }

    function formatNumber(value) {
        const number = Number(value);

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

    function updateConnection(
        status,
        message
    ) {
        if (!elements.connectionDot || !elements.connectionText) {
            return;
        }

        elements.connectionDot.classList.remove(
            "status-online",
            "status-warning",
            "status-offline"
        );

        if (status === "online") {
            elements.connectionDot.classList.add(
                "status-online"
            );
        } else if (status === "warning") {
            elements.connectionDot.classList.add(
                "status-warning"
            );
        } else {
            elements.connectionDot.classList.add(
                "status-offline"
            );
        }

        elements.connectionText.textContent = message;
    }

    function renderIndices(indices) {
        if (!elements.indexGrid) {
            return;
        }

        if (!Array.isArray(indices) || indices.length === 0) {
            elements.indexGrid.innerHTML = `
                <div class="detail-empty">
                    Verified live index data is unavailable.
                </div>
            `;
            return;
        }

        elements.indexGrid.innerHTML = indices.map((item) => {
            const change = Number(item.change || 0);
            const changePercent = Number(item.change_percent || 0);

            let directionClass = "index-neutral";

            if (changePercent > 0) {
                directionClass = "index-positive";
            } else if (changePercent < 0) {
                directionClass = "index-negative";
            }

            return `
                <article class="index-card">
                    <div class="index-card-header">
                        <span class="index-card-name">
                            ${escapeHtml(item.short_name || item.name || "-")}
                        </span>

                        <span class="index-exchange">
                            ${escapeHtml(item.exchange || "-")}
                        </span>
                    </div>

                    <div class="index-price">
                        ${formatNumber(item.current_price)}
                    </div>

                    <div class="index-card-footer">
                        <span class="index-change ${directionClass}">
                            ${change >= 0 ? "+" : ""}
                            ${formatNumber(change)}
                            (${changePercent >= 0 ? "+" : ""}
                            ${formatNumber(changePercent)}%)
                        </span>

                        ${
                            item.stale
                                ? `
                                    <span class="index-stale-label">
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

    function updateScannerStatus(status) {
        if (!status || typeof status !== "object") {
            return;
        }

        const running = Boolean(status.running);
        const progress = Number(status.progress_percent || 0);

        if (elements.scannerStatusText) {
            elements.scannerStatusText.textContent = (
                running
                    ? `Scanning ${status.last_symbol || ""}`.trim()
                    : status.last_error
                        ? "Scan Error"
                        : "Ready"
            );
        }

        if (elements.scannerProgressBar) {
            elements.scannerProgressBar.style.width = (
                `${Math.max(0, Math.min(100, progress))}%`
            );
        }

        if (elements.processedStocks) {
            elements.processedStocks.textContent = (
                status.processed_stocks || 0
            );
        }

        if (elements.qualifiedStocks) {
            elements.qualifiedStocks.textContent = (
                status.qualified_stocks || 0
            );
        }

        if (elements.rejectedStocks) {
            elements.rejectedStocks.textContent = (
                status.rejected_stocks || 0
            );
        }

        if (elements.failedStocks) {
            elements.failedStocks.textContent = (
                status.failed_stocks || 0
            );
        }

        if (
            !running
            && status.completed_at
            && window.EagleDashboard
        ) {
            const previousCompletion = (
                window.EagleAutoRefresh?.lastCompletion
            );

            if (
                previousCompletion !== status.completed_at
            ) {
                window.EagleAutoRefresh.lastCompletion = (
                    status.completed_at
                );

                window.EagleDashboard
                    .fetchSignals()
                    .catch(() => {});
            }
        }
    }

    async function refreshIndices() {
        if (!pageVisible) {
            return;
        }

        try {
            const response = await fetch(
                config.api.indices,
                {
                    credentials: "same-origin",
                    headers: {
                        "Accept": "application/json"
                    },
                    cache: "no-store"
                }
            );

            const payload = await response.json();

            if (!response.ok || !payload.success) {
                throw new Error(
                    payload.error
                    || "Index data could not be loaded."
                );
            }

            renderIndices(payload.indices);

            if (elements.indexUpdatedAt) {
                elements.indexUpdatedAt.textContent = (
                    formatDate(payload.updated_at)
                );
            }

            const hasStaleData = payload.indices.some(
                (item) => item.stale
            );

            updateConnection(
                hasStaleData ? "warning" : "online",
                hasStaleData
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
        }
    }

    async function refreshScannerStatus() {
        if (!pageVisible) {
            return;
        }

        try {
            const response = await fetch(
                config.api.scanStatus,
                {
                    credentials: "same-origin",
                    headers: {
                        "Accept": "application/json"
                    },
                    cache: "no-store"
                }
            );

            const payload = await response.json();

            if (!response.ok || !payload.success) {
                throw new Error(
                    payload.error
                    || "Scanner status unavailable."
                );
            }

            updateScannerStatus(payload.scanner);

        } catch (error) {
            console.warn(
                "Scanner status refresh failed:",
                error
            );
        }
    }

    async function refreshSignals() {
        if (
            !pageVisible
            || !window.EagleDashboard
            || typeof window.EagleDashboard.fetchSignals
            !== "function"
        ) {
            return;
        }

        try {
            await window.EagleDashboard.fetchSignals();

        } catch (error) {
            console.warn(
                "Signal refresh failed:",
                error
            );
        }
    }

    function clearTimers() {
        Object.keys(timers).forEach((key) => {
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

        timers.indices = window.setInterval(
            refreshIndices,
            intervals.indices
        );

        timers.signals = window.setInterval(
            refreshSignals,
            intervals.signals
        );

        timers.scannerStatus = window.setInterval(
            refreshScannerStatus,
            intervals.scannerStatus
        );
    }

    function handleVisibilityChange() {
        pageVisible = (
            document.visibilityState === "visible"
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

    function initialize() {
        updateConnection(
            "warning",
            "Connecting"
        );

        refreshIndices();
        refreshScannerStatus();

        startTimers();
    }

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
            );
        }
    );

    window.EagleAutoRefresh = {
        refreshIndices,
        refreshSignals,
        refreshScannerStatus,
        lastCompletion: null
    };

    document.addEventListener(
        "DOMContentLoaded",
        initialize
    );
})();
