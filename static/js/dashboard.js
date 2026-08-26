(() => {
    "use strict";

    // =========================================================
    // CONFIG + STATE
    // =========================================================

    const config = window.EAGLE_CONFIG || {};
    const api = config.api || {};

    const state = {
        mode: normalizeMode(
            config.initialMode
            || config.initialTimeframe
            || "swing"
        ),

        results: [],
        topSectors: [],
        sectorStocks: [],
        selectedSector: "",

        signalsInitialized: false,
        knownStrongBuySymbols: new Set(),

        drawerOpen: false,
        loadingSignals: false,
        loadingSectorStocks: false,
        manualScanRunning: false,

        filters: {
            sector: "",
            minimumTechnicalScore: "",
            chartPattern: ""
        }
    };


    // =========================================================
    // ELEMENTS
    // =========================================================

    const el = {
        tableBody:
            document.getElementById("signalTableBody"),

        resultCount:
            document.getElementById("resultCount"),

        signalsUpdatedAt:
            document.getElementById("signalsUpdatedAt"),

        topSectorGrid:
            document.getElementById("topSectorGrid"),

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
            mode === "intraday"
            || mode === "btst"
            || mode === "swing"
        ) {
            return mode;
        }

        return "swing";
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
        return String(
            item?.signal || ""
        )
            .trim()
            .toUpperCase();
    }


    function isStrongBuy(item) {
        return getSignal(item) === "STRONG BUY";
    }


    function getCompanyName(item) {
        return (
            item?.company_name
            || item?.stock_name
            || item?.name
            || item?.symbol
            || "Stock"
        );
    }


    function getSectorName(item) {
        return normalizeText(
            item?.sector
            || item?.sector_name
            || item?.name
            || item?.sector_key
        );
    }


    function getSectorScore(item) {
        return safeNumber(
            item?.score
            ?? item?.sector_score
            ?? item?.technical_score,
            0
        );
    }


    function getStockScore(item) {
        return safeNumber(
            item?.score
            ?? item?.stock_rank_score
            ?? item?.rank_score
            ?? item?.technical_score,
            0
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
                "FYERS session expired. Login again."
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
    // STRONG BUY VOICE ALERT
    // =========================================================

    function speechAvailable() {
        return (
            "speechSynthesis" in window
            && "SpeechSynthesisUtterance" in window
        );
    }


    function speakStrongBuy(item) {
        if (!speechAvailable() || !item) {
            return;
        }

        const company = getCompanyName(item);
        const sector = getSectorName(item);

        const price = safeNumber(
            item.current_price,
            0
        );

        const entry = safeNumber(
            item.entry_price,
            0
        );

        const stopLoss = safeNumber(
            item.stop_loss,
            0
        );

        const target = safeNumber(
            item.target_price,
            0
        );

        let text =
            `${company}. `;

        if (sector) {
            text += `${sector}. `;
        }

        text +=
            `${state.mode} Strong Buy signal. `;

        if (price > 0) {
            text +=
                `Current price ${price.toFixed(2)}. `;
        }

        if (entry > 0) {
            text +=
                `Entry ${entry.toFixed(2)}. `;
        }

        if (stopLoss > 0) {
            text +=
                `Stop loss ${stopLoss.toFixed(2)}. `;
        }

        if (target > 0) {
            text +=
                `Target ${target.toFixed(2)}.`;
        }

        try {
            const utterance =
                new SpeechSynthesisUtterance(text);

            utterance.lang = "en-IN";
            utterance.rate = 0.9;
            utterance.pitch = 1;
            utterance.volume = 1;

            window.speechSynthesis.speak(
                utterance
            );
        } catch (error) {
            console.warn(
                "Strong Buy voice alert failed:",
                error
            );
        }
    }


    function processStrongBuyAlerts(results) {
        const strongResults = Array.isArray(results)
            ? results.filter(isStrongBuy)
            : [];

        if (!state.signalsInitialized) {
            state.knownStrongBuySymbols =
                new Set(
                    strongResults
                        .map(
                            item => normalizeText(
                                item.symbol
                            ).toUpperCase()
                        )
                        .filter(Boolean)
                );

            state.signalsInitialized = true;
            return;
        }

        const currentSymbols =
            new Set();

        strongResults.forEach(item => {
            const symbol =
                normalizeText(
                    item.symbol
                ).toUpperCase();

            if (!symbol) {
                return;
            }

            currentSymbols.add(symbol);

            if (
                !state.knownStrongBuySymbols.has(
                    symbol
                )
            ) {
                speakStrongBuy(item);
            }
        });

        state.knownStrongBuySymbols =
            currentSymbols;
    }


    // =========================================================
    // FILTERS
    // =========================================================

    function getFilteredResults() {
        return state.results.filter(item => {
            if (!isStrongBuy(item)) {
                return false;
            }

            if (state.filters.sector) {
                const itemSector =
                    getSectorName(item)
                        .toLowerCase();

                const selectedSector =
                    state.filters.sector
                        .toLowerCase();

                if (
                    itemSector !== selectedSector
                ) {
                    return false;
                }
            }

            if (
                state.filters.minimumTechnicalScore
            ) {
                const minimum = Number(
                    state.filters
                        .minimumTechnicalScore
                );

                const score = safeNumber(
                    item.technical_score,
                    0
                );

                if (
                    Number.isFinite(minimum)
                    && score < minimum
                ) {
                    return false;
                }
            }

            if (state.filters.chartPattern) {
                const selected =
                    state.filters.chartPattern
                        .toLowerCase();

                const pattern =
                    normalizeText(
                        item.chart_pattern
                    ).toLowerCase();

                if (pattern !== selected) {
                    return false;
                }
            }

            return true;
        });
    }


    // =========================================================
    // STRONG BUY TABLE
    // =========================================================

    function renderSignalTable() {
        if (!el.tableBody) {
            return;
        }

        const results =
            getFilteredResults();

        if (!results.length) {
            el.tableBody.innerHTML = `
                <tr>
                    <td
                        colspan="12"
                        class="empty-state-cell"
                    >
                        No confirmed Strong Buy setup
                        matches the selected filters.
                    </td>
                </tr>
            `;

            if (el.resultCount) {
                el.resultCount.textContent =
                    "0 stocks";
            }

            return;
        }

        el.tableBody.innerHTML =
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
                                Number(item.risk_reward)
                            )
                                ? `1:${Number(
                                    item.risk_reward
                                ).toFixed(2)}`
                                : "—"
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
                            || item.candle_pattern
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
            `).join("");

        if (el.resultCount) {
            el.resultCount.textContent =
                `${results.length} ${
                    results.length === 1
                        ? "stock"
                        : "stocks"
                }`;
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
                    Top sectors will appear
                    after the technical scan.
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
                        === state.selectedSector
                            .toLowerCase();

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

        bindSectorCards();
    }


    function bindSectorCards() {
        document.querySelectorAll(
            ".sector-select-card[data-sector]"
        ).forEach(button => {
            button.addEventListener(
                "click",
                () => {
                    const sector =
                        normalizeText(
                            button.dataset.sector
                        );

                    if (sector) {
                        selectSector(sector);
                    }
                }
            );
        });
    }


    // =========================================================
    // SECTOR STOCK TABLE
    // =========================================================

    function showSectorLoading(sector) {
        if (el.selectedSectorTitle) {
            el.selectedSectorTitle.textContent =
                `${sector} — Top 10 Stocks`;
        }

        if (el.sectorStockCount) {
            el.sectorStockCount.textContent =
                "Loading...";
        }

        if (el.sectorStocksUpdatedAt) {
            el.sectorStocksUpdatedAt.textContent =
                "Loading technical ranking";
        }

        if (el.sectorStocksLoading) {
            el.sectorStocksLoading.hidden =
                false;
        }

        if (el.sectorStocksError) {
            el.sectorStocksError.hidden =
                true;

            el.sectorStocksError.textContent =
                "";
        }
    }


    function showSectorError(message) {
        if (el.sectorStocksLoading) {
            el.sectorStocksLoading.hidden =
                true;
        }

        if (el.sectorStocksError) {
            el.sectorStocksError.hidden =
                false;

            el.sectorStocksError.textContent =
                message;
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
                        ${escapeHtml(message)}
                    </td>
                </tr>
            `;
        }
    }


    function renderSectorStocks() {
        if (!el.sectorStockTableBody) {
            return;
        }

        if (el.sectorStocksLoading) {
            el.sectorStocksLoading.hidden =
                true;
        }

        if (el.sectorStocksError) {
            el.sectorStocksError.hidden =
                true;
        }

        const stocks =
            state.sectorStocks.slice(0, 10);

        if (el.sectorStockCount) {
            el.sectorStockCount.textContent =
                `${stocks.length} ${
                    stocks.length === 1
                        ? "stock"
                        : "stocks"
                }`;
        }

        if (!stocks.length) {
            el.sectorStockTableBody.innerHTML = `
                <tr>
                    <td
                        colspan="12"
                        class="empty-state-cell"
                    >
                        No ranked stocks are
                        available for this sector.
                    </td>
                </tr>
            `;

            return;
        }

        el.sectorStockTableBody.innerHTML =
            stocks.map((item, index) => {

                const signal =
                    getSignal(item);

                const strong =
                    signal === "STRONG BUY";

                const trend =
                    item.trend
                    ?? item.trend_score
                    ?? "—";

                const momentum =
                    item.momentum
                    ?? item.momentum_score
                    ?? "—";

                const volume =
                    item.volume
                    ?? item.volume_score
                    ?? "—";

                const rsi =
                    item.rsi
                    ?? "—";

                const relativeStrength =
                    item.relative_strength_score
                    ?? item.relative_strength_pct
                    ?? item.relative_strength
                    ?? "—";

                return `
                    <tr
                        class="${
                            strong
                                ? "strong-buy-candidate"
                                : ""
                        }"
                    >

                        <td>
                            <strong>
                                ${safeNumber(
                                    item.rank,
                                    index + 1
                                )}
                            </strong>
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
                            <strong>
                                ${formatNumber(
                                    getStockScore(item)
                                )}
                            </strong>
                        </td>

                        <td>
                            ${typeof trend === "number"
                                ? formatNumber(trend)
                                : escapeHtml(trend)}
                        </td>

                        <td>
                            ${typeof momentum === "number"
                                ? formatNumber(momentum)
                                : escapeHtml(momentum)}
                        </td>

                        <td>
                            ${typeof volume === "number"
                                ? formatNumber(volume)
                                : escapeHtml(volume)}
                        </td>

                        <td>
                            ${typeof rsi === "number"
                                ? formatNumber(rsi)
                                : escapeHtml(rsi)}
                        </td>

                        <td>
                            ${
                                typeof relativeStrength
                                    === "number"
                                    ? formatNumber(
                                        relativeStrength
                                    )
                                    : escapeHtml(
                                        relativeStrength
                                    )
                            }
                        </td>

                        <td>
                            ${
                                strong
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
                                                condition-badge
                                                condition-neutral
                                            "
                                        >
                                            RANKED
                                        </span>
                                    `
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
                `;
            }).join("");

        bindDetailButtons();
    }


    // =========================================================
    // FETCH SECTOR STOCKS
    // =========================================================

    async function fetchSectorStocks(sector) {
        const cleanSector =
            normalizeText(sector);

        if (
            !cleanSector
            || state.loadingSectorStocks
        ) {
            return;
        }

        state.loadingSectorStocks = true;

        showSectorLoading(cleanSector);

        try {
            const endpoint =
                api.sectorStocks
                || "/api/sector-stocks";

            const url = new URL(
                endpoint,
                window.location.origin
            );

            url.searchParams.set(
                "sector",
                cleanSector
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
                    headers: {
                        Accept: "application/json"
                    }
                }
            );

            const payload =
                await parseResponse(response);

            const stocks =
                Array.isArray(payload.stocks)
                    ? payload.stocks
                    : (
                        Array.isArray(payload.results)
                            ? payload.results
                            : []
                    );

            state.sectorStocks = stocks;

            if (el.sectorStocksUpdatedAt) {
                el.sectorStocksUpdatedAt
                    .textContent =
                    formatDate(
                        payload.timestamp
                    );
            }

            renderSectorStocks();

        } catch (error) {
            console.error(
                "Sector stocks failed:",
                error
            );

            showSectorError(
                error.message
                || "Top 10 stocks could not be loaded."
            );

        } finally {
            state.loadingSectorStocks =
                false;
        }
    }


    function selectSector(sector) {
        const cleanSector =
            normalizeText(sector);

        if (!cleanSector) {
            return;
        }

        state.selectedSector =
            cleanSector;

        state.sectorStocks = [];

        renderTopSectors();

        fetchSectorStocks(
            cleanSector
        );

        if (el.sectorStocksSection) {
            setTimeout(
                () => {
                    el.sectorStocksSection
                        .scrollIntoView({
                            behavior: "smooth",
                            block: "start"
                        });
                },
                80
            );
        }
    }


    // =========================================================
    // SCANNER STATUS
    // =========================================================

    function renderScannerStatus(data) {
        const scanner =
            data?.scanner_status
            || data?.scanner
            || data
            || {};

        const running =
            Boolean(scanner.running);

        const stage =
            normalizeText(
                scanner.stage
            ) || (
                running
                    ? "scanning"
                    : "idle"
            );

        if (el.scannerStatusText) {
            el.scannerStatusText.textContent =
                running
                    ? "Running"
                    : (
                        stage === "failed"
                            ? "Failed"
                            : "Ready"
                    );
        }

        if (el.scannerStage) {
            el.scannerStage.textContent =
                stage;
        }

        if (el.scannerProgressBar) {
            const progress = Math.max(
                0,
                Math.min(
                    100,
                    safeNumber(
                        scanner.progress_percent,
                        running ? 50 : 0
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
                    state.results.length
                );
        }

        if (
            el.manualRefreshButton
            && !state.manualScanRunning
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
            const url = new URL(
                api.scanStatus,
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
    // SIGNALS API
    // =========================================================

    async function fetchSignals() {
        if (
            !api.signals
            || state.loadingSignals
        ) {
            return;
        }

        state.loadingSignals = true;

        try {
            const url = new URL(
                api.signals,
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

            state.results = results;
            state.topSectors =
                sectors.slice(0, 10);

            renderSignalTable();
            renderTopSectors();
            renderScannerStatus(payload);

            if (el.signalsUpdatedAt) {
                el.signalsUpdatedAt.textContent =
                    formatDate(
                        payload.generated_at
                        || payload.timestamp
                    );
            }

            if (el.sectorCount) {
                el.sectorCount.textContent =
                    state.topSectors.length;
            }

            if (el.strongBuyCount) {
                el.strongBuyCount.textContent =
                    safeNumber(
                        payload.strong_buy_count,
                        results.length
                    );
            }

        } catch (error) {
            console.error(
                "Signals failed:",
                error
            );

            if (el.tableBody) {
                el.tableBody.innerHTML = `
                    <tr>
                        <td
                            colspan="12"
                            class="empty-state-cell"
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
            state.loadingSignals = false;
        }
    }


    // =========================================================
    // MANUAL SCAN
    // =========================================================

    async function triggerManualRefresh() {
        if (
            !api.scanRefresh
            || state.manualScanRunning
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

        if (el.scannerStatusText) {
            el.scannerStatusText.textContent =
                "Running";
        }

        if (el.scannerStage) {
            el.scannerStage.textContent =
                "scanning";
        }

        if (el.scannerProgressBar) {
            el.scannerProgressBar.style.width =
                "40%";
        }

        try {
            const response = await fetch(
                api.scanRefresh,
                {
                    method: "POST",
                    credentials: "same-origin",

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
                error.message
                || "Scanner refresh failed."
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
    // DETAIL DRAWER
    // =========================================================

    function openDrawer() {
        state.drawerOpen = true;

        el.drawer?.classList.add("open");

        el.drawer?.setAttribute(
            "aria-hidden",
            "false"
        );

        document.body.style.overflow =
            "hidden";
    }


    function closeDrawer() {
        state.drawerOpen = false;

        el.drawer?.classList.remove("open");

        el.drawer?.setAttribute(
            "aria-hidden",
            "true"
        );

        document.body.style.overflow =
            "";
    }


    function renderBoolean(value) {
        if (value === true) {
            return `
                <span class="status-pass">
                    PASS
                </span>
            `;
        }

        if (value === false) {
            return `
                <span class="status-fail">
                    FAIL
                </span>
            `;
        }

        return "—";
    }


    function renderDetailReasons(reasons) {
        if (
            !Array.isArray(reasons)
            || !reasons.length
        ) {
            return `
                <div class="detail-empty">
                    No confirmation details available.
                </div>
            `;
        }

        return `
            <ul class="reason-list">
                ${reasons.map(
                    reason => `
                        <li>
                            ${escapeHtml(reason)}
                        </li>
                    `
                ).join("")}
            </ul>
        `;
    }


    function renderStockDetail(payload) {
        if (!el.drawerContent) {
            return;
        }

        /*
         * Current app.py single-stock API returns:
         *
         * {
         *   stock: {
         *      symbol,
         *      fyers_symbol,
         *      mode,
         *      technical: {...},
         *      patterns: {...}
         *   }
         * }
         *
         * Final saved signal can also contain
         * flat fields. Merge both formats.
         */

        const root =
            payload?.stock
            || payload
            || {};

        const technical =
            root.technical
            && typeof root.technical === "object"
                ? root.technical
                : {};

        const patterns =
            root.patterns
            && typeof root.patterns === "object"
                ? root.patterns
                : {};

        const data = {
            ...root,
            ...technical
        };

        const chartPattern =
            data.chart_pattern
            || patterns.chart_pattern
            || patterns.pattern
            || patterns.name
            || "—";

        const candlePattern =
            data.candlestick_pattern
            || data.candle_pattern
            || patterns.candlestick_pattern
            || "—";

        if (el.drawerTitle) {
            el.drawerTitle.textContent =
                getCompanyName(data);
        }

        el.drawerContent.innerHTML = `

            <section class="detail-summary-grid">

                <article class="detail-summary-card">
                    <span>Stock</span>
                    <strong>
                        ${escapeHtml(
                            data.symbol || "—"
                        )}
                    </strong>
                </article>

                <article class="detail-summary-card">
                    <span>Mode</span>
                    <strong>
                        ${escapeHtml(
                            root.mode || state.mode
                        )}
                    </strong>
                </article>

                <article class="detail-summary-card">
                    <span>Signal</span>
                    <strong>
                        ${escapeHtml(
                            data.signal || "ANALYSIS"
                        )}
                    </strong>
                </article>

                <article class="detail-summary-card">
                    <span>Current Price</span>
                    <strong>
                        ${formatPrice(
                            data.current_price
                        )}
                    </strong>
                </article>

                <article class="detail-summary-card">
                    <span>Entry</span>
                    <strong>
                        ${formatPrice(
                            data.entry_price
                        )}
                    </strong>
                </article>

                <article class="detail-summary-card">
                    <span>Stop Loss</span>
                    <strong>
                        ${formatPrice(
                            data.stop_loss
                        )}
                    </strong>
                </article>

                <article class="detail-summary-card">
                    <span>Target</span>
                    <strong>
                        ${formatPrice(
                            data.target_price
                            ?? data.target
                        )}
                    </strong>
                </article>

                <article class="detail-summary-card">
                    <span>Technical Score</span>
                    <strong>
                        ${formatNumber(
                            data.technical_score
                            ?? data.score
                        )}
                    </strong>
                </article>

                <article class="detail-summary-card">
                    <span>RSI</span>
                    <strong>
                        ${formatNumber(data.rsi)}
                    </strong>
                </article>

            </section>


            <section class="detail-section">

                <div class="detail-section-heading">
                    <div>
                        <p class="eyebrow">
                            TECHNICAL CONDITIONS
                        </p>

                        <h3>
                            Trend & Momentum
                        </h3>
                    </div>
                </div>

                <div class="detail-stat-grid">

                    <article>
                        <span>EMA Bullish</span>
                        <strong>
                            ${renderBoolean(
                                data.ema_bullish
                            )}
                        </strong>
                    </article>

                    <article>
                        <span>MACD Bullish</span>
                        <strong>
                            ${renderBoolean(
                                data.macd_bullish
                            )}
                        </strong>
                    </article>

                    <article>
                        <span>Supertrend</span>
                        <strong>
                            ${renderBoolean(
                                data.supertrend_bullish
                            )}
                        </strong>
                    </article>

                    <article>
                        <span>Above VWAP</span>
                        <strong>
                            ${renderBoolean(
                                data.above_vwap
                            )}
                        </strong>
                    </article>

                    <article>
                        <span>Volume Ratio</span>
                        <strong>
                            ${formatNumber(
                                data.volume_ratio
                            )}
                        </strong>
                    </article>

                    <article>
                        <span>Breakout</span>
                        <strong>
                            ${renderBoolean(
                                data.breakout
                            )}
                        </strong>
                    </article>

                </div>

            </section>


            <section class="detail-section">

                <div class="detail-section-heading">
                    <div>
                        <p class="eyebrow">
                            PATTERN ANALYSIS
                        </p>

                        <h3>
                            Chart & Candlestick
                        </h3>
                    </div>
                </div>

                <div class="detail-stat-grid">

                    <article>
                        <span>Chart Pattern</span>
                        <strong>
                            ${escapeHtml(
                                chartPattern
                            )}
                        </strong>
                    </article>

                    <article>
                        <span>Candlestick</span>
                        <strong>
                            ${escapeHtml(
                                candlePattern
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
                            Technical Reasons
                        </h3>
                    </div>
                </div>

                ${renderDetailReasons(
                    data.reasons
                    || technical.reasons
                    || patterns.reasons
                )}

            </section>
        `;
    }


    async function loadStockDetail(symbol) {
        const cleanSymbol =
            normalizeText(symbol);

        if (!cleanSymbol) {
            return;
        }

        openDrawer();

        if (el.drawerTitle) {
            el.drawerTitle.textContent =
                cleanSymbol;
        }

        if (el.drawerContent) {
            el.drawerContent.innerHTML = `
                <div class="detail-loading">
                    Loading verified technical analysis...
                </div>
            `;
        }

        try {
            const base =
                api.stockDetailBase
                || "/api/stock/";

            const url = new URL(
                `${base}${encodeURIComponent(
                    cleanSymbol
                )}`,
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
                        Accept: "application/json"
                    }
                }
            );

            const payload =
                await parseResponse(response);

            renderStockDetail(payload);

        } catch (error) {
            if (el.drawerContent) {
                el.drawerContent.innerHTML = `
                    <div class="detail-error">
                        ${escapeHtml(
                            error.message
                            || "Technical analysis failed."
                        )}
                    </div>
                `;
            }
        }
    }


    function bindDetailButtons() {
        document.querySelectorAll(
            ".detail-button[data-symbol]"
        ).forEach(button => {
            if (
                button.dataset.eagleBound
                === "1"
            ) {
                return;
            }

            button.dataset.eagleBound = "1";

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
    // MODE CHANGE
    // =========================================================

    function setActiveMode(value) {
        const mode =
            normalizeMode(value);

        if (mode === state.mode) {
            return;
        }

        state.mode = mode;

        state.results = [];
        state.topSectors = [];
        state.sectorStocks = [];
        state.selectedSector = "";

        state.signalsInitialized = false;

        state.knownStrongBuySymbols =
            new Set();

        document.querySelectorAll(
            ".timeframe-tab"
        ).forEach(button => {
            const buttonMode =
                normalizeMode(
                    button.dataset.mode
                    || button.dataset.timeframe
                );

            button.classList.toggle(
                "active",
                buttonMode === mode
            );
        });

        if (el.selectedSectorTitle) {
            el.selectedSectorTitle.textContent =
                "Select a Sector";
        }

        if (el.sectorStockCount) {
            el.sectorStockCount.textContent =
                "0 stocks";
        }

        if (el.sectorStocksUpdatedAt) {
            el.sectorStocksUpdatedAt.textContent =
                "Tap a Top Sector above";
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

        const url =
            new URL(window.location.href);

        url.searchParams.set(
            "mode",
            mode
        );

        url.searchParams.delete(
            "timeframe"
        );

        window.history.replaceState(
            {},
            "",
            url.toString()
        );

        fetchSignals();
        fetchScannerStatus();
    }


    // =========================================================
    // EVENT BINDINGS
    // =========================================================

    function bindFilters() {
        el.sectorFilter?.addEventListener(
            "change",
            event => {
                state.filters.sector =
                    event.target.value;

                renderSignalTable();
            }
        );

        el.technicalScoreFilter
            ?.addEventListener(
                "change",
                event => {
                    state.filters
                        .minimumTechnicalScore =
                        event.target.value;

                    renderSignalTable();
                }
            );

        el.patternFilter?.addEventListener(
            "change",
            event => {
                state.filters.chartPattern =
                    event.target.value;

                renderSignalTable();
            }
        );

        el.resetFiltersButton
            ?.addEventListener(
                "click",
                () => {
                    state.filters = {
                        sector: "",
                        minimumTechnicalScore: "",
                        chartPattern: ""
                    };

                    if (el.sectorFilter) {
                        el.sectorFilter.value = "";
                    }

                    if (
                        el.technicalScoreFilter
                    ) {
                        el.technicalScoreFilter.value =
                            "";
                    }

                    if (el.patternFilter) {
                        el.patternFilter.value =
                            "";
                    }

                    renderSignalTable();
                }
            );
    }


    function bindModeButtons() {
        el.timeframeTabs?.addEventListener(
            "click",
            event => {
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


    function bindDrawer() {
        el.closeDrawerButton
            ?.addEventListener(
                "click",
                closeDrawer
            );

        el.drawer
            ?.querySelector(
                ".detail-drawer-backdrop"
            )
            ?.addEventListener(
                "click",
                closeDrawer
            );

        document.addEventListener(
            "keydown",
            event => {
                if (
                    event.key === "Escape"
                    && state.drawerOpen
                ) {
                    closeDrawer();
                }
            }
        );
    }


    // =========================================================
    // INITIALIZE
    // =========================================================

    function initialize() {
        bindFilters();
        bindModeButtons();
        bindDrawer();
        bindDetailButtons();

        el.manualRefreshButton
            ?.addEventListener(
                "click",
                triggerManualRefresh
            );

        document.querySelectorAll(
            ".timeframe-tab"
        ).forEach(button => {
            const buttonMode =
                normalizeMode(
                    button.dataset.mode
                    || button.dataset.timeframe
                );

            button.classList.toggle(
                "active",
                buttonMode === state.mode
            );
        });

        fetchSignals();
        fetchScannerStatus();
    }


    // =========================================================
    // PUBLIC API
    // =========================================================

    window.EagleDashboard = {
        state,
        fetchSignals,
        fetchScannerStatus,
        fetchSectorStocks,
        selectSector,
        loadStockDetail,
        triggerManualRefresh,
        renderSignalTable,
        renderTopSectors,
        renderSectorStocks,
        renderScannerStatus,
        setActiveMode,
        speakStrongBuy
    };


    document.addEventListener(
        "DOMContentLoaded",
        initialize
    );

})();
